//! OpenRouter rerank adapter behind the [`Reranker`] port (06.3.6 D-131).
//!
//! The adapter calls `POST /api/v1/rerank` once per query with the generator's bearer key and
//! `provider.allow_fallbacks = false`, so a reply can only come from the requested model's own
//! provider. It never retries, never falls back to another provider or model, and never spawns a
//! task: the call is awaited in place and the caller bounds it with its own time limit.
//!
//! The reply is untrusted. It must be a permutation of the request documents with finite scores
//! and a `model` that names the requested model; anything else is a malformed reply and is never
//! repaired by guessing. Errors carry the failure class only, so neither the key nor a provider
//! body can reach a log line or a notice through them.

use std::time::{Duration, Instant};

use futures::future::BoxFuture;
use reqwest::{redirect, Client};
use serde::{Deserialize, Serialize};

use crate::client::{read_body_limited_with_limit, BoundedBodyError};
use crate::rerank::{RerankError, RerankOutput, RerankRequest, Reranked, Reranker};

/// The OpenRouter rerank endpoint.
pub const DEFAULT_RERANK_ENDPOINT: &str = "https://openrouter.ai/api/v1/rerank";

/// The rerank model of the quality lever (D-131).
pub const DEFAULT_RERANK_MODEL: &str = "voyageai/rerank-2.5-lite";

/// The largest rerank reply the adapter reads, in bytes.
///
/// The reply echoes every document (up to 32 chunks), so it is about the size of the request;
/// 1 MiB holds 32 maximal chunks with margin (RESEARCH A4). The 256 KiB default of the other
/// provider calls would refuse a valid reply for a full candidate list; raising this admits a
/// larger body from the provider before the read is cut off.
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
        let endpoint = endpoint.into();
        let model = model.into();
        if endpoint.trim().is_empty() || model.trim().is_empty() || timeout.is_zero() {
            return Err(RerankError::invalid_request());
        }
        Ok(Self {
            endpoint,
            model,
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
///
/// `Debug` is written by hand and omits the key.
#[derive(Clone)]
pub struct OpenRouterReranker {
    http: Client,
    api_key: String,
    config: RerankConfig,
}

impl std::fmt::Debug for OpenRouterReranker {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("OpenRouterReranker")
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

#[derive(Serialize)]
struct ProviderPreferences {
    allow_fallbacks: bool,
}

#[derive(Serialize)]
struct RerankBody<'a> {
    model: &'a str,
    query: &'a str,
    documents: Vec<&'a str>,
    top_n: usize,
    provider: ProviderPreferences,
}

#[derive(Deserialize)]
struct ReplyResult {
    index: usize,
    relevance_score: f64,
}

#[derive(Deserialize)]
struct Reply {
    model: Option<String>,
    results: Vec<ReplyResult>,
    /// Read loosely: a malformed `usage` loses the cost, never the ranking.
    usage: Option<serde_json::Value>,
}

impl OpenRouterReranker {
    /// Builds the adapter.
    ///
    /// # Errors
    ///
    /// Returns an invalid-request [`RerankError`] for a blank key or when the HTTP client cannot
    /// be built.
    pub fn new(api_key: impl Into<String>, config: RerankConfig) -> Result<Self, RerankError> {
        let api_key = api_key.into();
        if api_key.trim().is_empty() {
            return Err(RerankError::invalid_request());
        }
        // No redirects: a bearer-authenticated call is never re-sent somewhere the endpoint
        // did not name.
        let http = Client::builder()
            .timeout(config.timeout)
            .redirect(redirect::Policy::none())
            .build()
            .map_err(|_| RerankError::invalid_request())?;
        Ok(Self {
            http,
            api_key,
            config,
        })
    }

    async fn call(&self, request: RerankRequest<'_>) -> Result<RerankOutput, RerankError> {
        let count = request.candidates.len();
        if count == 0 {
            return Ok(RerankOutput {
                ranked: Vec::new(),
                cost_credits: None,
            });
        }
        if request.query.trim().is_empty() {
            return Err(RerankError::invalid_request());
        }
        let started = Instant::now();
        let result = self.exchange(request).await;
        let latency_ms = started.elapsed().as_secs_f64() * 1000.0;
        match &result {
            Ok(output) => tracing::info!(
                n = count,
                latency_ms,
                cost_reported = output.cost_credits.is_some(),
                "rerank_call"
            ),
            Err(error) => tracing::warn!(
                n = count,
                latency_ms,
                cost_reported = false,
                error_class = %error.class(),
                "rerank_call"
            ),
        }
        result
    }

    async fn exchange(&self, request: RerankRequest<'_>) -> Result<RerankOutput, RerankError> {
        let count = request.candidates.len();
        let body = RerankBody {
            model: self.config.model(),
            query: request.query,
            documents: request
                .candidates
                .iter()
                .map(|fused| fused.candidate.content.as_str())
                .collect(),
            top_n: count,
            provider: ProviderPreferences {
                allow_fallbacks: false,
            },
        };
        let response = self
            .http
            .post(self.config.endpoint())
            .bearer_auth(&self.api_key)
            .json(&body)
            .send()
            .await
            .map_err(|error| {
                // The transport error's text can name the URL and is never copied.
                if error.is_timeout() {
                    RerankError::timeout()
                } else {
                    RerankError::transport()
                }
            })?;
        let status = response.status();
        if !status.is_success() {
            return Err(RerankError::status(status.as_u16()));
        }
        let bytes = read_body_limited_with_limit(response, RERANK_MAX_BODY_BYTES)
            .await
            .map_err(|error| match error {
                BoundedBodyError::TooLarge => RerankError::malformed(),
                BoundedBodyError::Read(_) => RerankError::transport(),
            })?;
        let reply: Reply = serde_json::from_slice(&bytes).map_err(|_| RerankError::malformed())?;
        validate_reply(reply, count, self.config.model())
    }
}

impl Reranker for OpenRouterReranker {
    fn rerank<'a>(
        &'a self,
        request: RerankRequest<'a>,
    ) -> BoxFuture<'a, Result<RerankOutput, RerankError>> {
        Box::pin(self.call(request))
    }
}

/// Whether the reply's `model` names the requested model.
///
/// OpenRouter echoes the bare model name (`rerank-2.5-lite`) for a vendor-prefixed request
/// (`voyageai/rerank-2.5-lite`), so the reply is accepted when it starts with the requested slug
/// or with the name after the vendor prefix (D-186). Any other model, including a missing one,
/// means the call was served by something else.
fn reply_model_matches(requested: &str, reply: &str) -> bool {
    let bare = requested
        .split_once('/')
        .map_or(requested, |(_, name)| name);
    reply.starts_with(requested) || (!bare.is_empty() && reply.starts_with(bare))
}

/// Checks the untrusted reply against the request and orders it by `(score desc, index asc)`.
fn validate_reply(
    reply: Reply,
    count: usize,
    requested: &str,
) -> Result<RerankOutput, RerankError> {
    let model_ok = reply
        .model
        .as_deref()
        .is_some_and(|model| reply_model_matches(requested, model));
    if !model_ok || reply.results.len() != count {
        return Err(RerankError::malformed());
    }
    let mut seen = vec![false; count];
    let mut ranked = Vec::with_capacity(count);
    for result in reply.results {
        let slot = seen
            .get_mut(result.index)
            .ok_or_else(RerankError::malformed)?;
        if *slot || !result.relevance_score.is_finite() {
            return Err(RerankError::malformed());
        }
        *slot = true;
        ranked.push(Reranked {
            index: result.index,
            score: result.relevance_score,
        });
    }
    // Scores are finite here, so `partial_cmp` never fails and -0.0 equals 0.0; equal scores
    // fall to the lower index whatever order the provider listed them in.
    ranked.sort_by(|left, right| {
        right
            .score
            .partial_cmp(&left.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(left.index.cmp(&right.index))
    });
    let cost_credits = reply
        .usage
        .as_ref()
        .and_then(|usage| usage.get("cost"))
        .and_then(serde_json::Value::as_f64)
        .filter(|cost| cost.is_finite() && *cost >= 0.0);
    Ok(RerankOutput {
        ranked,
        cost_credits,
    })
}
