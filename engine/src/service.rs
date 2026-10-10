//! gRPC service implementation for Lancet, covering ingestion, status, graph query, and RAG execution.
//!
//! Owns `LancetServiceImpl` which implements the `LancetService` gRPC definition,
//! along with the internal workflow adapters (`ProductionEmbeddingPort`, `ProductionGraphQueryPort`,
//! `ProductionDenseRetrievalPort`, `ProductionBm25RetrievalPort`), graph augmentation helpers,
//! and stream cancellation utilities.

use std::{
    collections::{HashMap, HashSet},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, OnceLock,
    },
    time::{Instant, SystemTime, UNIX_EPOCH},
};

use arrow_array::{Array, RecordBatch};
use dashmap::DashMap;
use futures::{Stream, TryStreamExt};
use lancedb::{
    query::{ExecutableQuery, QueryBase},
    Table,
};
use tokio::sync::mpsc;
use tonic::{Request, Response, Status};
use tracing::Instrument;
use tracing_opentelemetry::OpenTelemetrySpanExt;
use uuid::Uuid;

use crate::config::{EffectiveRagSettings, GraphSettings};
use crate::db::DatabaseManager;
use crate::generation;
use crate::graph::{self, escape_sql_literal};
use crate::ingest::{
    parse_chunk_settings, persist_raw_with_boundary, EmbeddingProvider, IngestionJob,
    IngestionStatus, LanceDbReplacementMutationBoundary, MAX_DOCUMENT_BYTES,
};
use crate::pb::lancet::v1::{
    self, lancet_service_server::LancetService, GetIngestionStatusRequest,
    GetIngestionStatusResponse, IngestDocumentRequest, IngestDocumentResponse, PingRequest,
    PingResponse, QueryGraphEdge, QueryGraphNode, QueryGraphRequest, QueryGraphResponse,
    QueryRagRequest,
};
use crate::prompt;
use crate::rerank;
use crate::retrieval::{self, DenseRetriever, QueryRequest, RetrievalErrorKind, Retriever};
use crate::workflow::{self, ports::Bm25RetrievalPort};

/// Set once, as early as possible after `telemetry::init` in `main.rs`, so
/// `request_process_state`'s `process_uptime_ms` reflects genuine process uptime rather than
/// time-since-first-request (06.3.4.1-07 Task 2). A missed/late call (e.g. in a test harness
/// that never calls `main`) degrades gracefully: `process_uptime_ms` reads 0 via
/// `get_or_init` on first use, never panics.
pub static PROCESS_START: OnceLock<Instant> = OnceLock::new();

/// Process-lifetime count of completed `query_rag` requests, incremented once per request in
/// the spawned workflow task (06.3.4.1-07 Task 2). Read by `request_process_state`'s
/// `request_ordinal` field; not reset between requests, only between process restarts.
static REQUEST_ORDINAL: AtomicU64 = AtomicU64::new(0);

/// Emits `tracing::info!(request_process_state, ...)` once per completed `query_rag` request,
/// outside every node's own timing span (06.3.4.1-07 Task 2, D-64 full-pipeline diagnosis).
/// `session_size_bytes` is a full `deep_size_of` walk (see `db::lance_session_stats`'s own
/// doc comment), so it is read only on every 50th request to keep this event cheap on the hot
/// path (M-LOG-OVERHEAD); `session_approx_num_items` is read on every request since it is a
/// plain field access, not a deep walk. Reads the session through a clone of the service's
/// startup `nodes` handle via `dataset()`/`session()` -- never `checkout()` (06.1 CR-01: a
/// `checkout()` on a shared `Table` handle races the pinned-version cell other holders of the
/// same clone rely on; a read-only `dataset()`/`session()` walk takes no such lock).
async fn emit_request_process_state(nodes: &Table, correlation_id: &str) {
    let ordinal = REQUEST_ORDINAL.fetch_add(1, Ordering::Relaxed) + 1;
    let uptime_ms = PROCESS_START
        .get_or_init(Instant::now)
        .elapsed()
        .as_millis() as u64;
    let metrics = tokio::runtime::Handle::current().metrics();
    let alive_tasks = metrics.num_alive_tasks();
    let global_queue_depth = metrics.global_queue_depth();

    if ordinal % 50 == 0 {
        let (session_size_bytes, session_approx_num_items) =
            crate::db::lance_session_stats(nodes).await;
        tracing::info!(
            request_process_state = true,
            request_ordinal = ordinal,
            process_uptime_ms = uptime_ms,
            correlation_id = %correlation_id,
            alive_tasks = alive_tasks,
            global_queue_depth = global_queue_depth,
            session_approx_num_items = session_approx_num_items,
            session_size_bytes = session_size_bytes,
            "request_process_state"
        );
    } else {
        let session_approx_num_items = crate::db::lance_session_approx_num_items(nodes).await;
        tracing::info!(
            request_process_state = true,
            request_ordinal = ordinal,
            process_uptime_ms = uptime_ms,
            correlation_id = %correlation_id,
            alive_tasks = alive_tasks,
            global_queue_depth = global_queue_depth,
            session_approx_num_items = session_approx_num_items,
            "request_process_state"
        );
    }
}

/// Lancet gRPC service state holding database handles, background ingestion queue, and RAG components.
#[derive(Clone)]
pub struct LancetServiceImpl {
    pub table: Table,
    pub statuses: Arc<DashMap<String, IngestionStatus>>,
    pub queue: mpsc::Sender<IngestionJob>,
    pub nodes: Table,
    pub corpus_store: workflow::ports::CorpusStore,
    pub effective_settings: EffectiveRagSettings,
    pub generator: Arc<dyn generation::Generator>,
    pub embedder: Arc<dyn EmbeddingProvider>,
    pub reranker: Arc<dyn rerank::Reranker>,
    /// Resources the quality levers need beyond the lever-free path (D-131, D-136).
    pub lever_resources: LeverResources,
    pub database: DatabaseManager,
}

/// The resources that serve the quality levers of a request, held beside the lever-free ones.
///
/// A lever whose resource is `None` is refused at admission with `lever_unavailable`. The
/// service-wide `reranker` stays the lever-free path (a failing reranker there fails the query);
/// `reranker` here is the one a request that names `rerank` uses, where a failure degrades to the
/// fused order instead.
#[derive(Clone, Default)]
pub struct LeverResources {
    /// The reranker of the `rerank` lever; `None` leaves the lever unavailable.
    pub reranker: Option<Arc<dyn rerank::Reranker>>,
}

impl std::fmt::Debug for LeverResources {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("LeverResources")
            .field("reranker", &self.reranker.is_some())
            .finish()
    }
}

/// Which quality levers this engine can serve right now (D-136, D-165).
///
/// A lever whose resource is absent is refused at admission with `lever_unavailable`, so the
/// snapshot echo never claims a lever that did not run.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LeverAvailability {
    rerank: bool,
    evidence_metadata: bool,
    binary_answer_format: bool,
    graph_v2: bool,
}

impl LeverAvailability {
    /// Whether `lever` can be served; `LEVER_UNSPECIFIED` never can.
    pub fn is_available(&self, lever: v1::Lever) -> bool {
        match lever {
            v1::Lever::Unspecified => false,
            v1::Lever::Rerank => self.rerank,
            v1::Lever::EvidenceMetadata => self.evidence_metadata,
            v1::Lever::BinaryAnswerFormat => self.binary_answer_format,
            v1::Lever::GraphV2 => self.graph_v2,
        }
    }
}

impl LancetServiceImpl {
    /// Reports which levers this engine can serve against `_snapshot`.
    ///
    /// `binary_answer_format` needs no resource and is available. `rerank` is available when
    /// the lever reranker is wired (D-131). `evidence_metadata` and `graph_v2` stay unavailable
    /// until the plans that implement them wire their resource (the evidence metadata columns of
    /// the corpus snapshot, the graph repair).
    pub fn lever_availability(
        &self,
        _snapshot: &workflow::ports::CorpusSnapshot,
    ) -> LeverAvailability {
        LeverAvailability {
            rerank: self.lever_resources.reranker.is_some(),
            evidence_metadata: false,
            binary_answer_format: true,
            graph_v2: false,
        }
    }

    /// Persists a raw ingestion job to the staged documents table.
    pub async fn persist_raw(&self, job: &IngestionJob) -> Result<(), Status> {
        persist_raw_with_boundary(&self.table, job, &LanceDbReplacementMutationBoundary)
            .await
            .map_err(internal)
    }

    /// Assembles the production workflow runner and dependencies for a request that names no lever.
    pub fn build_production_workflow(
        &self,
        snapshot: Arc<workflow::ports::CorpusSnapshot>,
    ) -> (workflow::WorkflowRunner, workflow::WorkflowDependencies) {
        self.build_production_workflow_with_levers(snapshot, &workflow::LeverSet::default())
    }

    /// Assembles the production workflow runner and dependencies for the admitted `levers`.
    ///
    /// The lever reranker reaches `RetrieveHybrid` only when `levers` contains `rerank`; a request
    /// without it builds the same nodes as [`build_production_workflow`](Self::build_production_workflow).
    pub fn build_production_workflow_with_levers(
        &self,
        snapshot: Arc<workflow::ports::CorpusSnapshot>,
        levers: &workflow::LeverSet,
    ) -> (workflow::WorkflowRunner, workflow::WorkflowDependencies) {
        let embedder_adapter: Arc<dyn workflow::node::QueryEmbeddingPort> =
            Arc::new(ProductionEmbeddingPort {
                embedder: Arc::clone(&self.embedder),
            });
        let graph_adapter: Arc<dyn workflow::ports::GraphQueryPort> =
            Arc::new(ProductionGraphQueryPort {
                database: self.database.clone(),
                graph_settings: self.effective_settings.graph.clone(),
                graph_index: Arc::clone(&snapshot.graph_index),
                embedder: Arc::clone(&self.embedder),
            });
        let dense_adapter: Arc<dyn workflow::ports::DenseRetrievalPort> =
            Arc::new(ProductionDenseRetrievalPort {
                database: self.database.clone(),
                nodes_version: snapshot.nodes_version,
                retrieval_settings: self.effective_settings.retrieval.clone(),
            });
        let bm25_adapter: Arc<dyn workflow::ports::Bm25RetrievalPort> =
            Arc::new(ProductionBm25RetrievalPort {
                bm25: Arc::clone(&snapshot.bm25),
                retrieval_settings: self.effective_settings.retrieval.clone(),
            });
        let reranker_adapter: Arc<dyn rerank::Reranker> = Arc::clone(&self.reranker);
        let generator_adapter: Arc<dyn generation::Generator> = Arc::clone(&self.generator);
        let reformulator_adapter: Arc<dyn workflow::ports::QueryReformulator> =
            Arc::new(workflow::ports::NoOpQueryReformulator::new());

        let deps = workflow::WorkflowDependencies {
            reformulator: Some(reformulator_adapter),
            embedding_port: Some(embedder_adapter),
            graph_port: Some(graph_adapter),
            dense_port: Some(dense_adapter),
            bm25_port: Some(bm25_adapter),
            reranker_port: Some(reranker_adapter),
            generator: Some(generator_adapter),
            retrieval_settings: self.effective_settings.retrieval.clone(),
            graph_weight: self.effective_settings.retrieval.graph_weight,
            grounding_limits: *self.effective_settings.grounding_limits(),
        };

        // The lever reranker reaches the node only for a request that names the lever.
        let lever_reranker = if levers.contains(v1::Lever::Rerank) {
            self.lever_resources.reranker.clone()
        } else {
            None
        };

        let wf = &self.effective_settings.workflow;
        let mut runner = workflow::WorkflowRunner::new().with_timeouts(
            wf.reformulate_timeout_ms,
            wf.graph_node_timeout_ms,
            wf.retrieve_timeout_ms,
            wf.prompt_timeout_ms,
            wf.generation_node_timeout_ms,
        );
        runner.add_node(workflow::nodes::ReformulateQueryNode::with_reformulator(
            deps.reformulator.clone(),
        ));
        runner.add_node(
            workflow::nodes::ExtractGraphContextNode::new(
                deps.embedding_port.clone(),
                deps.graph_port.clone(),
            )
            .with_timeouts(wf.query_embedding_timeout_ms, wf.graph_operation_timeout_ms),
        );
        runner.add_node(
            workflow::nodes::RetrieveHybridNode::new(
                deps.dense_port.clone(),
                deps.bm25_port.clone(),
                deps.reranker_port.clone(),
                deps.retrieval_settings.clone(),
            )
            .with_snapshot_metadata(
                snapshot.generation.clone(),
                self.effective_settings.embedding_model.clone(),
            )
            .with_rebuild_degraded(snapshot.rebuild_degraded)
            .with_excerpt_max_chars(self.effective_settings.citation_excerpt_max_chars)
            .with_doc_meta(Arc::clone(&snapshot.doc_meta))
            .with_rerank_lever(
                lever_reranker,
                std::time::Duration::from_millis(wf.rerank_timeout_ms),
                std::time::Duration::from_millis(wf.retrieve_timeout_ms),
            ),
        );
        runner.add_node(workflow::nodes::AssemblePromptNode::with_settings(
            self.effective_settings
                .grounding_limits()
                .evidence_token_budget() as usize,
            self.effective_settings
                .grounding_limits()
                .max_output_tokens() as usize,
            self.effective_settings.retrieval.graph_weight,
        ));
        runner.add_node(
            workflow::nodes::GenerateAnswerNode::new(deps.generator.clone())
                .with_settings(
                    *self.effective_settings.grounding_limits(),
                    self.effective_settings.citation_excerpt_max_chars,
                    self.effective_settings.retrieval.graph_weight,
                )
                .with_citation_repair_enabled(
                    self.effective_settings.workflow.citation_repair_enabled,
                ),
        );

        (runner, deps)
    }
}

/// Converts any displayable error into a gRPC internal status.
pub fn internal(err: impl std::fmt::Display) -> Status {
    Status::internal(err.to_string())
}

/// Filters ASCII graphic characters and truncates to a maximum byte length.
pub fn sanitize_header_value(s: &str, max_len: usize) -> String {
    s.chars()
        .filter(|c| c.is_ascii_graphic())
        .take(max_len)
        .collect()
}

/// Builds a `Status` carrying the `x-lancet-*` gRPC trailers that
/// `gateway/main.go::handlePreStreamError` reads to surface error identity on
/// pre-stream `QueryRAG` failures.
pub fn d1_status(
    code: tonic::Code,
    message: impl Into<String>,
    session_id: &str,
    correlation_id: &str,
    error_kind: &str,
) -> Status {
    let msg = message.into();
    let safe_session_id = sanitize_header_value(session_id, 128);
    let safe_correlation_id = sanitize_header_value(correlation_id, 128);
    let safe_error_kind = sanitize_header_value(error_kind, 64);
    tracing::warn!(
        session_id = %safe_session_id,
        correlation_id = %safe_correlation_id,
        error_kind = %safe_error_kind,
        "QueryRAG pre-stream failure: {msg}"
    );
    let mut status = Status::new(code, msg);
    let metadata = status.metadata_mut();
    if let Ok(val) = safe_session_id.parse() {
        metadata.insert("x-lancet-session-id", val);
    }
    if let Ok(val) = safe_correlation_id.parse() {
        metadata.insert("x-lancet-correlation-id", val);
    }
    if let Ok(val) = safe_error_kind.parse() {
        metadata.insert("x-lancet-error-kind", val);
    }
    status
}

/// Validates that a string is a valid UUIDv4.
pub fn validate_document_id(document_id: &str) -> Result<(), Status> {
    let id = Uuid::parse_str(document_id)
        .map_err(|_| Status::invalid_argument("document_id must be a UUIDv4 string"))?;
    if id.get_version_num() != 4 || id.get_variant() != uuid::Variant::RFC4122 {
        return Err(Status::invalid_argument(
            "document_id must be a UUIDv4 string",
        ));
    }
    Ok(())
}

/// Outcome of attempting graph augmentation for a query.
#[derive(Debug, Clone)]
pub enum GraphAugmentationOutcome {
    /// Graph augmentation succeeded with extracted facts.
    Succeeded {
        facts: Vec<graph::context_strategy::GraphFact>,
    },
    /// No matching entity found in graph above threshold.
    NoMatchFound,
    /// An error occurred during graph query or traversal.
    AttemptedAndFailed { reason: String },
}

/// What a graph augmentation found, beyond the facts themselves (D-79).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct GraphAugmentationReport {
    /// Seeds the question mentions matched.
    pub seed_count: u32,
    /// Whether at least one seed-to-seed path was kept.
    pub path_found: bool,
    /// Two-hop paths dropped because their intermediate was above the degree cap.
    pub degree_capped_count: u32,
    /// Document IDs of the seeds' source chunks, sorted and de-duplicated.
    pub seed_document_ids: Vec<String>,
    /// Source-chunk IDs of the entities on the kept paths (empty when no path was kept).
    pub chunk_candidates: Vec<String>,
    /// Distinct entities on the kept paths.
    pub node_count: u32,
    /// Relations on the kept paths, one per hop.
    pub edge_count: u32,
}

/// Augments a query with the seed-to-seed paths between the entities its question mentions.
///
/// The question text yields mentions, the mentions are matched to seed entities by name and then
/// by name vector (D-75), and only the paths that join two seeds become facts (D-76). A seed's own
/// neighbourhood is never injected. `graph_index` is the index of the snapshot the query was
/// admitted under. Every failure is an `AttemptedAndFailed`; nothing here panics.
pub async fn attempt_graph_augmentation(
    database: &DatabaseManager,
    graph_index: &graph::index::GraphIndex,
    question: &str,
    embedder: &Arc<dyn EmbeddingProvider>,
    settings: &GraphSettings,
) -> (GraphAugmentationOutcome, GraphAugmentationReport) {
    let search = graph::seeding::LanceMentionVectorSearch {
        database: database.clone(),
        embedder: Arc::clone(embedder),
    };
    attempt_graph_augmentation_with_search(database, graph_index, question, &search, settings).await
}

/// [`attempt_graph_augmentation`] with the mention vector search supplied by the caller.
///
/// An index with no entities, and a question with no mention, return `NoMatchFound` before any
/// embedding call or store read. Seeds that no path joins are a success with no facts, no chunk
/// candidates (decision `paths-only`) and the seed count recorded.
pub async fn attempt_graph_augmentation_with_search(
    database: &DatabaseManager,
    graph_index: &graph::index::GraphIndex,
    question: &str,
    search: &dyn graph::seeding::MentionVectorSearch,
    settings: &GraphSettings,
) -> (GraphAugmentationOutcome, GraphAugmentationReport) {
    let no_match = || {
        (
            GraphAugmentationOutcome::NoMatchFound,
            GraphAugmentationReport::default(),
        )
    };
    let failed = |reason: String| {
        (
            GraphAugmentationOutcome::AttemptedAndFailed { reason },
            GraphAugmentationReport::default(),
        )
    };

    if graph_index.entity_count() == 0 {
        return no_match();
    }
    let mentions = graph::seeding::extract_mentions(question);
    if mentions.is_empty() {
        return no_match();
    }
    let seeds = match graph::seeding::match_seeds(
        graph_index,
        &mentions,
        search,
        &settings.seed_settings(),
    )
    .await
    {
        Ok(seeds) => seeds,
        Err(error) => return failed(format!("seed matching failed: {error}")),
    };
    if seeds.is_empty() {
        return no_match();
    }
    let paths = match graph::paths::find_seed_paths(
        database,
        graph_index,
        &seeds,
        &settings.path_settings(),
    )
    .await
    {
        Ok(paths) => paths,
        Err(error) => return failed(format!("seed path search failed: {error}")),
    };

    let mut seed_document_ids: Vec<String> = seeds
        .iter()
        .flat_map(|seed| graph_index.seed_document_ids(&seed.entity_id))
        .collect();
    seed_document_ids.sort_unstable();
    seed_document_ids.dedup();
    let path_entities: HashSet<&str> = paths
        .paths
        .iter()
        .flat_map(|path| path.entities.iter().map(String::as_str))
        .collect();
    let report = GraphAugmentationReport {
        seed_count: seeds.len() as u32,
        path_found: paths.path_found,
        degree_capped_count: paths.degree_capped_count,
        seed_document_ids,
        chunk_candidates: paths.candidate_chunk_ids,
        node_count: path_entities.len() as u32,
        edge_count: paths.paths.iter().map(|path| path.relations.len() as u32).sum(),
    };
    (
        GraphAugmentationOutcome::Succeeded { facts: paths.facts },
        report,
    )
}

/// Production adapter implementing `QueryEmbeddingPort` backed by `EmbeddingProvider`.
pub struct ProductionEmbeddingPort {
    pub embedder: Arc<dyn EmbeddingProvider>,
}

impl workflow::node::QueryEmbeddingPort for ProductionEmbeddingPort {
    fn embed_variant_zero<'a>(
        &'a self,
        variant: &'a str,
        cancel: &'a tokio_util::sync::CancellationToken,
    ) -> workflow::node::BoxFuture<'a, Result<Vec<f32>, workflow::node::NodeError>> {
        let span = tracing::info_span!(
            "embedding_request",
            gen_ai.request.model = %self.embedder.model_id(),
        );
        Box::pin(
            async move {
                if cancel.is_cancelled() {
                    return Err(workflow::node::NodeError::cancelled());
                }
                let vecs = self
                    .embedder
                    .get_embeddings(&[variant.to_string()])
                    .await
                    .map_err(|err| {
                        workflow::node::NodeError::new(
                            v1::NodeErrorKind::RetrievalFailed,
                            format!("embedding provider transport error: {err}"),
                        )
                    })?;
                if vecs.len() != 1 || vecs[0].len() != 2048 || vecs[0].iter().any(|f| !f.is_finite()) {
                    return Err(workflow::node::NodeError::new(
                        v1::NodeErrorKind::RetrievalFailed,
                        "embedding provider returned invalid payload",
                    ));
                }
                Ok(vecs.into_iter().next().unwrap())
            }
            .instrument(span),
        )
    }
}

/// Production adapter implementing `GraphQueryPort` backed by LanceDB entity tables.
pub struct ProductionGraphQueryPort {
    pub database: DatabaseManager,
    pub graph_settings: GraphSettings,
    /// The graph index of the snapshot this request was admitted under, so a query sees one
    /// generation of the index however many rebuilds happen while it runs.
    pub graph_index: Arc<graph::index::GraphIndex>,
    /// Embeds the question mentions that no entity name matched.
    pub embedder: Arc<dyn EmbeddingProvider>,
}

impl workflow::ports::GraphQueryPort for ProductionGraphQueryPort {
    fn query_graph<'a>(
        &'a self,
        question: &'a str,
        _query_embedding: &'a [f32],
        cancel: &'a tokio_util::sync::CancellationToken,
    ) -> workflow::node::BoxFuture<
        'a,
        Result<workflow::ports::GraphQueryOutput, workflow::node::NodeError>,
    > {
        let span = tracing::info_span!(
            "graph_traversal",
            graph_augmentation = tracing::field::Empty,
            lancet.graph.node_count = tracing::field::Empty,
            lancet.graph.edge_count = tracing::field::Empty,
            lancet.graph.seed_count = tracing::field::Empty,
            lancet.graph.path_found = tracing::field::Empty,
        );
        Box::pin(
            async move {
                if cancel.is_cancelled() {
                    return Err(workflow::node::NodeError::cancelled());
                }
                let (graph_outcome, report) = attempt_graph_augmentation(
                    &self.database,
                    &self.graph_index,
                    question,
                    &self.embedder,
                    &self.graph_settings,
                )
                .await;

                let tag = match &graph_outcome {
                    GraphAugmentationOutcome::Succeeded { .. } => "succeeded",
                    GraphAugmentationOutcome::NoMatchFound => "no_match_found",
                    GraphAugmentationOutcome::AttemptedAndFailed { .. } => "attempted_and_failed",
                };
                tracing::Span::current().record("graph_augmentation", tag);
                // Counts and a boolean only: no question text and no entity name reach a span.
                tracing::Span::current()
                    .record("lancet.graph.seed_count", u64::from(report.seed_count));
                tracing::Span::current().record("lancet.graph.path_found", report.path_found);

                let facts: Vec<prompt::GraphFactBlock> = match graph_outcome {
                    GraphAugmentationOutcome::Succeeded { facts } => {
                        tracing::Span::current()
                            .record("lancet.graph.node_count", u64::from(report.node_count));
                        tracing::Span::current()
                            .record("lancet.graph.edge_count", u64::from(report.edge_count));
                        facts
                            .into_iter()
                            .map(|fact| prompt::GraphFactBlock { fact })
                            .collect()
                    }
                    GraphAugmentationOutcome::NoMatchFound => {
                        tracing::Span::current().record("lancet.graph.node_count", 0u64);
                        tracing::Span::current().record("lancet.graph.edge_count", 0u64);
                        vec![]
                    }
                    GraphAugmentationOutcome::AttemptedAndFailed { reason } => {
                        return Err(workflow::node::NodeError::new(
                            v1::NodeErrorKind::GraphFailed,
                            format!("graph augmentation failed: {reason}"),
                        ));
                    }
                };
                Ok(workflow::ports::GraphQueryOutput {
                    facts,
                    node_count: report.node_count,
                    edge_count: report.edge_count,
                    seed_count: report.seed_count,
                    path_found: report.path_found,
                    degree_capped_count: report.degree_capped_count,
                    seed_document_ids: report.seed_document_ids,
                    chunk_candidates: report.chunk_candidates,
                })
            }
            .instrument(span),
        )
    }
}

/// Production adapter implementing `DenseRetrievalPort` backed by LanceDB nodes table.
pub struct ProductionDenseRetrievalPort {
    pub database: DatabaseManager,
    pub nodes_version: u64,
    pub retrieval_settings: retrieval::RetrievalSettings,
}

impl workflow::ports::DenseRetrievalPort for ProductionDenseRetrievalPort {
    fn retrieve_dense<'a>(
        &'a self,
        query: &'a str,
        query_embedding: &'a [f32],
        filter: Option<&'a v1::DocumentFilter>,
        cancel: &'a tokio_util::sync::CancellationToken,
    ) -> workflow::node::BoxFuture<'a, Result<Vec<retrieval::Candidate>, workflow::node::NodeError>>
    {
        let generation = workflow::ports::corpus_generation_from_nodes_version(self.nodes_version);
        let span = tracing::info_span!(
            "dense_search",
            db.system = "lancedb",
            db.operation = "vector_search",
            lancet.index.generation = %generation,
        );
        Box::pin(
            async move {
                if cancel.is_cancelled() {
                    return Err(workflow::node::NodeError::cancelled());
                }
                let (doc_ids, content_types) = if let Some(f) = filter {
                    (f.document_ids.clone(), f.content_types.clone())
                } else {
                    (vec![], vec![])
                };
                let query_req =
                    QueryRequest::from_values(query, doc_ids, content_types, &self.retrieval_settings)
                        .map_err(|err| {
                            workflow::node::NodeError::new(
                                v1::NodeErrorKind::RetrievalFailed,
                                err.message(),
                            )
                        })?;
                let open_table_start = std::time::Instant::now();
                let nodes = self.database.nodes_table().await.map_err(|err| {
                    workflow::node::NodeError::new(
                        v1::NodeErrorKind::RetrievalFailed,
                        format!("failed to open nodes table: {err}"),
                    )
                })?;
                let open_table_ms = open_table_start.elapsed().as_secs_f64() * 1000.0;
                let checkout_start = std::time::Instant::now();
                nodes.checkout(self.nodes_version).await.map_err(|err| {
                    workflow::node::NodeError::new(
                        v1::NodeErrorKind::RetrievalFailed,
                        format!("dense checkout failure at version {}: {err}", self.nodes_version),
                    )
                })?;
                let checkout_ms = checkout_start.elapsed().as_secs_f64() * 1000.0;
                // Best-effort OI-02 side channel (06.3.4.1-03 Task 1): populated only when this
                // call runs inside `RetrieveHybridNode::execute`'s task-local scope
                // (`workflow::nodes::retrieve::DENSE_SUBSTAGE_TIMINGS`). A direct caller outside
                // that scope (e.g. a unit test constructing this port standalone) silently gets
                // no-op behavior here rather than a panic.
                let _ = crate::workflow::nodes::retrieve::DENSE_SUBSTAGE_TIMINGS.try_with(|cell| {
                    cell.set(crate::workflow::nodes::retrieve::DenseSubStageTimings {
                        open_table_ms,
                        checkout_ms,
                    });
                });
                let dense_retriever = DenseRetriever::new(nodes);
                dense_retriever
                    .query(query_embedding, &query_req, &self.retrieval_settings)
                    .await
                    .map_err(|err| {
                        workflow::node::NodeError::new(
                            v1::NodeErrorKind::RetrievalFailed,
                            format!("dense retrieval failure: {}", err.message()),
                        )
                    })
            }
            .instrument(span),
        )
    }

    fn fetch_chunks_by_id<'a>(
        &'a self,
        chunk_ids: &'a [String],
        cancel: &'a tokio_util::sync::CancellationToken,
    ) -> workflow::node::BoxFuture<'a, Result<Vec<retrieval::Candidate>, workflow::node::NodeError>>
    {
        let generation = workflow::ports::corpus_generation_from_nodes_version(self.nodes_version);
        let span = tracing::info_span!(
            "graph_chunk_fetch",
            db.system = "lancedb",
            db.operation = "select",
            lancet.index.generation = %generation,
        );
        Box::pin(
            async move {
                if cancel.is_cancelled() {
                    return Err(workflow::node::NodeError::cancelled());
                }
                let nodes = self.database.nodes_table().await.map_err(|err| {
                    workflow::node::NodeError::new(
                        v1::NodeErrorKind::RetrievalFailed,
                        format!("failed to open nodes table: {err}"),
                    )
                })?;
                // The same checkout as `retrieve_dense`: the graph chunks come from the
                // snapshot's generation, never a later version of the table. This call does not
                // touch `DENSE_SUBSTAGE_TIMINGS`, which belongs to the dense search.
                nodes.checkout(self.nodes_version).await.map_err(|err| {
                    workflow::node::NodeError::new(
                        v1::NodeErrorKind::RetrievalFailed,
                        format!(
                            "graph chunk checkout failure at version {}: {err}",
                            self.nodes_version
                        ),
                    )
                })?;
                DenseRetriever::new(nodes)
                    .fetch_by_chunk_ids(chunk_ids)
                    .await
                    .map_err(|err| {
                        workflow::node::NodeError::new(
                            v1::NodeErrorKind::RetrievalFailed,
                            format!("graph chunk fetch failure: {}", err.message()),
                        )
                    })
            }
            .instrument(span),
        )
    }
}

/// Production adapter implementing `Bm25RetrievalPort` backed by the in-memory BM25 index snapshot.
pub struct ProductionBm25RetrievalPort {
    pub bm25: Arc<crate::retrieval::bm25::Bm25Index>,
    pub retrieval_settings: retrieval::RetrievalSettings,
}

impl Bm25RetrievalPort for ProductionBm25RetrievalPort {
    fn retrieve_bm25<'a>(
        &'a self,
        query: &'a str,
        filter: Option<&'a v1::DocumentFilter>,
        cancel: &'a tokio_util::sync::CancellationToken,
    ) -> workflow::node::BoxFuture<'a, Result<Vec<retrieval::Candidate>, workflow::node::NodeError>>
    {
        let span = tracing::info_span!(
            "bm25_search",
            lancet.retrieval.path = "bm25",
            lancet.index.generation = "bm25-memory",
        );
        Box::pin(
            async move {
                if cancel.is_cancelled() {
                    return Err(workflow::node::NodeError::cancelled());
                }
                let (doc_ids, content_types) = if let Some(f) = filter {
                    (f.document_ids.clone(), f.content_types.clone())
                } else {
                    (vec![], vec![])
                };
                let query_req =
                    QueryRequest::from_values(query, doc_ids, content_types, &self.retrieval_settings)
                        .map_err(|err| {
                            workflow::node::NodeError::new(
                                v1::NodeErrorKind::RetrievalFailed,
                                err.message(),
                            )
                        })?;
                self.bm25
                    .retrieve(&query_req, &self.retrieval_settings)
                    .await
                    .map_err(|err| {
                        workflow::node::NodeError::new(
                            v1::NodeErrorKind::RetrievalFailed,
                            err.to_string(),
                        )
                    })
            }
            .instrument(span),
        )
    }
}

/// Stream wrapper that triggers cancellation of a CancellationToken on drop.
pub struct CancelOnDropStream<S> {
    pub inner: S,
    pub cancel: tokio_util::sync::CancellationToken,
}

impl<S: Stream + Unpin> Stream for CancelOnDropStream<S> {
    type Item = S::Item;

    fn poll_next(
        mut self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<Option<Self::Item>> {
        std::pin::Pin::new(&mut self.inner).poll_next(cx)
    }
}

impl<S> Drop for CancelOnDropStream<S> {
    fn drop(&mut self) {
        tracing::info!("CancelOnDropStream::drop called, cancelling workflow token");
        self.cancel.cancel();
    }
}

#[tonic::async_trait]
impl LancetService for LancetServiceImpl {
    async fn ping(&self, request: Request<PingRequest>) -> Result<Response<PingResponse>, Status> {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(internal)?
            .as_millis() as i64;
        Ok(Response::new(PingResponse {
            value: format!("pong: {}", request.into_inner().value),
            timestamp,
        }))
    }

    async fn ingest_document(
        &self,
        request: Request<tonic::Streaming<IngestDocumentRequest>>,
    ) -> Result<Response<IngestDocumentResponse>, Status> {
        let parent_cx = crate::telemetry::propagation::extract_parent_context(request.metadata());
        let mut stream = request.into_inner();
        let admission_span = tracing::info_span!(
            "ingest_admission",
            lancet.document.id = tracing::field::Empty,
            lancet.document.bytes = tracing::field::Empty,
        );
        let _ = admission_span.set_parent(parent_cx);

        async {
            let mut document_id = String::new();
            let mut filename = String::new();
            let mut metadata = HashMap::new();
            let mut raw = Vec::new();
            let mut first_frame = true;
            let mut parsed_settings = None;
            while let Some(message) = stream.message().await? {
                if first_frame {
                    first_frame = false;
                    document_id = message.document_id.clone();
                    filename = message.filename.clone();
                    metadata = message.metadata.clone();
                    parsed_settings = Some(parse_chunk_settings(&metadata)?);
                    tracing::Span::current().record("lancet.document.id", &document_id);
                } else {
                    if !message.metadata.is_empty() {
                        return Err(Status::invalid_argument(
                            "stream metadata must not be provided on subsequent frames",
                        ));
                    }
                }
                if message.document_id != document_id {
                    return Err(Status::invalid_argument(
                        "stream contains multiple document ids",
                    ));
                }
                if raw.len() + message.chunk_data.len() > MAX_DOCUMENT_BYTES {
                    return Err(Status::resource_exhausted("document exceeds 10MB"));
                }
                raw.extend_from_slice(&message.chunk_data);
            }
            tracing::Span::current().record("lancet.document.bytes", raw.len());
            if document_id.is_empty() {
                return Err(Status::invalid_argument("empty ingestion stream"));
            }
            validate_document_id(&document_id)?;
            let permit = self
                .queue
                .clone()
                .try_reserve_owned()
                .map_err(|_| Status::resource_exhausted("ingestion queue is full"))?;
            let trace_parent = crate::telemetry::propagation::inject_trace_parent(&tracing::Span::current().context());
            let job = IngestionJob {
                document_id: document_id.clone(),
                filename,
                raw_data: raw,
                metadata,
                chunk_settings: parsed_settings.expect("parsed settings present for non-empty stream"),
                trace_parent,
            };
            self.persist_raw(&job).await?;
            self.statuses
                .insert(document_id.clone(), IngestionStatus::queued());
            permit.send(job);
            Ok(Response::new(IngestDocumentResponse {
                document_id,
                success: true,
                message: "queued".into(),
            }))
        }
        .instrument(admission_span)
        .await
    }

    async fn get_ingestion_status(
        &self,
        request: Request<GetIngestionStatusRequest>,
    ) -> Result<Response<GetIngestionStatusResponse>, Status> {
        let id = request.into_inner().document_id;
        if let Some(state) = self.statuses.get(&id) {
            return Ok(Response::new(GetIngestionStatusResponse {
                document_id: id,
                status: state.status.clone(),
                chunk_count: state.chunk_count,
                error_message: state.error_message.clone(),
            }));
        }
        let predicate = format!("document_id = '{}'", escape_sql_literal(&id));
        match self.table.count_rows(Some(predicate)).await {
            Ok(count) => {
                if count > 0 {
                    Ok(Response::new(GetIngestionStatusResponse {
                        document_id: id,
                        status: "queued".into(),
                        chunk_count: 0,
                        error_message: String::new(),
                    }))
                } else {
                    Err(Status::not_found("document status not found"))
                }
            }
            Err(error) => Err(Status::unavailable(format!(
                "staged_documents_v2 query failed: {error}"
            ))),
        }
    }

    type QueryRAGStream = std::pin::Pin<
        Box<dyn tokio_stream::Stream<Item = Result<v1::WorkflowEvent, Status>> + Send + 'static>,
    >;

    async fn query_rag(
        &self,
        request: Request<QueryRagRequest>,
    ) -> Result<Response<Self::QueryRAGStream>, Status> {
        let parent_context = crate::telemetry::propagation::extract_parent_context(request.metadata());
        let req = request.into_inner();
        let correlation_id = Uuid::new_v4().to_string();

        let session_id = if req.session_id.trim().is_empty() {
            Uuid::new_v4().to_string()
        } else {
            let raw_session_id = req.session_id.trim().to_string();
            let parsed = Uuid::parse_str(&raw_session_id).map_err(|_| {
                d1_status(
                    tonic::Code::InvalidArgument,
                    "session_id must be a valid UUIDv4 string",
                    &raw_session_id,
                    &correlation_id,
                    "invalid_session_id",
                )
            })?;
            if parsed.get_version_num() != 4 || parsed.get_variant() != uuid::Variant::RFC4122 {
                return Err(d1_status(
                    tonic::Code::InvalidArgument,
                    "session_id must be a valid UUIDv4 string",
                    &raw_session_id,
                    &correlation_id,
                    "invalid_session_id",
                ));
            }
            parsed.to_string()
        };

        let (doc_ids, content_types) = if let Some(ref filter) = req.filter {
            (filter.document_ids.clone(), filter.content_types.clone())
        } else {
            (vec![], vec![])
        };

        // Resolved once at admission; Phase 6 adds no configuration key for this flag.
        let disable_graph_context = req.disable_graph_context.unwrap_or(false);

        // D-99 fails closed: a mode this build does not know is refused here and never read as
        // hybrid, because a silent default would make an ablation arm's delta an artefact. The
        // gateway refuses an unknown name first; this is the engine's own check for a direct caller.
        if v1::RetrievalMode::try_from(req.retrieval_mode).is_err() {
            return Err(d1_status(
                tonic::Code::InvalidArgument,
                "retrieval_mode must be one of hybrid, dense_only, bm25_only",
                &session_id,
                &correlation_id,
                "invalid_retrieval_mode",
            ));
        }

        // D-136 fails closed on the raw integers: an unknown, zero, negative or repeated lever is
        // refused here and never ignored, because a silently dropped lever would make an arm's
        // delta an artefact. The gateway refuses a bad name first; this is the engine's own check
        // for a direct caller.
        let levers = workflow::LeverSet::try_from_wire(&req.levers).map_err(|err| {
            d1_status(
                tonic::Code::InvalidArgument,
                format!("invalid levers: {err}"),
                &session_id,
                &correlation_id,
                "invalid_levers",
            )
        })?;

        // D-165: the graph repair needs the graph, so asking for it with the graph off is a
        // contradiction, refused before availability is consulted.
        if levers.contains(v1::Lever::GraphV2) && disable_graph_context {
            return Err(d1_status(
                tonic::Code::InvalidArgument,
                "levers graph_v2 cannot be combined with disable_graph_context",
                &session_id,
                &correlation_id,
                "invalid_lever_combination",
            ));
        }

        // A lever whose resource this engine does not hold is refused, never admitted and echoed:
        // the echo claims which levers ran.
        let snapshot = {
            let guard = self.corpus_store.read().await;
            Arc::clone(&*guard)
        };
        let availability = self.lever_availability(&snapshot);
        if let Some(lever) = levers
            .iter()
            .find(|lever| !availability.is_available(*lever))
        {
            return Err(d1_status(
                tonic::Code::InvalidArgument,
                format!("lever {} is not available on this engine", lever.as_str_name()),
                &session_id,
                &correlation_id,
                "lever_unavailable",
            ));
        }

        let _query_request = QueryRequest::from_values(
            &req.query,
            doc_ids,
            content_types,
            &self.effective_settings.retrieval,
        )
        .map_err(|err| {
            let (code, err_kind_str) = match err.kind {
                RetrievalErrorKind::EmptyQuery => (tonic::Code::InvalidArgument, "empty_query"),
                RetrievalErrorKind::QueryTooLong => {
                    (tonic::Code::InvalidArgument, "query_too_long")
                }
                RetrievalErrorKind::InvalidDocumentId => {
                    (tonic::Code::InvalidArgument, "invalid_document_id")
                }
                RetrievalErrorKind::UnsupportedContentType => {
                    (tonic::Code::InvalidArgument, "unsupported_content_type")
                }
                RetrievalErrorKind::EmptyFilterValue => {
                    (tonic::Code::InvalidArgument, "empty_filter_value")
                }
                RetrievalErrorKind::FilterLimitExceeded => {
                    (tonic::Code::InvalidArgument, "filter_limit_exceeded")
                }
                RetrievalErrorKind::InvalidSettings => {
                    (tonic::Code::InvalidArgument, "invalid_settings")
                }
                RetrievalErrorKind::NonFiniteScore => (tonic::Code::Internal, "non_finite_score"),
                RetrievalErrorKind::Snapshot => (tonic::Code::Internal, "snapshot"),
            };
            d1_status(
                code,
                err.message(),
                &session_id,
                &correlation_id,
                err_kind_str,
            )
        })?;

        let (tx, rx) = mpsc::channel(100);
        let cancel = tokio_util::sync::CancellationToken::new();
        let receiver_stream = tokio_stream::wrappers::ReceiverStream::new(rx);
        let stream: Self::QueryRAGStream = Box::pin(CancelOnDropStream {
            inner: receiver_stream,
            cancel: cancel.clone(),
        });

        let sequence = Arc::new(workflow::EventSequence::new());
        let sink = workflow::WorkflowEventSink::new(
            tx,
            sequence,
            correlation_id.clone(),
            session_id.clone(),
        );

        let wf = &self.effective_settings.workflow;
        let mut ctx =
            workflow::WorkflowContext::new(session_id.clone(), correlation_id.clone(), &req);
        ctx.allow_model_only = req.allow_model_only.unwrap_or(wf.allow_model_only_answers);
        ctx.levers = levers;
        let (runner, deps) = self.build_production_workflow_with_levers(snapshot, &ctx.levers);

        let parent_span = tracing::info_span!(
            "query_rag",
            graph_augmentation = tracing::field::Empty,
            session_id = %session_id,
            correlation_id = %correlation_id,
            "lancet.workflow.started_at_ms" = tracing::field::Empty,
            "lancet.workflow.completed_at_ms" = tracing::field::Empty,
            "lancet.workflow.reformulation_used" = tracing::field::Empty,
            "lancet.workflow.vector_count" = tracing::field::Empty,
            "lancet.workflow.bm25_count" = tracing::field::Empty,
            "lancet.workflow.graph_node_count" = tracing::field::Empty,
            "lancet.workflow.graph_edge_count" = tracing::field::Empty,
            "lancet.workflow.graph_prompt_fact_count" = tracing::field::Empty,
            "lancet.workflow.graph_seed_count" = tracing::field::Empty,
            "lancet.workflow.graph_path_found" = tracing::field::Empty,
            "lancet.workflow.prompt_tokens" = tracing::field::Empty,
            "lancet.workflow.completion_tokens" = tracing::field::Empty,
            "lancet.degraded_mode" = tracing::field::Empty,
        );
        let _ = tracing_opentelemetry::OpenTelemetrySpanExt::set_parent(&parent_span, parent_context);

        let request_process_state_nodes = self.nodes.clone();
        let request_process_state_correlation_id = correlation_id.clone();
        tokio::spawn(
            async move {
                let _ = &deps;
                runner.run_workflow(ctx, cancel, sink).await;
                // Outside every node's own timing (after run_workflow returns), per
                // 06.3.4.1-07 Task 2's spec -- this event's own cost is not attributed to any
                // node's latency measurement.
                emit_request_process_state(
                    &request_process_state_nodes,
                    &request_process_state_correlation_id,
                )
                .await;
            }
            .instrument(parent_span),
        );

        Ok(Response::new(stream))
    }

    /// Traverses the knowledge graph from a seed entity and returns a hop-bounded neighborhood.
    ///
    /// The seed entity is identified by `seed_entity_id` (UUID) **or** by `seed_entity_name`
    /// (case-folded exact name lookup over the full entities table — no match returns
    /// `Status::not_found`). At least one of the two fields must be non-blank. Byte-ceiling
    /// validation on `seed_entity_name` and `relation_type_filter` runs before any table or
    /// scan operations. `hop_depth` must be an explicit value in `[1, effective ceiling]`;
    /// `0` is rejected, never defaulted.
    async fn query_graph(
        &self,
        request: Request<QueryGraphRequest>,
    ) -> Result<Response<QueryGraphResponse>, Status> {
        let req = request.into_inner();

        // ── Input validation (byte-ceiling checks before any DB ops) ─────────────────
        let seed_entity_name = req.seed_entity_name.trim().to_string();
        let seed_entity_id = req.seed_entity_id.trim().to_string();
        let relation_type_filter = req.relation_type_filter.trim().to_string();

        if seed_entity_name.len() > graph::MAX_SEED_ENTITY_NAME_BYTES {
            return Err(Status::invalid_argument(format!(
                "seed_entity_name exceeds {} byte limit",
                graph::MAX_SEED_ENTITY_NAME_BYTES
            )));
        }
        if relation_type_filter.len() > graph::MAX_RELATION_TYPE_FILTER_BYTES {
            return Err(Status::invalid_argument(format!(
                "relation_type_filter exceeds {} byte limit",
                graph::MAX_RELATION_TYPE_FILTER_BYTES
            )));
        }

        // ── Resolve seed entity UUID ─────────────────────────────────────────────────
        let resolved_seed_id: String = if !seed_entity_id.is_empty() {
            let parsed = Uuid::parse_str(&seed_entity_id).map_err(|_| {
                Status::invalid_argument("seed_entity_id must be a valid UUID string")
            })?;
            parsed.to_string()
        } else if !seed_entity_name.is_empty() {
            let entities_table = self
                .database
                .entities_table()
                .await
                .map_err(|e| Status::internal(format!("entities table error: {e}")))?;

            let batches: Vec<RecordBatch> = entities_table
                .query()
                .select(lancedb::query::Select::columns(&["entity_id", "name"]))
                .execute()
                .await
                .map_err(|e| Status::internal(format!("entity name lookup error: {e}")))?
                .try_collect()
                .await
                .map_err(|e| Status::internal(format!("entity name lookup collect error: {e}")))?;

            let folded_query = seed_entity_name.trim().to_lowercase();
            let mut matched_ids: Vec<String> = Vec::new();
            for batch in &batches {
                let id_col = batch
                    .column_by_name("entity_id")
                    .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
                let name_col = batch
                    .column_by_name("name")
                    .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
                if let (Some(id_col), Some(name_col)) = (id_col, name_col) {
                    for i in 0..batch.num_rows() {
                        if id_col.is_null(i) || name_col.is_null(i) {
                            continue;
                        }
                        if name_col.value(i).trim().to_lowercase() == folded_query {
                            matched_ids.push(id_col.value(i).to_string());
                        }
                    }
                }
            }

            if matched_ids.is_empty() {
                return Err(Status::not_found(format!(
                    "no entity found with name '{seed_entity_name}'"
                )));
            }
            matched_ids.sort();
            if matched_ids.len() > 1 {
                tracing::warn!(
                    name = %seed_entity_name,
                    count = matched_ids.len(),
                    "multiple entities matched case-folded name lookup; using lexicographically smallest entity_id"
                );
            }
            matched_ids
                .into_iter()
                .next()
                .expect("matched_ids checked non-empty above")
        } else {
            return Err(Status::invalid_argument(
                "at least one of seed_entity_id or seed_entity_name must be non-blank",
            ));
        };

        // ── Hop-depth clamping ───────────────────────────────────────────────────────
        let effective_depth = graph::clamp_hop_cap_with_ceiling(
            req.hop_depth,
            self.effective_settings.graph.max_hop_cap,
        )
        .map_err(|e| Status::invalid_argument(e.message().to_string()))?;

        // ── Neighborhood fetch + Cypher narrowing ────────────────────────────────────
        let (entities_batch, edges_batch) =
            graph::fetch_neighborhood(&self.database, &resolved_seed_id, effective_depth, true)
                .await
                .map_err(|e| Status::internal(format!("fetch_neighborhood: {:?}", e.kind)))?;

        let (entities_batch, edges_batch) = graph::narrow_via_cypher(
            &entities_batch,
            &edges_batch,
            &resolved_seed_id,
            effective_depth,
        )
        .await;

        // ── Optional relation_type_filter ────────────────────────────────────────────
        let filter_applied = !relation_type_filter.is_empty();
        let edges_batch = if filter_applied {
            let rel_col = edges_batch
                .column_by_name("relation_type")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
            if let Some(rel_col) = rel_col {
                let mask: arrow_array::BooleanArray = (0..edges_batch.num_rows())
                    .map(|i| {
                        Some(
                            !rel_col.is_null(i)
                                && rel_col.value(i) == relation_type_filter.as_str(),
                        )
                    })
                    .collect();
                arrow_select::filter::filter_record_batch(&edges_batch, &mask)
                    .unwrap_or(edges_batch)
            } else {
                edges_batch
            }
        } else {
            edges_batch
        };

        // ── Build QueryGraphResponse ─────────────────────────────────────────────────
        let node_source_batch: RecordBatch = if filter_applied {
            let src_col = edges_batch
                .column_by_name("source_node_id")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
            let tgt_col = edges_batch
                .column_by_name("target_node_id")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());

            let mut endpoint_ids: HashSet<String> = HashSet::new();
            if let (Some(src_col), Some(tgt_col)) = (src_col, tgt_col) {
                for i in 0..edges_batch.num_rows() {
                    if !src_col.is_null(i) {
                        endpoint_ids.insert(src_col.value(i).to_string());
                    }
                    if !tgt_col.is_null(i) {
                        endpoint_ids.insert(tgt_col.value(i).to_string());
                    }
                }
            }

            let entity_id_col_for_mask = entities_batch
                .column_by_name("entity_id")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
            let node_mask: arrow_array::BooleanArray =
                (0..entities_batch.num_rows())
                    .map(|i| {
                        Some(entity_id_col_for_mask.is_some_and(|col| {
                            !col.is_null(i) && endpoint_ids.contains(col.value(i))
                        }))
                    })
                    .collect();
            arrow_select::filter::filter_record_batch(&entities_batch, &node_mask)
                .unwrap_or_else(|_| entities_batch.clone())
        } else {
            entities_batch.clone()
        };

        let entity_id_col = node_source_batch
            .column_by_name("entity_id")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let entity_name_col = node_source_batch
            .column_by_name("name")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let entity_type_col = node_source_batch
            .column_by_name("entity_type")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());

        let mut nodes = Vec::with_capacity(node_source_batch.num_rows());
        if let (Some(id_col), Some(name_col), Some(type_col)) =
            (entity_id_col, entity_name_col, entity_type_col)
        {
            for i in 0..node_source_batch.num_rows() {
                nodes.push(QueryGraphNode {
                    entity_id: if id_col.is_null(i) {
                        String::new()
                    } else {
                        id_col.value(i).to_string()
                    },
                    name: if name_col.is_null(i) {
                        String::new()
                    } else {
                        name_col.value(i).to_string()
                    },
                    entity_type: if type_col.is_null(i) {
                        String::new()
                    } else {
                        type_col.value(i).to_string()
                    },
                });
            }
        }

        let src_col = edges_batch
            .column_by_name("source_node_id")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let tgt_col = edges_batch
            .column_by_name("target_node_id")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let rel_col = edges_batch
            .column_by_name("relation_type")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let weight_col = edges_batch
            .column_by_name("weight")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::Float32Array>());

        let mut edges = Vec::with_capacity(edges_batch.num_rows());
        if let (Some(src), Some(tgt), Some(rel)) = (src_col, tgt_col, rel_col) {
            for i in 0..edges_batch.num_rows() {
                edges.push(QueryGraphEdge {
                    source_entity_id: if src.is_null(i) {
                        String::new()
                    } else {
                        src.value(i).to_string()
                    },
                    target_entity_id: if tgt.is_null(i) {
                        String::new()
                    } else {
                        tgt.value(i).to_string()
                    },
                    relation_type: if rel.is_null(i) {
                        String::new()
                    } else {
                        rel.value(i).to_string()
                    },
                    weight: weight_col
                        .and_then(|w| if w.is_null(i) { None } else { Some(w.value(i)) })
                        .unwrap_or(1.0),
                });
            }
        }

        Ok(Response::new(QueryGraphResponse { nodes, edges }))
    }
}
