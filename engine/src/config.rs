//! Configuration loading, settings schema, and effective runtime parameters.
//!
//! Owns the deserialized settings tree, the effective RAG settings derived from it,
//! and the TOML-plus-environment loading contract.

use serde::Deserialize;
use std::sync::Arc;
use uuid::Uuid;

use crate::generation;
use crate::graph;
use crate::retrieval::{self, Bm25Config};

pub fn default_candidate_limit() -> usize {
    32
}
pub fn default_final_limit() -> usize {
    8
}
pub fn default_query_max_bytes() -> usize {
    8192
}
pub fn default_max_document_ids() -> usize {
    100
}
pub fn default_max_content_types() -> usize {
    16
}
pub fn default_weight() -> f64 {
    1.0
}
pub fn default_rrf_k() -> f64 {
    60.0
}
pub fn default_evidence_token_budget() -> usize {
    8192
}
pub fn default_excerpt_max_chars() -> usize {
    512
}
pub fn default_k1() -> f64 {
    1.2
}
pub fn default_b() -> f64 {
    0.75
}
pub fn default_title_boost() -> f64 {
    2.0
}
pub fn default_section_boost() -> f64 {
    1.5
}
pub fn default_embedding_endpoint() -> String {
    "https://openrouter.ai/api/v1/embeddings".into()
}
pub fn default_embedding_model() -> String {
    "voyageai/voyage-4-large".into()
}
pub fn default_generation_model() -> String {
    "openai/gpt-4o-mini".into()
}
pub fn default_chat_endpoint() -> String {
    "https://openrouter.ai/api/v1/chat/completions".into()
}
pub fn default_models_endpoint() -> String {
    "https://openrouter.ai/api/v1/models".into()
}
pub fn default_generation_timeout_secs() -> u64 {
    30
}
pub fn default_temperature() -> f64 {
    0.0
}
pub fn default_top_p() -> f64 {
    1.0
}
pub fn default_max_output_tokens() -> u32 {
    2048
}
pub fn default_embedding_concurrency() -> usize {
    12
}
pub fn default_extraction_concurrency() -> usize {
    15
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Settings {
    pub engine: EngineSettings,
    #[serde(default)]
    pub openrouter: OpenRouterSettings,
}

pub fn default_seed_match_min_score() -> f64 {
    0.5
}

pub fn default_max_hop_cap() -> u32 {
    3
}

/// Most seeds one question may use for graph path search: 6.
///
/// **Derivation.** `graph::seeding::DEFAULT_MAX_SEEDS`, from RESEARCH section F.1 (about 6) and the
/// seed-count distribution of the offline probe (`06.3.4.1-SEED-PROBE.md` section 2): over 100
/// diagnostic questions the mean is 4.54 seeds and 39 questions reached 6. The path search checks
/// every pair of seeds, so the value sets the work: 6 seeds make 15 pairs.
///
/// **Effect of changing it.** Raising it grows the pair count quadratically (7 seeds make 21
/// pairs) and admits weaker, more generic seeds; lowering it drops the lower-priority seeds
/// first (exact before normalised before vector match, then the lower degree) and so loses paths.
/// The path search itself never reads more than 8.
pub fn default_max_seeds() -> usize {
    graph::seeding::DEFAULT_MAX_SEEDS
}

/// Nearest entities fetched per mention that has no name match: 3.
///
/// **Derivation.** `graph::seeding::DEFAULT_MENTION_VECTOR_TOP_K`, RESEARCH section F.1 (k = 3). In
/// the offline probe 19.4% of seeds came from this vector fallback.
///
/// **Effect of changing it.** Raising it widens recall for a misspelt or abbreviated name and
/// admits more weak seeds; `0` turns the vector fallback off, leaving exact and normalised
/// name matching only.
pub fn default_mention_vector_top_k() -> usize {
    graph::seeding::DEFAULT_MENTION_VECTOR_TOP_K
}

/// Largest degree a two-hop path may pass through: 33.
///
/// **Derivation.** `graph::paths::DEGREE_CAP`: the 99th percentile of the entity degree of the
/// reconciled eval store, 33.0 over 27,855 entities (`06.3.4.1-STORE-BASELINE.md` section 4,
/// `reconcile/graph_population_post.json`), confirmed by the user on 2026-10-05
/// (`06.3.4.1-SEED-PROBE.md` sections 8 and 9).
///
/// **Effect of changing it.** A smaller cap, such as the p95 of 10, also excludes mid-size real
/// entities as bridges and loses paths; a larger one admits hubs, whose paths join almost any two
/// seeds and carry no information. It affects intermediates only; a hub that is a seed stays one.
pub fn default_degree_cap() -> u32 {
    graph::paths::DEGREE_CAP
}

/// Most path facts one question may put in the prompt: 8.
///
/// **Derivation.** `graph::paths::MAX_PATH_FACTS`: `min(16, floor(0.10 * (8192 - 2048) / 69))`,
/// where 8192 is the evidence token budget, 2048 the answer budget and 69 the measured p95 of
/// tokens per path fact (`06.3.4.1-SEED-PROBE.md` section 8), confirmed by the user on 2026-10-05.
///
/// **Effect of changing it.** Raising it moves prompt budget from evidence chunks to graph facts
/// (about 69 tokens per fact); lowering it drops the lower-ranked, less specific paths. The value
/// was derived from the evidence and answer budgets, so changing either budget means re-deriving it.
pub fn default_max_path_facts() -> usize {
    graph::paths::MAX_PATH_FACTS
}

/// Most chunk candidates the graph offers to retrieval fusion: 8.
///
/// **Derivation.** Equal to `default_final_limit()` (`engine.retrieval.final_limit`): retrieval
/// returns that many chunks, so a graph list longer than it only adds candidates that cannot
/// all be used. Only chunks of the entities on seed-to-seed paths are candidates, and a question
/// with no such path has none (06.3.4.1-13 decision `paths-only`).
///
/// **Effect of changing it.** Raising it lets the graph list outweigh a longer part of the fused
/// ranking; lowering it limits the graph to its best chunks.
pub fn default_max_graph_chunk_candidates() -> usize {
    default_final_limit()
}

#[derive(Debug, Clone, Deserialize)]
pub struct GraphConfigSettings {
    #[serde(default = "default_seed_match_min_score")]
    pub seed_match_min_score: f64,
    #[serde(default = "default_max_hop_cap")]
    pub max_hop_cap: u32,
    #[serde(default = "default_max_seeds")]
    pub max_seeds: usize,
    #[serde(default = "default_mention_vector_top_k")]
    pub mention_vector_top_k: usize,
    #[serde(default = "default_degree_cap")]
    pub degree_cap: u32,
    #[serde(default = "default_max_path_facts")]
    pub max_path_facts: usize,
    #[serde(default = "default_max_graph_chunk_candidates")]
    pub max_graph_chunk_candidates: usize,
}

impl Default for GraphConfigSettings {
    fn default() -> Self {
        Self {
            seed_match_min_score: default_seed_match_min_score(),
            max_hop_cap: default_max_hop_cap(),
            max_seeds: default_max_seeds(),
            mention_vector_top_k: default_mention_vector_top_k(),
            degree_cap: default_degree_cap(),
            max_path_facts: default_max_path_facts(),
            max_graph_chunk_candidates: default_max_graph_chunk_candidates(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct GraphSettings {
    pub seed_match_min_score: f64,
    pub max_hop_cap: u32,
    pub max_seeds: usize,
    pub mention_vector_top_k: usize,
    pub degree_cap: u32,
    pub max_path_facts: usize,
    pub max_graph_chunk_candidates: usize,
}

impl Default for GraphSettings {
    fn default() -> Self {
        let defaults = GraphConfigSettings::default();
        Self {
            seed_match_min_score: defaults.seed_match_min_score,
            max_hop_cap: defaults.max_hop_cap,
            max_seeds: defaults.max_seeds,
            mention_vector_top_k: defaults.mention_vector_top_k,
            degree_cap: defaults.degree_cap,
            max_path_facts: defaults.max_path_facts,
            max_graph_chunk_candidates: defaults.max_graph_chunk_candidates,
        }
    }
}

impl GraphSettings {
    /// The seed-matching settings these graph settings select (D-75, D-77).
    pub fn seed_settings(&self) -> graph::seeding::SeedSettings {
        graph::seeding::SeedSettings::default()
    }

    /// The path-search settings these graph settings select (D-76, D-77).
    pub fn path_settings(&self) -> graph::paths::PathSettings {
        graph::paths::PathSettings {
            degree_cap: graph::paths::DEGREE_CAP,
            max_path_facts: graph::paths::MAX_PATH_FACTS,
            max_graph_chunk_candidates: 8,
        }
    }
}

/// Budget for `ReformulateQuery`, in milliseconds.
///
/// Carried forward and never derived from a measurement, so it is left out of the pass-A
/// derivation. See `06.3.4.1-BUDGETS.md`.
pub fn default_reformulate_timeout_ms() -> u64 {
    5000
}
/// Budget for the query embedding call inside `ExtractGraphContext`, in milliseconds.
///
/// A user-stated value (06.3.4.1-24, "tight embedding, loose graph"): an embedding timeout
/// fails the node and cancels the query, which is cheap to retry because generation has not
/// started. Raising it loosens the bound on that failure; `graph_node_timeout_ms` and
/// `retrieve_timeout_ms` must keep 500 ms of slack over it. See `06.3.4.1-BUDGETS.md`.
pub fn default_query_embedding_timeout_ms() -> u64 {
    2000
}
/// Budget for the `RetrieveHybrid` node, in milliseconds.
///
/// The committed rule (p95 x 1.5 over pass A) writes 294 ms, which nesting lifts to
/// `query_embedding_timeout_ms` + 500. See `06.3.4.1-BUDGETS.md`.
pub fn default_retrieve_timeout_ms() -> u64 {
    2500
}
/// Budget for the graph traversal inside `ExtractGraphContext`, in milliseconds.
///
/// A user-stated value (06.3.4.1-24). A graph-operation timeout degrades silently to
/// chunk-only context and records a success, so a tight value would hide lost graph yield.
/// See `06.3.4.1-BUDGETS.md`.
pub fn default_graph_operation_timeout_ms() -> u64 {
    10000
}
/// Budget for the whole `ExtractGraphContext` node, in milliseconds.
///
/// The committed rule writes 1062 ms, which nesting lifts to `query_embedding_timeout_ms` +
/// `graph_operation_timeout_ms` + 500. Engine startup rejects a value below that sum. See
/// `06.3.4.1-BUDGETS.md`.
pub fn default_graph_node_timeout_ms() -> u64 {
    12500
}
/// Budget for the `AssemblePrompt` node, in milliseconds.
///
/// A user-decided floor (06.3.4.1-24: 1.5 x pass A's 43 ms maximum, where the committed rule
/// alone writes 11 ms, close to the Windows timer granularity of about 15.6 ms), amended to
/// 120 by D-93 (2026-09-29). A fresh engine's first `AssemblePrompt` took 78.6 ms against
/// 65 ms, and 120 keeps headroom over that even if the startup tokenizer warm-up does not
/// remove all of it. See `06.3.4.1-BUDGETS.md`.
pub fn default_prompt_timeout_ms() -> u64 {
    120
}
/// Budget for the `GenerateAnswer` node, in milliseconds.
///
/// The provider contract: two attempts at the 30 s provider timeout plus 5 s of slack. Engine
/// startup rejects a value below the two attempts. See `06.3.4.1-BUDGETS.md`.
pub fn default_generation_node_timeout_ms() -> u64 {
    65000
}
pub fn default_allow_model_only_answers() -> bool {
    false
}
pub fn default_citation_repair_enabled() -> bool {
    true
}
pub fn default_rebuild_debounce_ms() -> u64 {
    2000
}
pub fn default_otlp_endpoint() -> String {
    "http://127.0.0.1:4317".to_string()
}
pub fn default_sampler_ratio() -> f64 {
    1.0
}
pub fn default_service_name() -> String {
    "lancet-engine".to_string()
}
pub fn default_deployment_environment() -> String {
    "dev".to_string()
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TelemetryConfigSettings {
    /// OTLP gRPC endpoint URL (e.g. `http://127.0.0.1:4317`).
    #[serde(default = "default_otlp_endpoint")]
    pub otlp_endpoint: String,
    /// Sampling ratio in range 0.0..=1.0. Defaults to 1.0 (always on, D-32).
    #[serde(default = "default_sampler_ratio")]
    pub sampler_ratio: f64,
    /// Service name for OTel resource attribution (D-43).
    #[serde(default = "default_service_name")]
    pub service_name: String,
    /// Deployment environment name (D-43).
    #[serde(default = "default_deployment_environment")]
    pub deployment_environment: String,
}

impl Default for TelemetryConfigSettings {
    fn default() -> Self {
        Self {
            otlp_endpoint: default_otlp_endpoint(),
            sampler_ratio: default_sampler_ratio(),
            service_name: default_service_name(),
            deployment_environment: default_deployment_environment(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowConfigSettings {
    #[serde(default = "default_reformulate_timeout_ms")]
    pub reformulate_timeout_ms: u64,
    #[serde(default = "default_query_embedding_timeout_ms")]
    pub query_embedding_timeout_ms: u64,
    #[serde(default = "default_retrieve_timeout_ms")]
    pub retrieve_timeout_ms: u64,
    #[serde(default = "default_graph_operation_timeout_ms")]
    pub graph_operation_timeout_ms: u64,
    #[serde(default = "default_graph_node_timeout_ms")]
    pub graph_node_timeout_ms: u64,
    #[serde(default = "default_prompt_timeout_ms")]
    pub prompt_timeout_ms: u64,
    #[serde(default = "default_generation_node_timeout_ms")]
    pub generation_node_timeout_ms: u64,
    /// Whether model-only answers are allowed when no evidence survives retrieval.
    ///
    /// Defaults to false. A request's `allow_model_only` field overrides this default when present;
    /// the resolution order is request, then configuration, then false (D-10/D-12).
    #[serde(default = "default_allow_model_only_answers")]
    pub allow_model_only_answers: bool,
    /// Whether the local citation-repair pass (D-14) runs on unresolved citation markers.
    ///
    /// Defaults to true. When true, a near-miss marker is normalized and retained and an
    /// unresolvable one is stripped from the answer and both citation lists; when false,
    /// an unresolvable marker fails the run exactly as it did before D-14 (DEBT-RAG-03).
    #[serde(default = "default_citation_repair_enabled")]
    pub citation_repair_enabled: bool,
    /// Ingestion index rebuild debounce interval in milliseconds (D-23, D-84).
    #[serde(default = "default_rebuild_debounce_ms")]
    pub rebuild_debounce_ms: u64,
}

impl Default for WorkflowConfigSettings {
    fn default() -> Self {
        Self {
            reformulate_timeout_ms: default_reformulate_timeout_ms(),
            query_embedding_timeout_ms: default_query_embedding_timeout_ms(),
            retrieve_timeout_ms: default_retrieve_timeout_ms(),
            graph_operation_timeout_ms: default_graph_operation_timeout_ms(),
            graph_node_timeout_ms: default_graph_node_timeout_ms(),
            prompt_timeout_ms: default_prompt_timeout_ms(),
            generation_node_timeout_ms: default_generation_node_timeout_ms(),
            allow_model_only_answers: default_allow_model_only_answers(),
            citation_repair_enabled: default_citation_repair_enabled(),
            rebuild_debounce_ms: default_rebuild_debounce_ms(),
        }
    }
}

impl WorkflowConfigSettings {
    pub fn to_workflow_settings(&self) -> WorkflowSettings {
        WorkflowSettings {
            reformulate_timeout_ms: self.reformulate_timeout_ms,
            query_embedding_timeout_ms: self.query_embedding_timeout_ms,
            retrieve_timeout_ms: self.retrieve_timeout_ms,
            graph_operation_timeout_ms: self.graph_operation_timeout_ms,
            graph_node_timeout_ms: self.graph_node_timeout_ms,
            prompt_timeout_ms: self.prompt_timeout_ms,
            generation_node_timeout_ms: self.generation_node_timeout_ms,
            allow_model_only_answers: self.allow_model_only_answers,
            citation_repair_enabled: self.citation_repair_enabled,
            rebuild_debounce_ms: self.rebuild_debounce_ms,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkflowSettings {
    pub reformulate_timeout_ms: u64,
    pub query_embedding_timeout_ms: u64,
    pub retrieve_timeout_ms: u64,
    pub graph_operation_timeout_ms: u64,
    pub graph_node_timeout_ms: u64,
    pub prompt_timeout_ms: u64,
    pub generation_node_timeout_ms: u64,
    /// Whether model-only answers are allowed when no evidence survives retrieval.
    ///
    /// Defaults to false. A request's `allow_model_only` field overrides this default when present;
    /// the resolution order is request, then configuration, then false (D-10/D-12).
    pub allow_model_only_answers: bool,
    /// Whether the local citation-repair pass (D-14) runs on unresolved citation markers.
    ///
    /// Defaults to true. When true, a near-miss marker is normalized and retained and an
    /// unresolvable one is stripped from the answer and both citation lists; when false,
    /// an unresolvable marker fails the run exactly as it did before D-14 (DEBT-RAG-03).
    pub citation_repair_enabled: bool,
    /// Ingestion index rebuild debounce interval in milliseconds (D-23, D-84).
    pub rebuild_debounce_ms: u64,
}

impl Default for WorkflowSettings {
    fn default() -> Self {
        WorkflowConfigSettings::default().to_workflow_settings()
    }
}

impl WorkflowSettings {
    pub fn validate(&self) -> Result<(), String> {
        if self.rebuild_debounce_ms == 0 {
            return Err("invalid rebuild_debounce_ms: must be greater than 0".into());
        }
        if self.reformulate_timeout_ms == 0 {
            return Err("invalid reformulate_timeout_ms: must be greater than 0".into());
        }
        if self.query_embedding_timeout_ms == 0 {
            return Err("invalid query_embedding_timeout_ms: must be greater than 0".into());
        }
        if self.retrieve_timeout_ms == 0 {
            return Err("invalid retrieve_timeout_ms: must be greater than 0".into());
        }
        if self.graph_operation_timeout_ms == 0 {
            return Err("invalid graph_operation_timeout_ms: must be greater than 0".into());
        }
        if self.graph_node_timeout_ms == 0 {
            return Err("invalid graph_node_timeout_ms: must be greater than 0".into());
        }
        if self.prompt_timeout_ms == 0 {
            return Err("invalid prompt_timeout_ms: must be greater than 0".into());
        }
        if self.generation_node_timeout_ms == 0 {
            return Err("invalid generation_node_timeout_ms: must be greater than 0".into());
        }
        let graph_required = self
            .query_embedding_timeout_ms
            .saturating_add(self.graph_operation_timeout_ms);
        if self.graph_node_timeout_ms < graph_required {
            return Err(format!(
                "invalid graph_node_timeout_ms ({}): must be >= query_embedding_timeout_ms + graph_operation_timeout_ms ({})",
                self.graph_node_timeout_ms, graph_required
            ));
        }
        Ok(())
    }

    pub fn validate_against_provider(&self, generation_timeout_secs: u64) -> Result<(), String> {
        const GENERATION_ATTEMPTS: u64 = 2; // GenerateAnswerNode performs up to 2 attempts
        let required =
            GENERATION_ATTEMPTS.saturating_mul(generation_timeout_secs.saturating_mul(1000));
        if self.generation_node_timeout_ms < required {
            return Err(format!(
                "invalid generation_node_timeout_ms ({}): must be >= {} ({} attempts x {}s provider timeout)",
                self.generation_node_timeout_ms, required, GENERATION_ATTEMPTS, generation_timeout_secs
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct EngineSettings {
    pub grpc_addr: String,
    pub lancedb_path: String,
    #[serde(default)]
    pub workflow: WorkflowConfigSettings,
    #[serde(default)]
    pub retrieval: RetrievalConfigSettings,
    #[serde(default)]
    pub graph: GraphConfigSettings,
    #[serde(default)]
    pub telemetry: TelemetryConfigSettings,
}

impl Default for EngineSettings {
    fn default() -> Self {
        Self {
            grpc_addr: "[::1]:50051".into(),
            lancedb_path: "./data/lancedb".into(),
            workflow: WorkflowConfigSettings::default(),
            retrieval: RetrievalConfigSettings::default(),
            graph: GraphConfigSettings::default(),
            telemetry: TelemetryConfigSettings::default(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct Bm25ConfigSettings {
    #[serde(default = "default_k1")]
    pub k1: f64,
    #[serde(default = "default_b")]
    pub b: f64,
    #[serde(default = "default_weight")]
    pub content_boost: f64,
    #[serde(default = "default_title_boost")]
    pub title_boost: f64,
    #[serde(default = "default_section_boost")]
    pub section_boost: f64,
}

impl Default for Bm25ConfigSettings {
    fn default() -> Self {
        Self {
            k1: 1.2,
            b: 0.75,
            content_boost: 1.0,
            title_boost: 2.0,
            section_boost: 1.5,
        }
    }
}

impl Bm25ConfigSettings {
    pub fn to_bm25_config(&self) -> Bm25Config {
        Bm25Config {
            k1: self.k1,
            b: self.b,
            content_boost: self.content_boost,
            title_boost: self.title_boost,
            section_path_boost: self.section_boost,
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct RetrievalConfigSettings {
    #[serde(default = "default_candidate_limit")]
    pub candidate_limit: usize,
    #[serde(default = "default_final_limit")]
    pub final_limit: usize,
    #[serde(default = "default_query_max_bytes")]
    pub query_max_bytes: usize,
    #[serde(default = "default_max_document_ids")]
    pub max_document_ids: usize,
    #[serde(default = "default_max_content_types")]
    pub max_content_types: usize,
    #[serde(default = "default_weight")]
    pub vector_weight: f64,
    #[serde(default = "default_weight")]
    pub bm25_weight: f64,
    #[serde(default = "default_weight")]
    pub graph_weight: f64,
    #[serde(default = "default_rrf_k")]
    pub rrf_k: f64,
    #[serde(default = "default_evidence_token_budget")]
    pub evidence_token_budget: usize,
    #[serde(default = "default_excerpt_max_chars")]
    pub excerpt_max_chars: usize,
    #[serde(default)]
    pub bm25: Bm25ConfigSettings,
}

impl Default for RetrievalConfigSettings {
    fn default() -> Self {
        Self {
            candidate_limit: 32,
            final_limit: 8,
            query_max_bytes: 8192,
            max_document_ids: 100,
            max_content_types: 16,
            vector_weight: 1.0,
            bm25_weight: 1.0,
            graph_weight: 1.0,
            rrf_k: 60.0,
            evidence_token_budget: 8192,
            excerpt_max_chars: 512,
            bm25: Bm25ConfigSettings::default(),
        }
    }
}

impl RetrievalConfigSettings {
    pub fn to_retrieval_settings(&self) -> retrieval::RetrievalSettings {
        retrieval::RetrievalSettings {
            candidate_limit: self.candidate_limit,
            final_limit: self.final_limit,
            query_max_bytes: self.query_max_bytes,
            max_document_ids: self.max_document_ids,
            max_content_types: self.max_content_types,
            vector_weight: self.vector_weight,
            bm25_weight: self.bm25_weight,
            graph_weight: self.graph_weight,
            rrf_k: self.rrf_k,
            bm25: self.bm25.to_bm25_config(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct OpenRouterSettings {
    #[serde(default = "default_embedding_endpoint")]
    pub embedding_endpoint: String,
    #[serde(default = "default_embedding_model")]
    pub embedding_model: String,
    #[serde(default = "default_generation_model")]
    pub generation_model: String,
    #[serde(default = "default_embedding_concurrency")]
    pub embedding_concurrency: usize,
    #[serde(default = "default_extraction_concurrency")]
    pub extraction_concurrency: usize,
    #[serde(default = "default_chat_endpoint")]
    pub chat_endpoint: String,
    #[serde(default = "default_models_endpoint", alias = "models_endpoint")]
    pub model_metadata_endpoint: String,
    #[serde(default = "default_generation_timeout_secs")]
    pub generation_timeout_secs: u64,
    #[serde(default = "default_temperature")]
    pub temperature: f64,
    #[serde(default = "default_top_p")]
    pub top_p: f64,
    #[serde(default = "default_max_output_tokens")]
    pub max_output_tokens: u32,
}

impl Default for OpenRouterSettings {
    fn default() -> Self {
        Self {
            embedding_endpoint: "https://openrouter.ai/api/v1/embeddings".into(),
            embedding_model: "voyageai/voyage-4-large".into(),
            generation_model: "openai/gpt-4o-mini".into(),
            embedding_concurrency: default_embedding_concurrency(),
            extraction_concurrency: default_extraction_concurrency(),
            chat_endpoint: "https://openrouter.ai/api/v1/chat/completions".into(),
            model_metadata_endpoint: "https://openrouter.ai/api/v1/models".into(),
            generation_timeout_secs: 30,
            temperature: 0.0,
            top_p: 1.0,
            max_output_tokens: 2048,
        }
    }
}

pub fn new_index_generation() -> String {
    format!("gen-{}", Uuid::new_v4())
}

#[derive(Debug, Clone, PartialEq)]
pub struct EffectiveRagSettings {
    pub workflow: WorkflowSettings,
    pub retrieval: retrieval::RetrievalSettings,
    pub graph: GraphSettings,
    pub evidence_token_budget: usize,
    pub citation_excerpt_max_chars: usize,
    pub embedding_endpoint: String,
    pub embedding_model: String,
    pub generation_model: String,
    pub embedding_concurrency: usize,
    pub extraction_concurrency: usize,
    pub chat_endpoint: String,
    pub model_metadata_endpoint: String,
    pub generation_timeout_secs: u64,
    pub temperature: f64,
    pub top_p: f64,
    pub max_output_tokens: u32,
    pub index_generation: String,
    grounding_limits: Arc<generation::GroundingLimits>,
}

impl EffectiveRagSettings {
    pub fn grounding_limits(&self) -> &generation::GroundingLimits {
        &self.grounding_limits
    }

    pub fn grounding_limits_arc(&self) -> Arc<generation::GroundingLimits> {
        Arc::clone(&self.grounding_limits)
    }

    pub fn try_from_settings(settings: &Settings) -> Result<Self, String> {
        let workflow = settings.engine.workflow.to_workflow_settings();
        let retrieval = settings.engine.retrieval.to_retrieval_settings();
        let graph = GraphSettings {
            seed_match_min_score: settings.engine.graph.seed_match_min_score,
            max_hop_cap: settings.engine.graph.max_hop_cap,
            max_seeds: settings.engine.graph.max_seeds,
            mention_vector_top_k: settings.engine.graph.mention_vector_top_k,
            degree_cap: settings.engine.graph.degree_cap,
            max_path_facts: settings.engine.graph.max_path_facts,
            max_graph_chunk_candidates: settings.engine.graph.max_graph_chunk_candidates,
        };
        let ev = u32::try_from(settings.engine.retrieval.evidence_token_budget)
            .map_err(|_| "evidence_token_budget exceeds u32::MAX".to_string())?;
        let limits = generation::GroundingLimits::new(ev, settings.openrouter.max_output_tokens)
            .map_err(|err| err.message().to_string())?;
        let effective = Self {
            workflow,
            retrieval,
            graph,
            evidence_token_budget: settings.engine.retrieval.evidence_token_budget,
            citation_excerpt_max_chars: settings.engine.retrieval.excerpt_max_chars,
            embedding_endpoint: settings.openrouter.embedding_endpoint.clone(),
            embedding_model: settings.openrouter.embedding_model.clone(),
            generation_model: settings.openrouter.generation_model.clone(),
            embedding_concurrency: settings.openrouter.embedding_concurrency,
            extraction_concurrency: settings.openrouter.extraction_concurrency,
            chat_endpoint: settings.openrouter.chat_endpoint.clone(),
            model_metadata_endpoint: settings.openrouter.model_metadata_endpoint.clone(),
            generation_timeout_secs: settings.openrouter.generation_timeout_secs,
            temperature: settings.openrouter.temperature,
            top_p: settings.openrouter.top_p,
            max_output_tokens: settings.openrouter.max_output_tokens,
            index_generation: new_index_generation(),
            grounding_limits: Arc::new(limits),
        };
        effective.validate()?;
        Ok(effective)
    }

    pub fn validate(&self) -> Result<(), String> {
        self.workflow.validate()?;
        self.workflow.validate_against_provider(self.generation_timeout_secs)?;
        self.retrieval
            .validate()
            .map_err(|err| format!("invalid retrieval settings: {}", err.message()))?;
        if !self.graph.seed_match_min_score.is_finite()
            || self.graph.seed_match_min_score < 0.0
            || self.graph.seed_match_min_score > 1.0
        {
            return Err(
                "invalid graph.seed_match_min_score: must be finite and between 0.0 and 1.0".into(),
            );
        }
        if self.graph.max_hop_cap == 0 || self.graph.max_hop_cap > graph::MAX_HOP_CAP {
            return Err(format!(
                "invalid graph.max_hop_cap: must be between 1 and {}",
                graph::MAX_HOP_CAP
            ));
        }
        if self.graph.max_seeds == 0 {
            return Err("invalid graph.max_seeds: must be greater than 0".into());
        }
        if self.graph.degree_cap == 0 {
            return Err("invalid graph.degree_cap: must be greater than 0".into());
        }
        if self.graph.max_path_facts == 0 {
            return Err("invalid graph.max_path_facts: must be greater than 0".into());
        }
        if self.evidence_token_budget == 0 {
            return Err("invalid evidence_token_budget: must be greater than 0".into());
        }
        if self.citation_excerpt_max_chars == 0 {
            return Err("invalid excerpt_max_chars: must be greater than 0".into());
        }
        if self.embedding_endpoint.trim().is_empty() {
            return Err("invalid embedding_endpoint: must not be empty".into());
        }
        if self.embedding_model.trim().is_empty() {
            return Err("invalid embedding_model: must not be empty".into());
        }
        if self.generation_model.trim().is_empty() {
            return Err("invalid generation_model: must not be empty".into());
        }
        if self.embedding_concurrency == 0 {
            return Err("invalid embedding_concurrency: must be greater than 0".into());
        }
        if self.extraction_concurrency == 0 {
            return Err("invalid extraction_concurrency: must be greater than 0".into());
        }
        if self.chat_endpoint.trim().is_empty() {
            return Err("invalid chat_endpoint: must not be empty".into());
        }
        if self.model_metadata_endpoint.trim().is_empty() {
            return Err("invalid model_metadata_endpoint: must not be empty".into());
        }
        if self.generation_timeout_secs == 0 {
            return Err("invalid generation_timeout_secs: must be greater than 0".into());
        }
        if !self.temperature.is_finite() || self.temperature < 0.0 || self.temperature > 2.0 {
            return Err("invalid temperature: must be finite and between 0.0 and 2.0".into());
        }
        if !self.top_p.is_finite() || self.top_p <= 0.0 || self.top_p > 1.0 {
            return Err("invalid top_p: must be finite and between 0.0 and 1.0".into());
        }
        if self.index_generation.trim().is_empty() {
            return Err("invalid index_generation: must not be empty".into());
        }
        Ok(())
    }
}

impl Default for EffectiveRagSettings {
    fn default() -> Self {
        Self::try_from_settings(&Settings::default()).expect("default settings must be valid")
    }
}

pub fn load_settings() -> Result<Settings, ::config::ConfigError> {
    let base_path = if let Ok(dir) = std::env::var("LANCET_CONFIG_DIR") {
        if !dir.trim().is_empty() {
            let trimmed = dir.trim().trim_end_matches(['/', '\\']);
            format!("{trimmed}/config")
        } else if std::path::Path::new("../config/config.toml").exists() {
            "../config/config".to_string()
        } else {
            "config/config".to_string()
        }
    } else if std::path::Path::new("../config/config.toml").exists() {
        "../config/config".to_string()
    } else {
        "config/config".to_string()
    };
    let mut builder = ::config::Config::builder().add_source(::config::File::with_name(&base_path));
    if let Ok(environment) = std::env::var("LANCET_ENV") {
        if !environment.trim().is_empty() {
            let env_path = format!("{base_path}.{}", environment.trim());
            builder = builder.add_source(::config::File::with_name(&env_path).required(false));
        }
    }
    let mut settings: Settings = builder
        .add_source(::config::Environment::with_prefix("LANCET").separator("__"))
        .build()?
        .try_deserialize()?;

    // Keep the process-test and deployment override names explicit at the
    // boundary. This also makes the double-underscore contract independent of
    // config crate version-specific environment parsing details.
    if let Ok(value) = std::env::var("LANCET_ENGINE__GRPC_ADDR") {
        if !value.trim().is_empty() {
            settings.engine.grpc_addr = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__LANCEDB_PATH") {
        if !value.trim().is_empty() {
            settings.engine.lancedb_path = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__WORKFLOW__REFORMULATE_TIMEOUT_MS") {
        if let Ok(val) = value.trim().parse::<u64>() {
            settings.engine.workflow.reformulate_timeout_ms = val;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__WORKFLOW__QUERY_EMBEDDING_TIMEOUT_MS") {
        if let Ok(val) = value.trim().parse::<u64>() {
            settings.engine.workflow.query_embedding_timeout_ms = val;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__WORKFLOW__RETRIEVE_TIMEOUT_MS") {
        if let Ok(val) = value.trim().parse::<u64>() {
            settings.engine.workflow.retrieve_timeout_ms = val;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__WORKFLOW__GRAPH_OPERATION_TIMEOUT_MS") {
        if let Ok(val) = value.trim().parse::<u64>() {
            settings.engine.workflow.graph_operation_timeout_ms = val;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__WORKFLOW__GRAPH_NODE_TIMEOUT_MS") {
        if let Ok(val) = value.trim().parse::<u64>() {
            settings.engine.workflow.graph_node_timeout_ms = val;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__WORKFLOW__PROMPT_TIMEOUT_MS") {
        if let Ok(val) = value.trim().parse::<u64>() {
            settings.engine.workflow.prompt_timeout_ms = val;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__WORKFLOW__GENERATION_NODE_TIMEOUT_MS") {
        if let Ok(val) = value.trim().parse::<u64>() {
            settings.engine.workflow.generation_node_timeout_ms = val;
        }
    }
    if let Ok(raw) = std::env::var("LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            settings.engine.workflow.allow_model_only_answers = match trimmed {
                "true" | "1" => true,
                "false" | "0" => false,
                other => {
                    return Err(::config::ConfigError::Message(format!(
                        "LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS must be true/false, got {other:?}"
                    )))
                }
            };
        }
    }
    if let Ok(raw) = std::env::var("LANCET_ENGINE__WORKFLOW__CITATION_REPAIR_ENABLED") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            settings.engine.workflow.citation_repair_enabled = match trimmed {
                "true" | "1" => true,
                "false" | "0" => false,
                other => {
                    return Err(::config::ConfigError::Message(format!(
                        "LANCET_ENGINE__WORKFLOW__CITATION_REPAIR_ENABLED must be true/false, got {other:?}"
                    )))
                }
            };
        }
    }
    if let Ok(raw) = std::env::var("LANCET_ENGINE__WORKFLOW__REBUILD_DEBOUNCE_MS") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            match trimmed.parse::<u64>() {
                Ok(val) if val > 0 => {
                    settings.engine.workflow.rebuild_debounce_ms = val;
                }
                _ => {
                    return Err(::config::ConfigError::Message(format!(
                        "LANCET_ENGINE__WORKFLOW__REBUILD_DEBOUNCE_MS must be a positive integer > 0, got {trimmed:?}"
                    )));
                }
            }
        }
    }
    if let Ok(raw) = std::env::var("LANCET_ENGINE__TELEMETRY__OTLP_ENDPOINT") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            match reqwest::Url::parse(trimmed) {
                Ok(url) if (url.scheme() == "http" || url.scheme() == "https") && url.has_host() => {
                    settings.engine.telemetry.otlp_endpoint = trimmed.to_string();
                }
                _ => {
                    return Err(::config::ConfigError::Message(format!(
                        "LANCET_ENGINE__TELEMETRY__OTLP_ENDPOINT must be an absolute http or https URL, got {trimmed:?}"
                    )));
                }
            }
        }
    }
    if let Ok(raw) = std::env::var("LANCET_ENGINE__TELEMETRY__SAMPLER_RATIO") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            match trimmed.parse::<f64>() {
                Ok(val) if (0.0..=1.0).contains(&val) && !val.is_nan() => {
                    settings.engine.telemetry.sampler_ratio = val;
                }
                _ => {
                    return Err(::config::ConfigError::Message(format!(
                        "LANCET_ENGINE__TELEMETRY__SAMPLER_RATIO must be a float in range 0.0..=1.0, got {trimmed:?}"
                    )));
                }
            }
        }
    }
    if let Ok(raw) = std::env::var("LANCET_ENGINE__TELEMETRY__SERVICE_NAME") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            settings.engine.telemetry.service_name = trimmed.to_string();
        } else if !raw.is_empty() {
            return Err(::config::ConfigError::Message(
                "LANCET_ENGINE__TELEMETRY__SERVICE_NAME must not be empty when set".to_string(),
            ));
        }
    }
    if let Ok(raw) = std::env::var("LANCET_ENGINE__TELEMETRY__DEPLOYMENT_ENVIRONMENT") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            settings.engine.telemetry.deployment_environment = trimmed.to_string();
        } else if !raw.is_empty() {
            return Err(::config::ConfigError::Message(
                "LANCET_ENGINE__TELEMETRY__DEPLOYMENT_ENVIRONMENT must not be empty when set".to_string(),
            ));
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__EMBEDDING_ENDPOINT") {
        if !value.trim().is_empty() {
            settings.openrouter.embedding_endpoint = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__MODEL_METADATA_ENDPOINT") {
        if !value.trim().is_empty() {
            settings.openrouter.model_metadata_endpoint = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__CHAT_ENDPOINT") {
        if !value.trim().is_empty() {
            settings.openrouter.chat_endpoint = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__GENERATION_MODEL") {
        if !value.trim().is_empty() {
            settings.openrouter.generation_model = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__EMBEDDING_MODEL") {
        if !value.trim().is_empty() {
            settings.openrouter.embedding_model = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__RETRIEVAL__EVIDENCE_TOKEN_BUDGET") {
        if let Ok(budget) = value.trim().parse::<usize>() {
            settings.engine.retrieval.evidence_token_budget = budget;
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__MAX_OUTPUT_TOKENS") {
        if let Ok(tokens) = value.trim().parse::<u32>() {
            settings.openrouter.max_output_tokens = tokens;
        }
    }
    Ok(settings)
}

#[cfg(test)]
mod tests {
    use super::*;

    const CONFIG_TOML: &str = include_str!("../../config/config.toml");
    const CONFIG_EXAMPLE_TOML: &str = include_str!("../../config/config.example.toml");

    /// Minimum gap, in milliseconds, that the operator configuration comments promise between
    /// an outer budget and the inner budgets it contains.
    const NESTING_SLACK_MS: u64 = 500;

    /// The seven `[engine.workflow]` timeout keys paired with the compiled-in default of each.
    fn default_budgets() -> [(&'static str, u64); 7] {
        [
            ("reformulate_timeout_ms", default_reformulate_timeout_ms()),
            (
                "query_embedding_timeout_ms",
                default_query_embedding_timeout_ms(),
            ),
            ("retrieve_timeout_ms", default_retrieve_timeout_ms()),
            (
                "graph_operation_timeout_ms",
                default_graph_operation_timeout_ms(),
            ),
            ("graph_node_timeout_ms", default_graph_node_timeout_ms()),
            ("prompt_timeout_ms", default_prompt_timeout_ms()),
            (
                "generation_node_timeout_ms",
                default_generation_node_timeout_ms(),
            ),
        ]
    }

    /// Reads `engine.workflow.<key>` from a TOML document, failing when the key is absent.
    ///
    /// Reading the raw key, rather than deserializing into `Settings`, keeps a key that a
    /// file dropped from silently agreeing through its serde default.
    fn file_budget(raw: &str, key: &str) -> u64 {
        ::config::Config::builder()
            .add_source(::config::File::from_str(raw, ::config::FileFormat::Toml))
            .build()
            .expect("configuration file must parse as TOML")
            .get::<u64>(&format!("engine.workflow.{key}"))
            .unwrap_or_else(|error| {
                panic!("engine.workflow.{key} must be present and numeric: {error}")
            })
    }

    /// D-66: the committed configuration files and the compiled-in defaults are one budget set.
    #[test]
    fn workflow_budget_defaults_agree_with_config_files() {
        for (file_name, raw) in [
            ("config/config.toml", CONFIG_TOML),
            ("config/config.example.toml", CONFIG_EXAMPLE_TOML),
        ] {
            for (key, default) in default_budgets() {
                assert_eq!(
                    file_budget(raw, key),
                    default,
                    "{file_name} engine.workflow.{key} must equal the config.rs default"
                );
            }
        }
    }

    /// Pins the set the user decided at 06.3.4.1-24 as amended by D-93 (2026-09-29), where
    /// `prompt_timeout_ms` moved from 65 to 120 (recorded in `06.3.4.1-BUDGETS.md`), so a
    /// coordinated edit of the files and the defaults cannot move a budget unnoticed.
    #[test]
    fn workflow_budget_defaults_carry_the_decided_values() {
        assert_eq!(
            default_budgets(),
            [
                ("reformulate_timeout_ms", 5000),
                ("query_embedding_timeout_ms", 2000),
                ("retrieve_timeout_ms", 2500),
                ("graph_operation_timeout_ms", 10000),
                ("graph_node_timeout_ms", 12500),
                ("prompt_timeout_ms", 120),
                ("generation_node_timeout_ms", 65000),
            ]
        );
    }

    /// The defaults nest with the promised slack and pass the engine's own startup checks.
    #[test]
    fn workflow_budget_defaults_nest_and_pass_startup_validation() {
        let settings = WorkflowSettings::default();
        settings
            .validate()
            .expect("default budgets must satisfy graph_node >= query_embedding + graph_operation");
        settings
            .validate_against_provider(30)
            .expect("default generation budget must cover two attempts at the 30s provider timeout");
        assert!(
            settings.graph_node_timeout_ms
                >= settings.query_embedding_timeout_ms
                    + settings.graph_operation_timeout_ms
                    + NESTING_SLACK_MS,
            "graph_node must contain query_embedding + graph_operation with {NESTING_SLACK_MS} ms slack"
        );
        assert!(
            settings.retrieve_timeout_ms >= settings.query_embedding_timeout_ms + NESTING_SLACK_MS,
            "retrieve must contain query_embedding with {NESTING_SLACK_MS} ms slack"
        );
    }

    /// The seven `[engine.graph]` keys paired with the compiled-in default of each, as numbers.
    fn graph_defaults() -> [(&'static str, f64); 7] {
        [
            ("seed_match_min_score", default_seed_match_min_score()),
            ("max_hop_cap", f64::from(default_max_hop_cap())),
            ("max_seeds", default_max_seeds() as f64),
            ("mention_vector_top_k", default_mention_vector_top_k() as f64),
            ("degree_cap", f64::from(default_degree_cap())),
            ("max_path_facts", default_max_path_facts() as f64),
            (
                "max_graph_chunk_candidates",
                default_max_graph_chunk_candidates() as f64,
            ),
        ]
    }

    /// Reads `engine.<table>.<key>` from a TOML document as a number, failing when it is absent.
    ///
    /// Like `file_budget`, this reads the raw key so a key a file dropped cannot agree through
    /// its serde default.
    fn file_number(raw: &str, table: &str, key: &str) -> f64 {
        ::config::Config::builder()
            .add_source(::config::File::from_str(raw, ::config::FileFormat::Toml))
            .build()
            .expect("configuration file must parse as TOML")
            .get::<f64>(&format!("engine.{table}.{key}"))
            .unwrap_or_else(|error| {
                panic!("engine.{table}.{key} must be present and numeric: {error}")
            })
    }

    /// D-66, D-77: the committed configuration files and the compiled-in defaults are one set of
    /// graph settings.
    #[test]
    fn graph_defaults_agree_with_config_files() {
        for (file_name, raw) in [
            ("config/config.toml", CONFIG_TOML),
            ("config/config.example.toml", CONFIG_EXAMPLE_TOML),
        ] {
            for (key, default) in graph_defaults() {
                assert_eq!(
                    file_number(raw, "graph", key),
                    default,
                    "{file_name} engine.graph.{key} must equal the config.rs default"
                );
            }
        }
    }

    /// Pins the decided D-77 values (06.3.4.1-13: `DEGREE_CAP` 33 and `MAX_PATH_FACTS` 8,
    /// confirmed by the user on 2026-10-05) so a coordinated edit of the files and the defaults
    /// cannot move a cap unnoticed.
    #[test]
    fn graph_defaults_carry_the_decided_values() {
        assert_eq!(
            graph_defaults(),
            [
                ("seed_match_min_score", 0.5),
                ("max_hop_cap", 3.0),
                ("max_seeds", 6.0),
                ("mention_vector_top_k", 3.0),
                ("degree_cap", 33.0),
                ("max_path_facts", 8.0),
                ("max_graph_chunk_candidates", 8.0),
            ]
        );
    }

    /// The candidate cap is the number of chunks retrieval returns, so the graph never offers
    /// more chunks than the answer can use.
    #[test]
    fn the_graph_chunk_candidate_cap_equals_the_final_limit_in_the_defaults_and_both_files() {
        assert_eq!(default_max_graph_chunk_candidates(), default_final_limit());
        for (file_name, raw) in [
            ("config/config.toml", CONFIG_TOML),
            ("config/config.example.toml", CONFIG_EXAMPLE_TOML),
        ] {
            assert_eq!(
                file_number(raw, "graph", "max_graph_chunk_candidates"),
                file_number(raw, "retrieval", "final_limit"),
                "{file_name} must keep max_graph_chunk_candidates equal to final_limit"
            );
        }
    }

    /// Startup refuses a graph setting that would make the seeding or the path search do nothing
    /// or run without a bound.
    #[test]
    fn graph_settings_reject_zero_seeds_degree_cap_and_path_facts() {
        type Zeroed = fn(&mut Settings);
        let cases: [(&str, Zeroed); 3] = [
            ("max_seeds", |s| s.engine.graph.max_seeds = 0),
            ("degree_cap", |s| s.engine.graph.degree_cap = 0),
            ("max_path_facts", |s| s.engine.graph.max_path_facts = 0),
        ];
        for (key, zero) in cases {
            let mut settings = Settings::default();
            zero(&mut settings);
            let error = EffectiveRagSettings::try_from_settings(&settings)
                .expect_err(&format!("graph.{key} = 0 must be rejected"));
            assert!(
                error.contains(&format!("graph.{key}")),
                "the error must name graph.{key}: {error}"
            );
        }
        EffectiveRagSettings::try_from_settings(&Settings::default())
            .expect("the defaults must pass validation");
    }
}
