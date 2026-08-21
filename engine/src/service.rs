//! gRPC service implementation for Lancet, covering ingestion, status, graph query, and RAG execution.
//!
//! Owns `LancetServiceImpl` which implements the `LancetService` gRPC definition,
//! along with the internal workflow adapters (`ProductionEmbeddingPort`, `ProductionGraphQueryPort`,
//! `ProductionDenseRetrievalPort`, `ProductionBm25RetrievalPort`), graph augmentation helpers,
//! and stream cancellation utilities.

use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
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

/// Lancet gRPC service state holding database handles, background ingestion queue, and RAG components.
#[derive(Clone)]
pub struct LancetServiceImpl {
    pub table: Table,
    pub statuses: Arc<DashMap<String, IngestionStatus>>,
    pub queue: mpsc::Sender<IngestionJob>,
    pub nodes: Table,
    pub bm25_index: workflow::ports::Bm25IndexStore,
    pub effective_settings: EffectiveRagSettings,
    pub generator: Arc<dyn generation::Generator>,
    pub embedder: Arc<dyn EmbeddingProvider>,
    pub reranker: Arc<dyn rerank::Reranker>,
    pub database: DatabaseManager,
}

impl LancetServiceImpl {
    /// Persists a raw ingestion job to the staged documents table.
    pub async fn persist_raw(&self, job: &IngestionJob) -> Result<(), Status> {
        persist_raw_with_boundary(&self.table, job, &LanceDbReplacementMutationBoundary)
            .await
            .map_err(internal)
    }

    /// Assembles the production workflow runner and dependencies for RAG execution.
    pub fn build_production_workflow(
        &self,
    ) -> (workflow::WorkflowRunner, workflow::WorkflowDependencies) {
        let embedder_adapter: Arc<dyn workflow::node::QueryEmbeddingPort> =
            Arc::new(ProductionEmbeddingPort {
                embedder: Arc::clone(&self.embedder),
            });
        let graph_adapter: Arc<dyn workflow::ports::GraphQueryPort> =
            Arc::new(ProductionGraphQueryPort {
                database: self.database.clone(),
                graph_settings: self.effective_settings.graph.clone(),
            });
        let dense_adapter: Arc<dyn workflow::ports::DenseRetrievalPort> =
            Arc::new(ProductionDenseRetrievalPort {
                nodes: self.nodes.clone(),
                retrieval_settings: self.effective_settings.retrieval.clone(),
            });
        let bm25_adapter: Arc<dyn workflow::ports::Bm25RetrievalPort> =
            Arc::new(ProductionBm25RetrievalPort {
                bm25_index: Arc::clone(&self.bm25_index),
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
                self.effective_settings.index_generation.clone(),
                self.effective_settings.embedding_model.clone(),
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
            workflow::nodes::GenerateAnswerNode::new(deps.generator.clone()).with_settings(
                *self.effective_settings.grounding_limits(),
                self.effective_settings.citation_excerpt_max_chars,
                self.effective_settings.retrieval.graph_weight,
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

/// Attempts to augment a query with knowledge graph facts from the nearest entity match.
pub async fn attempt_graph_augmentation(
    database: &DatabaseManager,
    query_embedding: &[f32],
    settings: &GraphSettings,
) -> GraphAugmentationOutcome {
    let entities_table = match database.entities_table().await {
        Ok(t) => t,
        Err(e) => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: format!("entities table error: {e}"),
            }
        }
    };

    let nearest = match entities_table.query().nearest_to(query_embedding.to_vec()) {
        Ok(q) => q,
        Err(e) => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: format!("nearest_to error: {e}"),
            }
        }
    };

    let batches: Vec<RecordBatch> = match nearest
        .column("name_vector")
        .select(lancedb::query::Select::columns(&[
            "entity_id",
            "name",
            "entity_type",
            "_distance",
        ]))
        .limit(1)
        .execute()
        .await
    {
        Ok(s) => match s.try_collect().await {
            Ok(b) => b,
            Err(e) => {
                return GraphAugmentationOutcome::AttemptedAndFailed {
                    reason: format!("execute collect error: {e}"),
                }
            }
        },
        Err(e) => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: format!("execute error: {e}"),
            }
        }
    };

    if batches.is_empty() || batches[0].num_rows() == 0 {
        return GraphAugmentationOutcome::NoMatchFound;
    }

    let seed_batch = &batches[0];
    let distance_col = match seed_batch
        .column_by_name("_distance")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::Float32Array>())
    {
        Some(c) => c,
        None => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: "missing _distance column".into(),
            }
        }
    };
    let distance = distance_col.value(0) as f64;
    let seed_match_score = retrieval::dense::dense_score(distance);

    if seed_match_score < settings.seed_match_min_score {
        return GraphAugmentationOutcome::NoMatchFound;
    }

    let seed_id_col = match seed_batch
        .column_by_name("entity_id")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: "missing entity_id column".into(),
            }
        }
    };
    let matched_entity_id = seed_id_col.value(0).to_string();

    let (entities_batch, edges_batch) =
        match graph::fetch_neighborhood(database, &matched_entity_id, 1, true).await {
            Ok(res) => res,
            Err(e) => {
                return GraphAugmentationOutcome::AttemptedAndFailed {
                    reason: format!("fetch_neighborhood kind: {:?}", e.kind),
                }
            }
        };

    let (entities_batch, edges_batch) =
        graph::narrow_via_cypher(&entities_batch, &edges_batch, &matched_entity_id, 1).await;

    let entity_id_col = match entities_batch
        .column_by_name("entity_id")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };
    let name_col = match entities_batch
        .column_by_name("name")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };

    let mut name_map = HashMap::new();
    for i in 0..entities_batch.num_rows() {
        if !entity_id_col.is_null(i) && !name_col.is_null(i) {
            name_map.insert(
                entity_id_col.value(i).to_string(),
                name_col.value(i).to_string(),
            );
        }
    }

    let source_col = match edges_batch
        .column_by_name("source_node_id")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };
    let target_col = match edges_batch
        .column_by_name("target_node_id")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };
    let rel_col = match edges_batch
        .column_by_name("relation_type")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };
    let weight_col = match edges_batch
        .column_by_name("weight")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::Float32Array>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };

    let mut facts = Vec::new();
    for i in 0..edges_batch.num_rows() {
        if !source_col.is_null(i)
            && !target_col.is_null(i)
            && !rel_col.is_null(i)
            && !weight_col.is_null(i)
        {
            let src_id = source_col.value(i);
            let tgt_id = target_col.value(i);
            let rel = rel_col.value(i);
            let weight = weight_col.value(i) as f64;

            if let (Some(src_name), Some(tgt_name)) = (name_map.get(src_id), name_map.get(tgt_id)) {
                let score = seed_match_score * weight;
                facts.push(graph::context_strategy::GraphFact::new(
                    src_name, rel, tgt_name, None, score,
                ));
            }
        }
    }

    GraphAugmentationOutcome::Succeeded { facts }
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
        Box::pin(async move {
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
        })
    }
}

/// Production adapter implementing `GraphQueryPort` backed by LanceDB entity tables.
pub struct ProductionGraphQueryPort {
    pub database: DatabaseManager,
    pub graph_settings: GraphSettings,
}

impl workflow::ports::GraphQueryPort for ProductionGraphQueryPort {
    fn query_graph<'a>(
        &'a self,
        query_embedding: &'a [f32],
        cancel: &'a tokio_util::sync::CancellationToken,
    ) -> workflow::node::BoxFuture<'a, Result<Vec<prompt::GraphFactBlock>, workflow::node::NodeError>>
    {
        Box::pin(async move {
            if cancel.is_cancelled() {
                return Err(workflow::node::NodeError::cancelled());
            }
            let graph_outcome =
                attempt_graph_augmentation(&self.database, query_embedding, &self.graph_settings)
                    .await;

            let tag = match &graph_outcome {
                GraphAugmentationOutcome::Succeeded { .. } => "succeeded",
                GraphAugmentationOutcome::NoMatchFound => "no_match_found",
                GraphAugmentationOutcome::AttemptedAndFailed { .. } => "attempted_and_failed",
            };
            tracing::Span::current().record("graph_augmentation", tag);

            let facts: Vec<prompt::GraphFactBlock> = match graph_outcome {
                GraphAugmentationOutcome::Succeeded { facts } => facts
                    .into_iter()
                    .map(|fact| prompt::GraphFactBlock { fact })
                    .collect(),
                GraphAugmentationOutcome::NoMatchFound => vec![],
                GraphAugmentationOutcome::AttemptedAndFailed { reason } => {
                    return Err(workflow::node::NodeError::new(
                        v1::NodeErrorKind::GraphFailed,
                        format!("graph augmentation failed: {reason}"),
                    ));
                }
            };
            Ok(facts)
        })
    }
}

/// Production adapter implementing `DenseRetrievalPort` backed by LanceDB nodes table.
pub struct ProductionDenseRetrievalPort {
    pub nodes: Table,
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
        Box::pin(async move {
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
            let dense_retriever = DenseRetriever::new(self.nodes.clone());
            dense_retriever
                .query(query_embedding, &query_req, &self.retrieval_settings)
                .await
                .map_err(|err| {
                    workflow::node::NodeError::new(
                        v1::NodeErrorKind::RetrievalFailed,
                        format!("dense retrieval failure: {}", err.message()),
                    )
                })
        })
    }
}

/// Production adapter implementing `Bm25RetrievalPort` backed by the in-memory BM25 index snapshot.
pub struct ProductionBm25RetrievalPort {
    pub bm25_index: workflow::ports::Bm25IndexStore,
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
        Box::pin(async move {
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
            let index_snapshot = {
                let guard = self.bm25_index.read().await;
                Arc::clone(&*guard)
            };
            index_snapshot
                .retrieve(&query_req, &self.retrieval_settings)
                .await
                .map_err(|err| {
                    workflow::node::NodeError::new(
                        v1::NodeErrorKind::RetrievalFailed,
                        err.to_string(),
                    )
                })
        })
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
        let mut stream = request.into_inner();
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
        if document_id.is_empty() {
            return Err(Status::invalid_argument("empty ingestion stream"));
        }
        validate_document_id(&document_id)?;
        let permit = self
            .queue
            .clone()
            .try_reserve_owned()
            .map_err(|_| Status::resource_exhausted("ingestion queue is full"))?;
        let job = IngestionJob {
            document_id: document_id.clone(),
            filename,
            raw_data: raw,
            metadata,
            chunk_settings: parsed_settings.expect("parsed settings present for non-empty stream"),
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
        let _disable_graph_context = req.disable_graph_context.unwrap_or(false);

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

        let ctx = workflow::WorkflowContext::new(session_id.clone(), correlation_id.clone(), &req);
        let (runner, deps) = self.build_production_workflow();

        let parent_span = tracing::info_span!(
            "query_rag",
            graph_augmentation = tracing::field::Empty,
            session_id = %session_id,
            correlation_id = %correlation_id,
        );

        tokio::spawn(
            async move {
                let _ = &deps;
                runner.run_workflow(ctx, cancel, sink).await;
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
