use std::time::{SystemTime, UNIX_EPOCH};
use tonic::{transport::Server, Request, Response, Status};

pub mod lancet {
    pub mod v1 {
        include!("pb/lancet/v1/lancet.v1.rs");
    }
}

use lancet::v1::lancet_service_server::{LancetService, LancetServiceServer};
use lancet::v1::{
    PingRequest, PingResponse,
    IngestDocumentRequest, IngestDocumentResponse,
    QueryRagRequest, QueryRagResponse,
    QueryGraphRequest, QueryGraphResponse,
};

#[derive(Debug, Default)]
pub struct LancetServiceImpl {}

#[tonic::async_trait]
impl LancetService for LancetServiceImpl {
    async fn ping(&self, request: Request<PingRequest>) -> Result<Response<PingResponse>, Status> {
        let req = request.into_inner();
        tracing::info!("Received Ping request with value: {}", req.value);

        let start = SystemTime::now();
        let since_the_epoch = start
            .duration_since(UNIX_EPOCH)
            .expect("Time went backwards")
            .as_millis() as i64;

        let response = PingResponse {
            value: format!("pong: {}", req.value),
            timestamp: since_the_epoch,
        };

        Ok(Response::new(response))
    }

    async fn ingest_document(
        &self,
        _request: Request<tonic::Streaming<IngestDocumentRequest>>,
    ) -> Result<Response<IngestDocumentResponse>, Status> {
        tracing::info!("Received IngestDocument stream request");
        // Placeholder implementation for Phase 1
        let response = IngestDocumentResponse {
            document_id: "placeholder-id".to_string(),
            success: true,
            message: "Ingestion scaffolding received".to_string(),
        };
        Ok(Response::new(response))
    }

    async fn query_rag(
        &self,
        request: Request<QueryRagRequest>,
    ) -> Result<Response<QueryRagResponse>, Status> {
        let req = request.into_inner();
        tracing::info!("Received QueryRAG request: {}", req.query);
        // Placeholder implementation for Phase 1
        let response = QueryRagResponse {
            answer: format!("Placeholder answer for: {}", req.query),
            citations: vec!["citation-1".to_string()],
            session_id: req.session_id,
        };
        Ok(Response::new(response))
    }

    async fn query_graph(
        &self,
        request: Request<QueryGraphRequest>,
    ) -> Result<Response<QueryGraphResponse>, Status> {
        let req = request.into_inner();
        tracing::info!("Received QueryGraph request: {}", req.query);
        // Placeholder implementation for Phase 1
        let response = QueryGraphResponse {
            result_json: r#"{"status": "scaffolding"}"#.to_string(),
        };
        Ok(Response::new(response))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();

    let addr = "[::1]:50051".parse()?;
    let service = LancetServiceImpl::default();

    tracing::info!("Rust RAG Engine serving on {}", addr);

    Server::builder()
        .add_service(LancetServiceServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}
