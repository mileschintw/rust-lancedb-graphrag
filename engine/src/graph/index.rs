//! Immutable per-generation lookup structures for graph seeding and path search.
//!
//! [`GraphIndex`] is built once from one `entities` scan and one `entity_edges` scan and is never
//! mutated afterwards. It holds the name maps that mention matching reads, the entity degree that
//! path ranking and the hub cap read, and the entity-to-source-chunk provenance that candidate
//! chunk selection reads. Because the structure is rebuilt for a new index generation instead of
//! being updated per query, it cannot grow with query volume, which is what separates it from the
//! per-query accumulators that the OI-02 investigation looked for (RESEARCH Pattern 2).
//!
//! Degree is counted the same way `inspect_lancedb --graph-population` counts it: every edge adds
//! one to its source and one to its target, so a self-loop adds two. That keeps
//! [`GraphIndex::degree_percentile`] comparable with the post-reconcile degree distribution that
//! the hub cap was derived from.

use std::collections::HashMap;

use arrow_array::{Array, ListArray, RecordBatch, StringArray};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};

use crate::db::DatabaseManager;

/// One `entities` row as the index consumes it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntityRecord {
    /// The entity's UUID string.
    pub entity_id: String,
    /// The entity's display name, as extracted from the corpus.
    pub name: String,
    /// Chunk IDs (`{document_id}:{chunk_index}`) that this entity was extracted from.
    pub source_chunk_ids: Vec<String>,
}

/// Name index, degree and provenance maps built once from one scan of each table.
///
/// All lookups return sorted, de-duplicated data, so two builds of the same store give the same
/// answers regardless of scan order.
#[derive(Debug, Clone, Default)]
pub struct GraphIndex {
    name_casefold: HashMap<String, Vec<String>>,
    name_normalized: HashMap<String, Vec<String>>,
    degree: HashMap<String, u32>,
    entity_chunks: HashMap<String, Vec<String>>,
    entity_names: HashMap<String, String>,
}

/// Lower-cases a name for exact matching.
///
/// This is `str::to_lowercase`, the same fold `inspect_lancedb`'s name lookup uses, so an exact
/// seed match agrees with what the store inspection tool reports.
pub fn casefold_name(name: &str) -> String {
    name.to_lowercase()
}

/// Collapses case, punctuation and a leading article so that spelling variants share one key.
///
/// The name is lower-cased, every run of non-alphanumeric characters becomes one space, and a
/// leading `the` is dropped when other words remain. `"The Beta-Group"` and `"beta group"` both
/// become `"beta group"`; `"CBSSports.com"` becomes `"cbssports com"`.
pub fn normalize_name(name: &str) -> String {
    let lowered = name.to_lowercase();
    let mut words: Vec<&str> = lowered
        .split(|c: char| !c.is_alphanumeric())
        .filter(|word| !word.is_empty())
        .collect();
    if words.len() > 1 && words[0] == "the" {
        words.remove(0);
    }
    words.join(" ")
}

impl GraphIndex {
    /// Builds the index from already-read rows.
    ///
    /// `edges` holds `(source_node_id, target_node_id)` pairs for every row of `entity_edges`.
    /// An edge endpoint that has no `entities` row still gets a degree, so degree stays a pure
    /// function of the edge list.
    pub fn from_parts(entities: Vec<EntityRecord>, edges: &[(String, String)]) -> Self {
        let mut index = Self {
            name_casefold: HashMap::with_capacity(entities.len()),
            name_normalized: HashMap::with_capacity(entities.len()),
            degree: HashMap::with_capacity(entities.len()),
            entity_chunks: HashMap::with_capacity(entities.len()),
            entity_names: HashMap::with_capacity(entities.len()),
        };
        for entity in entities {
            index.degree.entry(entity.entity_id.clone()).or_insert(0);
            index
                .name_casefold
                .entry(casefold_name(&entity.name))
                .or_default()
                .push(entity.entity_id.clone());
            let normalized = normalize_name(&entity.name);
            if !normalized.is_empty() {
                index
                    .name_normalized
                    .entry(normalized)
                    .or_default()
                    .push(entity.entity_id.clone());
            }
            index
                .entity_chunks
                .insert(entity.entity_id.clone(), entity.source_chunk_ids);
            index.entity_names.insert(entity.entity_id, entity.name);
        }
        for (source, target) in edges {
            *index.degree.entry(source.clone()).or_insert(0) += 1;
            *index.degree.entry(target.clone()).or_insert(0) += 1;
        }
        for ids in index
            .name_casefold
            .values_mut()
            .chain(index.name_normalized.values_mut())
        {
            ids.sort_unstable();
            ids.dedup();
        }
        index
    }

    /// Reads `entities` and `entity_edges` once each and builds the index.
    ///
    /// The caller must have validated the store first (`DatabaseManager::open_and_validate`):
    /// the table accessors create an empty table when one is missing, and an empty graph is not
    /// something to build an index from silently.
    ///
    /// # Errors
    /// Returns the underlying LanceDB or Arrow error text when a scan fails or a column has an
    /// unexpected type.
    pub async fn build(db: &DatabaseManager) -> Result<Self, String> {
        let entities_table = db.entities_table().await?;
        let entity_batches: Vec<RecordBatch> = entities_table
            .query()
            .select(Select::columns(&["entity_id", "name", "source_chunk_ids"]))
            .execute()
            .await
            .map_err(|error| format!("failed to scan entities: {error}"))?
            .try_collect()
            .await
            .map_err(|error| format!("failed to collect entities: {error}"))?;

        let mut records = Vec::new();
        for batch in &entity_batches {
            let ids = string_column(batch, "entity_id")?;
            let names = string_column(batch, "name")?;
            let chunk_lists = batch
                .column_by_name("source_chunk_ids")
                .and_then(|column| column.as_any().downcast_ref::<ListArray>())
                .ok_or_else(|| "entities.source_chunk_ids is missing or not a list".to_string())?;
            for row in 0..batch.num_rows() {
                let mut chunks = Vec::new();
                if !chunk_lists.is_null(row) {
                    let values = chunk_lists.value(row);
                    let values =
                        values
                            .as_any()
                            .downcast_ref::<StringArray>()
                            .ok_or_else(|| {
                                "entities.source_chunk_ids items are not strings".to_string()
                            })?;
                    for item in 0..values.len() {
                        if !values.is_null(item) {
                            chunks.push(values.value(item).to_string());
                        }
                    }
                }
                records.push(EntityRecord {
                    entity_id: ids.value(row).to_string(),
                    name: names.value(row).to_string(),
                    source_chunk_ids: chunks,
                });
            }
            tokio::task::yield_now().await;
        }

        let edges_table = db.entity_edges_table().await?;
        let edge_batches: Vec<RecordBatch> = edges_table
            .query()
            .select(Select::columns(&["source_node_id", "target_node_id"]))
            .execute()
            .await
            .map_err(|error| format!("failed to scan entity_edges: {error}"))?
            .try_collect()
            .await
            .map_err(|error| format!("failed to collect entity_edges: {error}"))?;

        let mut pairs = Vec::new();
        for batch in &edge_batches {
            let sources = string_column(batch, "source_node_id")?;
            let targets = string_column(batch, "target_node_id")?;
            for row in 0..batch.num_rows() {
                pairs.push((
                    sources.value(row).to_string(),
                    targets.value(row).to_string(),
                ));
            }
            tokio::task::yield_now().await;
        }

        Ok(Self::from_parts(records, &pairs))
    }

    /// Number of entities in the index.
    pub fn entity_count(&self) -> usize {
        self.entity_names.len()
    }

    /// Whether `entity_id` is an entity of this index generation.
    pub fn contains(&self, entity_id: &str) -> bool {
        self.entity_names.contains_key(entity_id)
    }

    /// Entity IDs whose case-folded name equals the case-folded `mention`, sorted.
    pub fn exact_matches(&self, mention: &str) -> &[String] {
        self.name_casefold
            .get(&casefold_name(mention))
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    /// Entity IDs whose normalised name equals the normalised `mention`, sorted.
    pub fn normalized_matches(&self, mention: &str) -> &[String] {
        let key = normalize_name(mention);
        if key.is_empty() {
            return &[];
        }
        self.name_normalized
            .get(&key)
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    /// The entity's degree, or `0` for an entity with no edges or an unknown ID.
    pub fn degree(&self, entity_id: &str) -> u32 {
        self.degree.get(entity_id).copied().unwrap_or(0)
    }

    /// The entity's display name.
    pub fn entity_name(&self, entity_id: &str) -> Option<&str> {
        self.entity_names.get(entity_id).map(String::as_str)
    }

    /// The chunk IDs the entity was extracted from, in stored order.
    pub fn source_chunk_ids(&self, entity_id: &str) -> &[String] {
        self.entity_chunks
            .get(entity_id)
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    /// Document IDs of the entity's source chunks, sorted and de-duplicated.
    ///
    /// A chunk ID is `{document_id}:{chunk_index}`; a document ID is a UUID and never contains a
    /// colon, so the document is everything before the last colon.
    pub fn seed_document_ids(&self, entity_id: &str) -> Vec<String> {
        let mut documents: Vec<String> = self
            .source_chunk_ids(entity_id)
            .iter()
            .filter_map(|chunk_id| {
                chunk_id
                    .rsplit_once(':')
                    .map(|(document, _)| document.to_string())
            })
            .collect();
        documents.sort_unstable();
        documents.dedup();
        documents
    }

    /// Linear-interpolated percentile of the degree of every entity, `q` in `[0.0, 1.0]`.
    ///
    /// Uses the `(n - 1) * q` rule that `inspect_lancedb --graph-population` uses for its `p95`
    /// and `p99`, over the same population (every entity, isolated ones included), so the value
    /// can be compared with `reconcile/graph_population_post.json`. Returns `0.0` for an empty
    /// index.
    pub fn degree_percentile(&self, q: f64) -> f64 {
        let mut degrees: Vec<u32> = self.entity_names.keys().map(|id| self.degree(id)).collect();
        if degrees.is_empty() {
            return 0.0;
        }
        degrees.sort_unstable();
        if degrees.len() == 1 {
            return f64::from(degrees[0]);
        }
        let position = (degrees.len() - 1) as f64 * q.clamp(0.0, 1.0);
        let lower = position.floor() as usize;
        let upper = position.ceil() as usize;
        let fraction = position - lower as f64;
        f64::from(degrees[lower]) * (1.0 - fraction) + f64::from(degrees[upper]) * fraction
    }
}

fn string_column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a StringArray, String> {
    batch
        .column_by_name(name)
        .ok_or_else(|| format!("LanceDB query did not return {name}"))?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| format!("LanceDB column {name} has an unexpected type"))
}
