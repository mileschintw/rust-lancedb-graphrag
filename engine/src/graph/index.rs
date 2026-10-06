//! Immutable per-generation graph lookup structures (stub, replaced in the GREEN commit).

use std::collections::HashMap;

use crate::db::DatabaseManager;

/// One `entities` row as the index consumes it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntityRecord {
    pub entity_id: String,
    pub name: String,
    pub source_chunk_ids: Vec<String>,
}

/// Name index, degree and provenance maps built once from one scan.
#[derive(Debug, Clone, Default)]
pub struct GraphIndex {
    degree: HashMap<String, u32>,
}

/// Lower-cases a name for exact matching.
pub fn casefold_name(name: &str) -> String {
    name.to_string()
}

/// Collapses case, punctuation and a leading article.
pub fn normalize_name(name: &str) -> String {
    name.to_string()
}

impl GraphIndex {
    /// Builds the index from already-read rows.
    pub fn from_parts(_entities: Vec<EntityRecord>, _edges: &[(String, String)]) -> Self {
        Self::default()
    }

    /// Reads `entities` and `entity_edges` once each and builds the index.
    pub async fn build(_db: &DatabaseManager) -> Result<Self, String> {
        Ok(Self::default())
    }

    pub fn entity_count(&self) -> usize {
        0
    }

    pub fn contains(&self, _entity_id: &str) -> bool {
        false
    }

    pub fn exact_matches(&self, _mention: &str) -> &[String] {
        &[]
    }

    pub fn normalized_matches(&self, _mention: &str) -> &[String] {
        &[]
    }

    pub fn degree(&self, entity_id: &str) -> u32 {
        self.degree.get(entity_id).copied().unwrap_or(0)
    }

    pub fn entity_name(&self, _entity_id: &str) -> Option<&str> {
        None
    }

    pub fn source_chunk_ids(&self, _entity_id: &str) -> &[String] {
        &[]
    }

    pub fn seed_document_ids(&self, _entity_id: &str) -> Vec<String> {
        Vec::new()
    }

    pub fn degree_percentile(&self, _q: f64) -> f64 {
        0.0
    }
}
