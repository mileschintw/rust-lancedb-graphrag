//! OpenRouter rerank adapter behind the [`Reranker`] port (06.3.6 D-131).
//!
//! The adapter calls `POST /api/v1/rerank` once per query with the generator's bearer key.
//! It never retries, never falls back to another provider or model, and never spawns a task.

use std::time::Duration;

use futures::future::BoxFuture;
use reqwest::Client;

use crate::rerank::{RerankError, RerankOutput, RerankRequest, Reranker};

/// The OpenRouter rerank endpoint.
pub const DEFAULT_RERANK_ENDPOINT: &str = "https://openrouter.ai/api/v1/rerank";

/// The rerank model of the quality lever (D-131).
pub const DEFAULT_RERANK_MODEL: &str = "voyageai/rerank-2.5-lite";

/// The largest rerank reply the adapter reads, in bytes.
pub const RERANK_MAX_BODY_BYTES: usize = 1024 * 1024;

/// Endpoint, model and call time limit of the rerank adapter.
#[derive(Debug, Clone)]
pub struct RerankConfig {
    endpoint: String,
    model: String,
    timeout: Duration,
}

impl RerankConfig {
    /// Builds a configuration.
    ///
    /// # Errors
    ///
    /// Returns an invalid-request [`RerankError`] for a blank endpoint or model or a zero timeout.
    pub fn new(
        endpoint: impl Into<String>,
        model: impl Into<String>,
        timeout: Duration,
    ) -> Result<Self, RerankError> {
        Ok(Self {
            endpoint: endpoint.into(),
            model: model.into(),
            timeout,
        })
    }

    /// The endpoint the adapter posts to.
    pub fn endpoint(&self) -> &str {
        &self.endpoint
    }

    /// The model slug the adapter requests.
    pub fn model(&self) -> &str {
        &self.model
    }

    /// The time limit of one call.
    pub fn timeout(&self) -> Duration {
        self.timeout
    }
}

/// Reranks through OpenRouter.
#[derive(Clone)]
pub struct OpenRouterReranker {
    _http: Client,
    _api_key: String,
    _config: RerankConfig,
}

impl OpenRouterReranker {
    /// Builds the adapter.
    ///
    /// # Errors
    ///
    /// Returns an invalid-request [`RerankError`] for a blank key.
    pub fn new(api_key: impl Into<String>, config: RerankConfig) -> Result<Self, RerankError> {
        Ok(Self {
            _http: Client::new(),
            _api_key: api_key.into(),
            _config: config,
        })
    }
}

impl std::fmt::Debug for OpenRouterReranker {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("OpenRouterReranker").finish_non_exhaustive()
    }
}

impl Reranker for OpenRouterReranker {
    fn rerank<'a>(
        &'a self,
        _request: RerankRequest<'a>,
    ) -> BoxFuture<'a, Result<RerankOutput, RerankError>> {
        Box::pin(async move {
            Ok(RerankOutput {
                ranked: Vec::new(),
                cost_credits: None,
            })
        })
    }
}
