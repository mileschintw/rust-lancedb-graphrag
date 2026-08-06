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

use std::collections::HashMap;
use std::fmt::{Display, Formatter};

use lance_graph::config::{GraphConfigBuilder, RelationshipMapping};
use lance_graph::query::{CypherQuery, ExecutionStrategy};

pub mod bridge;

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
