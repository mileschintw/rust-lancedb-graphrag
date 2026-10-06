//! Seed-to-seed path search (stub, replaced in the GREEN commit).

use crate::db::DatabaseManager;
use crate::graph::context_strategy::GraphFact;
use crate::graph::index::GraphIndex;
use crate::graph::seeding::Seed;

/// One `entity_edges` row as the path search consumes it.
#[derive(Debug, Clone, PartialEq)]
pub struct EdgeRow {
    pub edge_id: String,
    pub source: String,
    pub target: String,
    pub relation: String,
    pub weight: f64,
}

/// Path-search knobs.
#[derive(Debug, Clone, PartialEq)]
pub struct PathSettings {
    pub degree_cap: u32,
    pub max_path_facts: usize,
    pub max_graph_chunk_candidates: usize,
}

/// One seed-to-seed path.
#[derive(Debug, Clone, PartialEq)]
pub struct PathFact {
    pub entities: Vec<String>,
    pub relations: Vec<String>,
    pub score: f64,
    pub rendered: String,
}

/// Result of a seed-to-seed path search.
#[derive(Debug, Clone, PartialEq)]
pub struct SeedPathResult {
    pub facts: Vec<GraphFact>,
    pub paths: Vec<PathFact>,
    pub path_found: bool,
    pub candidate_chunk_ids: Vec<String>,
    pub degree_capped_count: u32,
}

/// Derives the path-fact cap from the prompt budget and the measured fact size.
pub fn derive_max_path_facts(
    _evidence_token_budget: u32,
    _answer_token_budget: u32,
    _p95_fact_tokens: u32,
) -> Option<usize> {
    None
}

/// Pure path construction over already-scanned edges.
pub fn build_paths(
    _index: &GraphIndex,
    _seeds: &[Seed],
    _edges: &[EdgeRow],
    _settings: &PathSettings,
) -> SeedPathResult {
    SeedPathResult {
        facts: Vec::new(),
        paths: Vec::new(),
        path_found: false,
        candidate_chunk_ids: Vec::new(),
        degree_capped_count: 0,
    }
}

/// Chunks of the seeds themselves, as length-0 paths.
pub fn seed_chunk_candidates(_index: &GraphIndex, _seeds: &[Seed], _cap: usize) -> Vec<String> {
    Vec::new()
}

/// Scans the seeds' edges once and builds the paths.
pub async fn find_seed_paths(
    _db: &DatabaseManager,
    _index: &GraphIndex,
    _seeds: &[Seed],
    _settings: &PathSettings,
) -> Result<SeedPathResult, String> {
    Ok(SeedPathResult {
        facts: Vec::new(),
        paths: Vec::new(),
        path_found: false,
        candidate_chunk_ids: Vec::new(),
        degree_capped_count: 0,
    })
}
