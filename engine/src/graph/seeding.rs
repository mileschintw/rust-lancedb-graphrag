//! Mention extraction and seed matching (stub, replaced in the GREEN commit).

use std::sync::Arc;

use serde::Serialize;

use crate::db::DatabaseManager;
use crate::graph::index::GraphIndex;
use crate::ingest::EmbeddingProvider;

/// How a seed entity was matched to a mention.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MatchKind {
    Exact,
    Normalized,
    Vector,
}

/// One matched seed entity.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Seed {
    pub entity_id: String,
    pub name: String,
    pub match_kind: MatchKind,
    pub score: f64,
    pub degree: u32,
}

/// Seed-matching knobs.
#[derive(Debug, Clone, PartialEq)]
pub struct SeedSettings {
    pub max_seeds: usize,
    pub mention_vector_top_k: usize,
    pub seed_match_min_score: f64,
}

impl Default for SeedSettings {
    fn default() -> Self {
        Self {
            max_seeds: 6,
            mention_vector_top_k: 3,
            seed_match_min_score: 0.5,
        }
    }
}

/// Batched nearest-neighbour search over entity name vectors.
#[tonic::async_trait]
pub trait MentionVectorSearch: Send + Sync {
    async fn search(
        &self,
        mentions: &[String],
        top_k: usize,
    ) -> Result<Vec<Vec<(String, f64)>>, String>;
}

/// Production `MentionVectorSearch` over the `entities.name_vector` column.
pub struct LanceMentionVectorSearch {
    pub database: DatabaseManager,
    pub embedder: Arc<dyn EmbeddingProvider>,
}

#[tonic::async_trait]
impl MentionVectorSearch for LanceMentionVectorSearch {
    async fn search(
        &self,
        mentions: &[String],
        _top_k: usize,
    ) -> Result<Vec<Vec<(String, f64)>>, String> {
        Ok(vec![Vec::new(); mentions.len()])
    }
}

/// Extracts candidate entity mentions from question text.
pub fn extract_mentions(_question: &str) -> Vec<String> {
    Vec::new()
}

/// Matches mentions to seed entities.
pub async fn match_seeds(
    _index: &GraphIndex,
    _mentions: &[String],
    _search: &dyn MentionVectorSearch,
    _settings: &SeedSettings,
) -> Result<Vec<Seed>, String> {
    Ok(Vec::new())
}
