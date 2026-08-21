use std::{sync::Arc, time::Duration};

use dashmap::DashMap;
use tokio::sync::{mpsc, watch};
use tonic::transport::Server;

use engine::client::{OpenRouterClient, OpenRouterEmbeddingConfig};
use engine::config::{load_settings, EffectiveRagSettings};
use engine::db::DatabaseManager;
use engine::generation;
use engine::graph;
use engine::ingest::{read_staged_jobs, spawn_worker, IngestionStatus, QUEUE_CAPACITY};
use engine::pb::lancet::v1::lancet_service_server::LancetServiceServer;
use engine::rerank;
use engine::retrieval::Bm25Index;
use engine::service::LancetServiceImpl;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();
    let settings = load_settings()?;
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings)
        .map_err(|err| format!("invalid RAG configuration: {err}"))?;
    let database = DatabaseManager::initialize(&settings.engine.lancedb_path).await?;
    let nodes = database.nodes_table().await?;
    let bm25_index = Bm25Index::from_table(&nodes, effective_settings.retrieval.bm25.clone())
        .await
        .map_err(|error| format!("initial BM25 snapshot build failed: {error}"))?;
    tracing::info!(document_count = bm25_index.len(), "BM25 snapshot built");
    let table = database.staged_documents_table().await?;
    let api_key = std::env::var("OPENROUTER_API_KEY")
        .map_err(|_| "OPENROUTER_API_KEY environment variable is not set")?;
    if api_key.trim().is_empty() {
        return Err("OPENROUTER_API_KEY environment variable must not be empty or blank".into());
    }
    let embedding_config = OpenRouterEmbeddingConfig::new(
        effective_settings.embedding_model.clone(),
        effective_settings.embedding_endpoint.clone(),
    )?;
    let embedder = Arc::new(OpenRouterClient::new_with_config(
        api_key.clone(),
        embedding_config,
    )?);
    let extraction_config = generation::openrouter::OpenRouterGenerationConfig::new(
        effective_settings.generation_model.clone(),
        effective_settings.chat_endpoint.clone(),
        effective_settings.model_metadata_endpoint.clone(),
        Duration::from_secs(effective_settings.generation_timeout_secs),
        0.0,
        1.0,
        768,
        768,
    )?;
    let extraction_generator: Arc<dyn graph::extraction::ExtractionGenerator> = Arc::new(
        graph::extraction::OpenRouterExtractionGenerator::new_with_config(
            api_key.clone(),
            extraction_config,
        )?,
    );

    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        embedder.clone(),
        extraction_generator.clone(),
        shutdown_rx,
    );

    let staged_jobs = read_staged_jobs(&database).await?;
    for job in staged_jobs {
        statuses.insert(job.document_id.clone(), IngestionStatus::queued());
        sender
            .send(job)
            .await
            .map_err(|_| "worker exited during replay send")?;
    }

    let generation_config =
        generation::openrouter::OpenRouterGenerationConfig::from_effective_limits(
            effective_settings.generation_model.clone(),
            effective_settings.chat_endpoint.clone(),
            effective_settings.model_metadata_endpoint.clone(),
            Duration::from_secs(effective_settings.generation_timeout_secs),
            effective_settings.temperature,
            effective_settings.top_p,
            effective_settings.grounding_limits_arc(),
        )?;
    let generator: Arc<dyn generation::Generator> = Arc::new(
        generation::openrouter::OpenRouterGenerator::new_with_config(api_key, generation_config)?,
    );

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(Arc::new(bm25_index))),
        effective_settings,
        generator,
        embedder: embedder.clone(),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        database: database.clone(),
    };

    let addr = settings.engine.grpc_addr.parse()?;
    tracing::info!(%addr, "Rust RAG Engine serving");
    Server::builder()
        .add_service(LancetServiceServer::new(service))
        .serve_with_shutdown(addr, async {
            let _ = tokio::signal::ctrl_c().await;
            let _ = shutdown_tx.send(true);
        })
        .await?;
    worker.await?;
    Ok(())
}
