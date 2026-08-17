//! Checked-in Phase 04 spike proof-of-concept for `lance-graph` Cypher traversal.
//!
//! Gated behind the `graph-spike` Cargo feature and invisible to the default
//! build. Reproduces 04-RESEARCH.md's empirically proven bridge-plus-Cypher
//! patterns (fixed single-hop, multi-hop, open-vocabulary `relation_type`
//! filtering) as passing, checked-in tests rather than a deleted scratch crate.
//! Every traversal function pre-narrows nothing itself — callers are expected
//! to hand in an already-narrowed `entities`/`edges` neighborhood — bridges
//! both batches into lance-graph's arrow tree via [`bridge`], executes a
//! Cypher query, and bridges the single-`RecordBatch` result back.

use std::collections::{HashMap, HashSet};
use std::fmt::{Display, Formatter};
use std::sync::Arc;

use futures::TryStreamExt;
use lance_graph::config::{GraphConfigBuilder, RelationshipMapping};
use lance_graph::query::{CypherQuery, ExecutionStrategy};
use lancedb::query::{ExecutableQuery, QueryBase};
use uuid::Uuid;

use arrow_array::Array;
use arrow_select::concat::concat_batches;
use arrow_select::filter::filter_record_batch;

pub(crate) mod bridge;
pub mod context_strategy;
pub mod extraction;

#[cfg(test)]
mod tests;

/// Identifies the category of failure raised by the graph-spike PoC.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GraphSpikeErrorKind {
    Bridge,
    GraphConfig,
    CypherParse,
    CypherExecute,
    InvalidHopCap,
}

/// A typed graph-spike error with a stable category and human-readable context.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphSpikeError {
    pub kind: GraphSpikeErrorKind,
    message: String,
}

impl GraphSpikeError {
    pub(crate) fn new(kind: GraphSpikeErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
    }

    pub fn message(&self) -> &str {
        &self.message
    }
}

impl Display for GraphSpikeError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for GraphSpikeError {}

/// Upper bound on caller-requested traversal hop depth (D-23's Claude's-Discretion default).
pub const MAX_HOP_CAP: u32 = 3;

/// Maximum byte length accepted for a caller-supplied `seed_entity_name` (T-04.1-19).
///
/// Matches the extraction JSON-Schema's own `name` `maxLength` bound from AI-SPEC §4b.1,
/// reusing an existing bound rather than introducing an arbitrary new ceiling.
pub const MAX_SEED_ENTITY_NAME_BYTES: usize = 512;

/// Maximum byte length accepted for a caller-supplied `relation_type_filter` (T-04.1-19).
///
/// Matches the extraction JSON-Schema's own `relation_type` `maxLength` bound from
/// AI-SPEC §4b.1.
pub const MAX_RELATION_TYPE_FILTER_BYTES: usize = 128;

/// Clamps a requested hop count to the `[1, MAX_HOP_CAP]` range.
///
/// This guard runs before `hop_cap` is ever interpolated into a `format!`-built
/// Cypher string (Cypher cannot parameterize a variable-length path bound) — the
/// V5 input-validation mitigation from 04-RESEARCH.md's Security Domain.
///
/// # Errors
/// Returns a [`GraphSpikeError`] with kind [`GraphSpikeErrorKind::InvalidHopCap`]
/// if `requested` is `0` or greater than [`MAX_HOP_CAP`].
pub fn clamp_hop_cap(requested: u32) -> Result<u32, GraphSpikeError> {
    if requested == 0 || requested > MAX_HOP_CAP {
        return Err(GraphSpikeError::new(
            GraphSpikeErrorKind::InvalidHopCap,
            format!("hop_cap must be between 1 and {MAX_HOP_CAP}, got {requested}"),
        ));
    }
    Ok(requested)
}

/// Clamps a requested hop count against a configurable ceiling.
///
/// This is the `QueryGraph`-specific variant of [`clamp_hop_cap`] that takes a
/// caller-configured maximum (`configured_max`) read from `GraphSettings.max_hop_cap`
/// rather than relying solely on the compile-time [`MAX_HOP_CAP`] constant.
///
/// The effective ceiling is `min(MAX_HOP_CAP, configured_max)`: if the operator
/// sets a `max_hop_cap` above the compile-time bound it is silently capped to
/// `MAX_HOP_CAP` (defence in depth against a misconfigured TOML value), then the
/// same `0 / > effective_max` rejection logic as [`clamp_hop_cap`] applies.
///
/// # Errors
/// Returns a [`GraphSpikeError`] with kind [`GraphSpikeErrorKind::InvalidHopCap`]
/// if `requested` is `0` or greater than the effective ceiling.
pub fn clamp_hop_cap_with_ceiling(
    requested: u32,
    configured_max: u32,
) -> Result<u32, GraphSpikeError> {
    let effective_max = MAX_HOP_CAP.min(configured_max);
    if requested == 0 || requested > effective_max {
        return Err(GraphSpikeError::new(
            GraphSpikeErrorKind::InvalidHopCap,
            format!(
                "hop_depth must be between 1 and {effective_max} (configured ceiling), got {requested}"
            ),
        ));
    }
    Ok(requested)
}

/// Runs a fixed single-hop Cypher query, projecting the matched relationship's properties.
///
/// Bridges `entities`/`edges` into lance-graph's arrow tree, matches every `RELATED`
/// neighbor of `seed_id` in exactly one hop, and returns `seed.entity_id`,
/// `r.relation_type`, `neighbor.entity_id`, and `neighbor.name`. Fixed-length (non
/// variable-length) patterns can project the relationship-pattern variable directly
/// (04-RESEARCH.md Pitfall 6) — the case [`traverse_multi_hop`] cannot use.
///
/// # Errors
/// Returns a [`GraphSpikeError`] if bridging, graph configuration, Cypher parsing,
/// or Cypher execution fails.
pub async fn traverse_fixed_hop(
    entities: &arrow_array::RecordBatch,
    edges: &arrow_array::RecordBatch,
    seed_id: &str,
) -> Result<arrow_array::RecordBatch, GraphSpikeError> {
    let entities_lg = bridge::bridge_batch(entities)?;
    let edges_lg = bridge::bridge_batch(edges)?;

    let config = GraphConfigBuilder::new()
        .with_node_label("Entity", "entity_id")
        .with_default_relationship_type_field("relation_type")
        .with_relationship_mapping(RelationshipMapping {
            relationship_type: "RELATED".into(),
            source_id_field: "source_node_id".into(),
            target_id_field: "target_node_id".into(),
            type_field: Some("relation_type".into()),
            property_fields: vec!["relation_type".into()],
            filter_conditions: None,
        })
        .build()
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::GraphConfig, format!("graph config: {e}")))?;

    let mut datasets = HashMap::new();
    datasets.insert("Entity".to_string(), entities_lg);
    datasets.insert("RELATED".to_string(), edges_lg);

    let cypher = "MATCH (seed:Entity {entity_id: $seed_id})-[r:RELATED]-(neighbor:Entity) \
         RETURN seed.entity_id, r.relation_type, neighbor.entity_id, neighbor.name";
    let query = CypherQuery::new(cypher)
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::CypherParse, format!("cypher parse: {e}")))?
        .with_config(config)
        .with_parameter("seed_id", seed_id);

    let result_lg = query
        .execute(datasets, None::<ExecutionStrategy>)
        .await
        .map_err(|e| {
            GraphSpikeError::new(GraphSpikeErrorKind::CypherExecute, format!("cypher execute: {e}"))
        })?;

    bridge::bridge_batch_back(&result_lg)
}

/// Runs a variable-length (`*1..hop_cap`) Cypher traversal, returning matched neighbors.
///
/// `hop_cap` is clamped via [`clamp_hop_cap`] before it is ever interpolated into the
/// `format!`-built Cypher string — Cypher cannot parameterize a variable-length path
/// bound, so this is the V5 input-validation guard from 04-RESEARCH.md's Security
/// Domain. Per 04-RESEARCH.md Pitfall 6, the relationship-pattern variable (`r`) is
/// omitted from `RETURN` — variable-length quantifiers cannot project it.
///
/// # Errors
/// Returns a [`GraphSpikeError`] if `hop_cap` is out of range, or if bridging, graph
/// configuration, Cypher parsing, or Cypher execution fails.
pub async fn traverse_multi_hop(
    entities: &arrow_array::RecordBatch,
    edges: &arrow_array::RecordBatch,
    seed_id: &str,
    hop_cap: u32,
) -> Result<arrow_array::RecordBatch, GraphSpikeError> {
    let hop_cap = clamp_hop_cap(hop_cap)?;

    let entities_lg = bridge::bridge_batch(entities)?;
    let edges_lg = bridge::bridge_batch(edges)?;

    let config = GraphConfigBuilder::new()
        .with_node_label("Entity", "entity_id")
        .with_default_relationship_type_field("relation_type")
        .with_relationship("RELATED", "source_node_id", "target_node_id")
        .build()
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::GraphConfig, format!("graph config: {e}")))?;

    let mut datasets = HashMap::new();
    datasets.insert("Entity".to_string(), entities_lg);
    datasets.insert("RELATED".to_string(), edges_lg);

    let cypher = format!(
        "MATCH (seed:Entity {{entity_id: $seed_id}})-[r:RELATED*1..{hop_cap}]-(neighbor:Entity) \
         RETURN seed.entity_id, neighbor.entity_id, neighbor.name"
    );
    let query = CypherQuery::new(&cypher)
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::CypherParse, format!("cypher parse: {e}")))?
        .with_config(config)
        .with_parameter("seed_id", seed_id);

    let result_lg = query
        .execute(datasets, None::<ExecutionStrategy>)
        .await
        .map_err(|e| {
            GraphSpikeError::new(GraphSpikeErrorKind::CypherExecute, format!("cypher execute: {e}"))
        })?;

    bridge::bridge_batch_back(&result_lg)
}

/// Matches `RELATED` neighbors of `seed_id` whose `relation_type` equals `relation_type`.
///
/// Both `seed_id` and `relation_type` are passed as Cypher `$parameter` bindings, never
/// string-interpolated — ordinary value predicates parameterize safely, unlike the
/// hop-count bound [`traverse_multi_hop`] must clamp and interpolate.
///
/// # Errors
/// Returns a [`GraphSpikeError`] if bridging, graph configuration, Cypher parsing, or
/// Cypher execution fails.
pub async fn traverse_filtered_by_relation_type(
    entities: &arrow_array::RecordBatch,
    edges: &arrow_array::RecordBatch,
    seed_id: &str,
    relation_type: &str,
) -> Result<arrow_array::RecordBatch, GraphSpikeError> {
    let entities_lg = bridge::bridge_batch(entities)?;
    let edges_lg = bridge::bridge_batch(edges)?;

    let config = GraphConfigBuilder::new()
        .with_node_label("Entity", "entity_id")
        .with_default_relationship_type_field("relation_type")
        .with_relationship("RELATED", "source_node_id", "target_node_id")
        .build()
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::GraphConfig, format!("graph config: {e}")))?;

    let mut datasets = HashMap::new();
    datasets.insert("Entity".to_string(), entities_lg);
    datasets.insert("RELATED".to_string(), edges_lg);

    let cypher = "MATCH (seed:Entity {entity_id: $seed_id})-[r:RELATED]-(neighbor:Entity) \
         WHERE r.relation_type = $relation_type \
         RETURN neighbor.entity_id, neighbor.name";
    let query = CypherQuery::new(cypher)
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::CypherParse, format!("cypher parse: {e}")))?
        .with_config(config)
        .with_parameter("seed_id", seed_id)
        .with_parameter("relation_type", relation_type);

    let result_lg = query
        .execute(datasets, None::<ExecutionStrategy>)
        .await
        .map_err(|e| {
            GraphSpikeError::new(GraphSpikeErrorKind::CypherExecute, format!("cypher execute: {e}"))
        })?;

    bridge::bridge_batch_back(&result_lg)
}

pub fn escape_sql_literal(value: &str) -> String {
    value.replace('\'', "''")
}

pub const MAX_FRONTIER_SIZE: usize = 200;
pub const MAX_TOTAL_EDGES: usize = 500;

/// Bounded multi-hop neighborhood fetch over `entity_edges_table()`.
///
/// Fetches nodes and edges within `hop_cap` steps of `seed_entity_id`, querying `entity_edges_table()`
/// exclusively. Enforces `MAX_FRONTIER_SIZE` and `MAX_TOTAL_EDGES` bounds (enforced against distinct edge_id values), returning a [`GraphSpikeError`]
/// if exceeded rather than silently truncating. Returns the bridged `entities` batch (including the seed entity)
/// and `entity_edges` batch.
pub async fn fetch_neighborhood(
    db: &crate::db::DatabaseManager,
    seed_entity_id: &str,
    hop_cap: u32,
    bidirectional: bool,
) -> Result<(arrow_array::RecordBatch, arrow_array::RecordBatch), GraphSpikeError> {
    Uuid::parse_str(seed_entity_id).map_err(|e| {
        GraphSpikeError::new(
            GraphSpikeErrorKind::Bridge,
            format!("invalid seed entity ID '{seed_entity_id}': {e}"),
        )
    })?;

    let hop_cap = clamp_hop_cap(hop_cap)?;

    let mut frontier: HashSet<String> = HashSet::from([seed_entity_id.to_string()]);
    let mut visited: HashSet<String> = HashSet::from([seed_entity_id.to_string()]);
    let mut accumulated_edge_batches: Vec<arrow_array::RecordBatch> = Vec::new();
    let mut seen_edge_ids: HashSet<String> = HashSet::new();

    for _hop in 1..=hop_cap {
        let escaped_ids: Vec<String> = frontier
            .iter()
            .map(|id| format!("'{}'", escape_sql_literal(id)))
            .collect();
        let in_list = escaped_ids.join(",");
        let predicate = if bidirectional {
            format!("source_node_id IN ({in_list}) OR target_node_id IN ({in_list})")
        } else {
            format!("source_node_id IN ({in_list})")
        };

        let edges_table = db
            .entity_edges_table()
            .await
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, e.to_string()))?;

        let edge_batches: Vec<arrow_array::RecordBatch> = edges_table
            .query()
            .only_if(predicate)
            .select(lancedb::query::Select::columns(&[
                "edge_id",
                "source_node_id",
                "target_node_id",
                "relation_type",
                "weight",
            ]))
            .execute()
            .await
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, e.to_string()))?
            .try_collect()
            .await
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, e.to_string()))?;

        for batch in &edge_batches {
            let edge_id_col = batch
                .column_by_name("edge_id")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
                .ok_or_else(|| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, "missing edge_id column"))?;
            for i in 0..batch.num_rows() {
                seen_edge_ids.insert(edge_id_col.value(i).to_string());
            }
        }

        if seen_edge_ids.len() > MAX_TOTAL_EDGES {
            return Err(GraphSpikeError::new(
                GraphSpikeErrorKind::Bridge,
                format!(
                    "accumulated distinct edge count {} exceeds MAX_TOTAL_EDGES {}",
                    seen_edge_ids.len(),
                    MAX_TOTAL_EDGES
                ),
            ));
        }

        let mut next_frontier = HashSet::new();
        for batch in &edge_batches {
            let src_col = batch
                .column_by_name("source_node_id")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
            let tgt_col = batch
                .column_by_name("target_node_id")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());

            if let (Some(src_col), Some(tgt_col)) = (src_col, tgt_col) {
                for i in 0..batch.num_rows() {
                    if !src_col.is_null(i) {
                        let src = src_col.value(i);
                        if !visited.contains(src) {
                            next_frontier.insert(src.to_string());
                        }
                    }
                    if !tgt_col.is_null(i) {
                        let tgt = tgt_col.value(i);
                        if !visited.contains(tgt) {
                            next_frontier.insert(tgt.to_string());
                        }
                    }
                }
            }
        }

        if next_frontier.len() > MAX_FRONTIER_SIZE {
            return Err(GraphSpikeError::new(
                GraphSpikeErrorKind::Bridge,
                format!(
                    "frontier size {} exceeds MAX_FRONTIER_SIZE {}",
                    next_frontier.len(),
                    MAX_FRONTIER_SIZE
                ),
            ));
        }

        accumulated_edge_batches.extend(edge_batches);
        visited.extend(next_frontier.clone());
        frontier = next_frontier;

        if frontier.is_empty() {
            break;
        }
    }

    let escaped_visited: Vec<String> = visited
        .iter()
        .map(|id| format!("'{}'", escape_sql_literal(id)))
        .collect();
    let visited_in_list = escaped_visited.join(",");
    let entities_predicate = format!("entity_id IN ({visited_in_list})");
    let entities_table = db
        .entities_table()
        .await
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, e.to_string()))?;

    let entities_batches: Vec<arrow_array::RecordBatch> = entities_table
        .query()
        .only_if(entities_predicate)
        .select(lancedb::query::Select::columns(&[
            "entity_id",
            "name",
            "entity_type",
        ]))
        .execute()
        .await
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, e.to_string()))?
        .try_collect()
        .await
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, e.to_string()))?;

    let entities_schema = Arc::new(arrow_schema::Schema::new(vec![
        arrow_schema::Field::new("entity_id", arrow_schema::DataType::Utf8, false),
        arrow_schema::Field::new("name", arrow_schema::DataType::Utf8, false),
        arrow_schema::Field::new("entity_type", arrow_schema::DataType::Utf8, false),
    ]));

    let edges_schema = Arc::new(arrow_schema::Schema::new(vec![
        arrow_schema::Field::new("edge_id", arrow_schema::DataType::Utf8, false),
        arrow_schema::Field::new("source_node_id", arrow_schema::DataType::Utf8, false),
        arrow_schema::Field::new("target_node_id", arrow_schema::DataType::Utf8, false),
        arrow_schema::Field::new("relation_type", arrow_schema::DataType::Utf8, false),
        arrow_schema::Field::new("weight", arrow_schema::DataType::Float32, false),
    ]));

    let entities_batch = if entities_batches.is_empty() {
        arrow_array::RecordBatch::new_empty(entities_schema)
    } else {
        concat_batches(&entities_schema, &entities_batches)
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("concat entities: {e}")))?
    };

    let edges_batch = if accumulated_edge_batches.is_empty() {
        arrow_array::RecordBatch::new_empty(edges_schema)
    } else {
        let concatenated = concat_batches(&edges_schema, &accumulated_edge_batches)
            .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("concat edges: {e}")))?;
        // Bidirectional per-hop querying re-matches an edge already accumulated in a
        // prior hop once its OTHER endpoint enters a later frontier (e.g. seed--A-->B
        // fetched at hop 1 via seed's frontier, then re-fetched at hop 2 once B enters
        // the frontier and the bidirectional predicate matches B as an endpoint again).
        // Deduplicate before returning so the response never double-counts an edge.
        dedup_edges_by_identity(&concatenated)?
    };

    Ok((entities_batch, edges_batch))
}

/// Deduplicates edge rows re-fetched across multiple BFS hops in [`fetch_neighborhood`].
///
/// Identity is `edge_id` — the `entity_edges` table's own `Uuid::new_v4()`-generated
/// unique identifier set once per edge at creation time, now selected into this
/// function's input batch. This correctly distinguishes a genuinely distinct edge
/// from the same edge merely re-observed across a later bidirectional BFS hop,
/// unlike a value-tuple two unrelated edges can coincidentally share.
fn dedup_edges_by_identity(
    edges: &arrow_array::RecordBatch,
) -> Result<arrow_array::RecordBatch, GraphSpikeError> {
    let edge_id_col = edges
        .column_by_name("edge_id")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
        .ok_or_else(|| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, "missing edge_id column"))?;

    let mut seen: HashSet<String> = HashSet::new();
    let mask: arrow_array::BooleanArray = (0..edges.num_rows())
        .map(|i| {
            let key = edge_id_col.value(i).to_string();
            Some(seen.insert(key))
        })
        .collect();

    filter_record_batch(edges, &mask).map_err(|e| {
        GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("filter deduped edges failed: {e}"))
    })
}

fn extract_neighbor_ids(
    result_batch: &arrow_array::RecordBatch,
) -> Result<HashSet<String>, GraphSpikeError> {
    let neighbor_col = result_batch
        .column_by_name("neighbor.entity_id")
        .ok_or_else(|| {
            GraphSpikeError::new(
                GraphSpikeErrorKind::Bridge,
                "missing neighbor.entity_id column in Cypher result",
            )
        })?;
    let string_array = neighbor_col
        .as_any()
        .downcast_ref::<arrow_array::StringArray>()
        .ok_or_else(|| {
            GraphSpikeError::new(
                GraphSpikeErrorKind::Bridge,
                "neighbor.entity_id is not a StringArray",
            )
        })?;

    let mut confirmed = HashSet::new();
    for i in 0..string_array.len() {
        if !string_array.is_null(i) {
            confirmed.insert(string_array.value(i).to_string());
        }
    }
    Ok(confirmed)
}

/// Swaps `source_node_id` and `target_node_id` column arrays in `edges`.
///
/// `lance-graph` 0.5.4's relationship mapping is strictly directed; this helper
/// allows querying reversed edges without mutating the schema or other columns.
fn reverse_edge_endpoints(
    edges: &arrow_array::RecordBatch,
) -> Result<arrow_array::RecordBatch, GraphSpikeError> {
    let source_idx = edges
        .schema()
        .index_of("source_node_id")
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("missing source_node_id: {e}")))?;
    let target_idx = edges
        .schema()
        .index_of("target_node_id")
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("missing target_node_id: {e}")))?;

    let mut columns = edges.columns().to_vec();
    columns.swap(source_idx, target_idx);

    arrow_array::RecordBatch::try_new(edges.schema(), columns)
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("swap edge columns failed: {e}")))
}

/// Executes Cypher traversal in both forward and reversed directions to confirm reachable neighbors.
///
/// Note on limitation: A path that changes direction partway through a multi-hop chain
/// (e.g. seed -> A <- B) is not confirmed by either direction alone.
pub(crate) async fn cypher_confirmed_neighbor_ids(
    entities: &arrow_array::RecordBatch,
    edges: &arrow_array::RecordBatch,
    seed_id: &str,
    hop_cap: u32,
) -> Result<HashSet<String>, GraphSpikeError> {
    let forward_batch = traverse_multi_hop(entities, edges, seed_id, hop_cap).await?;
    let mut confirmed = extract_neighbor_ids(&forward_batch)?;

    let reversed_edges = reverse_edge_endpoints(edges)?;
    let reverse_batch = traverse_multi_hop(entities, &reversed_edges, seed_id, hop_cap).await?;
    confirmed.extend(extract_neighbor_ids(&reverse_batch)?);

    Ok(confirmed)
}

pub(crate) fn constrain_to_cypher_matched(
    entities: &arrow_array::RecordBatch,
    edges: &arrow_array::RecordBatch,
    seed_id: &str,
    cypher_neighbor_ids: &HashSet<String>,
) -> Result<(arrow_array::RecordBatch, arrow_array::RecordBatch), GraphSpikeError> {
    let mut allowed_ids = cypher_neighbor_ids.clone();
    allowed_ids.insert(seed_id.to_string());

    let source_col = edges
        .column_by_name("source_node_id")
        .ok_or_else(|| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, "missing source_node_id column"))?
        .as_any()
        .downcast_ref::<arrow_array::StringArray>()
        .ok_or_else(|| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, "source_node_id is not a StringArray"))?;

    let target_col = edges
        .column_by_name("target_node_id")
        .ok_or_else(|| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, "missing target_node_id column"))?
        .as_any()
        .downcast_ref::<arrow_array::StringArray>()
        .ok_or_else(|| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, "target_node_id is not a StringArray"))?;

    let edge_mask: arrow_array::BooleanArray = (0..edges.num_rows())
        .map(|i| {
            if source_col.is_null(i) || target_col.is_null(i) {
                Some(false)
            } else {
                Some(allowed_ids.contains(source_col.value(i)) && allowed_ids.contains(target_col.value(i)))
            }
        })
        .collect();

    let constrained_edges = filter_record_batch(edges, &edge_mask)
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("filter edges failed: {e}")))?;

    let entity_id_col = entities
        .column_by_name("entity_id")
        .ok_or_else(|| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, "missing entity_id column"))?
        .as_any()
        .downcast_ref::<arrow_array::StringArray>()
        .ok_or_else(|| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, "entity_id is not a StringArray"))?;

    let entity_mask: arrow_array::BooleanArray = (0..entities.num_rows())
        .map(|i| {
            if entity_id_col.is_null(i) {
                Some(false)
            } else {
                Some(allowed_ids.contains(entity_id_col.value(i)))
            }
        })
        .collect();

    let constrained_entities = filter_record_batch(entities, &entity_mask)
        .map_err(|e| GraphSpikeError::new(GraphSpikeErrorKind::Bridge, format!("filter entities failed: {e}")))?;

    Ok((constrained_entities, constrained_edges))
}

pub async fn narrow_via_cypher(
    entities: &arrow_array::RecordBatch,
    edges: &arrow_array::RecordBatch,
    seed_id: &str,
    hop_cap: u32,
) -> (arrow_array::RecordBatch, arrow_array::RecordBatch) {
    match cypher_confirmed_neighbor_ids(entities, edges, seed_id, hop_cap).await {
        Ok(confirmed_ids) => {
            match constrain_to_cypher_matched(entities, edges, seed_id, &confirmed_ids) {
                Ok(res) => res,
                Err(err) => {
                    tracing::warn!(kind = ?err.kind, "constrain_to_cypher_matched failed, falling back to unconstrained");
                    (entities.clone(), edges.clone())
                }
            }
        }
        Err(err) => {
            tracing::warn!(kind = ?err.kind, "cypher_confirmed_neighbor_ids failed, falling back to unconstrained");
            (entities.clone(), edges.clone())
        }
    }
}

