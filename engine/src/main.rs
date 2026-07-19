use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use arrow_array::{BinaryArray, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};
use dashmap::DashMap;
use lancedb::Table;
use serde::Deserialize;
use tokio::{sync::mpsc, task::JoinHandle};
use tonic::{transport::Server, Request, Response, Status};

pub mod lancet {
    pub mod v1 {
        include!("pb/lancet/v1/lancet.v1.rs");
    }
}

use lancet::v1::lancet_service_server::{LancetService, LancetServiceServer};
use lancet::v1::{
    GetIngestionStatusRequest, GetIngestionStatusResponse, IngestDocumentRequest,
    IngestDocumentResponse, PingRequest, PingResponse, QueryGraphRequest, QueryGraphResponse,
    QueryRagRequest, QueryRagResponse,
};

const MAX_DOCUMENT_BYTES: usize = 10 << 20;
const QUEUE_CAPACITY: usize = 100;

#[derive(Debug, Clone, Deserialize)]
struct Settings {
    engine: EngineSettings,
}
#[derive(Debug, Clone, Deserialize)]
struct EngineSettings {
    grpc_addr: String,
    lancedb_path: String,
}

fn load_settings() -> Result<Settings, config::ConfigError> {
    let base = if std::path::Path::new("../config/config.toml").exists() {
        "../config/config"
    } else {
        "config/config"
    };
    let mut builder = config::Config::builder().add_source(config::File::with_name(base));
    if let Ok(environment) = std::env::var("LANCET_ENV") {
        if !environment.is_empty() {
            builder = builder.add_source(config::File::with_name(&format!("{base}.{environment}")));
        }
    }
    builder
        .add_source(config::Environment::with_prefix("LANCET").separator("__"))
        .build()?
        .try_deserialize()
}

#[derive(Debug, Clone)]
struct IngestionStatus {
    status: String,
    chunk_count: i32,
    error_message: String,
}
impl IngestionStatus {
    fn queued() -> Self {
        Self {
            status: "queued".into(),
            chunk_count: 0,
            error_message: String::new(),
        }
    }
}

#[derive(Debug)]
struct IngestionJob {
    document_id: String,
    byte_count: usize,
}

#[derive(Clone)]
pub struct LancetServiceImpl {
    table: Table,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    queue: mpsc::Sender<IngestionJob>,
}

impl LancetServiceImpl {
    async fn persist_raw(
        &self,
        document_id: &str,
        filename: &str,
        data: &[u8],
    ) -> Result<(), Status> {
        let schema = self.table.schema().await.map_err(internal)?;
        let batch = RecordBatch::try_new(
            schema,
            vec![
                Arc::new(StringArray::from(vec![document_id])),
                Arc::new(StringArray::from(vec![filename])),
                Arc::new(BinaryArray::from_vec(vec![data])),
            ],
        )
        .map_err(internal)?;
        self.table.add(batch).execute().await.map_err(internal)?;
        Ok(())
    }
}

fn internal(err: impl std::fmt::Display) -> Status {
    Status::internal(err.to_string())
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
        let mut raw = Vec::new();
        while let Some(message) = stream.message().await? {
            if document_id.is_empty() {
                document_id = message.document_id.clone();
                filename = message.filename.clone();
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
        let permit = self
            .queue
            .clone()
            .try_reserve_owned()
            .map_err(|_| Status::resource_exhausted("ingestion queue is full"))?;
        self.persist_raw(&document_id, &filename, &raw).await?;
        self.statuses
            .insert(document_id.clone(), IngestionStatus::queued());
        permit.send(IngestionJob {
            document_id: document_id.clone(),
            byte_count: raw.len(),
        });
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
        let state = self
            .statuses
            .get(&id)
            .ok_or_else(|| Status::not_found("document status not found"))?;
        Ok(Response::new(GetIngestionStatusResponse {
            document_id: id,
            status: state.status.clone(),
            chunk_count: state.chunk_count,
            error_message: state.error_message.clone(),
        }))
    }

    async fn query_rag(
        &self,
        request: Request<QueryRagRequest>,
    ) -> Result<Response<QueryRagResponse>, Status> {
        let req = request.into_inner();
        Ok(Response::new(QueryRagResponse {
            answer: format!("Placeholder answer for: {}", req.query),
            citations: vec![],
            session_id: req.session_id,
        }))
    }

    async fn query_graph(
        &self,
        _request: Request<QueryGraphRequest>,
    ) -> Result<Response<QueryGraphResponse>, Status> {
        Ok(Response::new(QueryGraphResponse {
            result_json: r#"{"status":"scaffolding"}"#.into(),
        }))
    }
}

fn spawn_worker(
    mut receiver: mpsc::Receiver<IngestionJob>,
    statuses: Arc<DashMap<String, IngestionStatus>>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        while let Some(job) = receiver.recv().await {
            statuses.insert(
                job.document_id.clone(),
                IngestionStatus {
                    status: "processing".into(),
                    chunk_count: 0,
                    error_message: String::new(),
                },
            );
            let span = tracing::info_span!("index_document", document_id = %job.document_id, bytes = job.byte_count);
            let _guard = span.enter();
            tracing::info!("mock indexing started");
            let chunks = ((job.byte_count.max(1) + 511) / 512) as i32;
            statuses.insert(
                job.document_id,
                IngestionStatus {
                    status: "completed".into(),
                    chunk_count: chunks,
                    error_message: String::new(),
                },
            );
            tracing::info!(chunk_count = chunks, "mock indexing completed");
        }
    })
}

async fn open_documents_table(path: &str) -> Result<Table, Box<dyn std::error::Error>> {
    let connection = lancedb::connect(path).execute().await?;
    match connection.open_table("documents").execute().await {
        Ok(table) => Ok(table),
        Err(_) => {
            let schema = Arc::new(Schema::new(vec![
                Field::new("document_id", DataType::Utf8, false),
                Field::new("filename", DataType::Utf8, false),
                Field::new("raw_data", DataType::Binary, false),
            ]));
            Ok(connection
                .create_empty_table("documents", schema)
                .execute()
                .await?)
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();
    let settings = load_settings()?;
    let table = open_documents_table(&settings.engine.lancedb_path).await?;
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let worker = spawn_worker(receiver, statuses.clone());
    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
    };
    let addr = settings.engine.grpc_addr.parse()?;
    tracing::info!(%addr, "Rust RAG Engine serving");
    Server::builder()
        .add_service(LancetServiceServer::new(service))
        .serve_with_shutdown(addr, async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    worker.await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn worker_completes_jobs_and_records_mock_chunks() {
        let statuses = Arc::new(DashMap::new());
        let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
        let worker = spawn_worker(receiver, statuses.clone());
        sender
            .send(IngestionJob {
                document_id: "doc-1".into(),
                byte_count: 1025,
            })
            .await
            .unwrap();
        drop(sender);
        worker.await.unwrap();
        let state = statuses.get("doc-1").unwrap();
        assert_eq!(state.status, "completed");
        assert_eq!(state.chunk_count, 3);
    }

    #[tokio::test]
    async fn bounded_queue_rejects_work_when_full() {
        let (sender, _receiver) = mpsc::channel(1);
        sender
            .try_send(IngestionJob {
                document_id: "one".into(),
                byte_count: 1,
            })
            .unwrap();
        assert!(sender
            .try_send(IngestionJob {
                document_id: "two".into(),
                byte_count: 1
            })
            .is_err());
    }
}
