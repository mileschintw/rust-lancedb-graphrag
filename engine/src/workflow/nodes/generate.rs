use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use tracing::Instrument;

use super::super::{
    node::{BoxFuture, Node, NodeError, NodeKind},
    WorkflowContext,
};
use crate::generation::citations::{self, Resolution};
use crate::generation::{GenerationErrorKind, GenerationRequest, Generator, GroundingLimits};
use crate::pb::lancet::v1::NodeErrorKind;
use crate::prompt::{resolve_citations, resolve_citations_with_max_chars};

pub struct GenerateAnswerNode {
    generator: Option<Arc<dyn Generator>>,
    grounding_limits: Option<GroundingLimits>,
    citation_excerpt_max_chars: Option<usize>,
    graph_weight: f64,
    citation_repair_enabled: bool,
}

impl GenerateAnswerNode {
    pub fn new(generator: Option<Arc<dyn Generator>>) -> Self {
        Self {
            generator,
            grounding_limits: None,
            citation_excerpt_max_chars: None,
            graph_weight: 1.0,
            citation_repair_enabled: true,
        }
    }

    pub fn with_settings(
        mut self,
        grounding_limits: GroundingLimits,
        citation_excerpt_max_chars: usize,
        graph_weight: f64,
    ) -> Self {
        self.grounding_limits = Some(grounding_limits);
        self.citation_excerpt_max_chars = Some(citation_excerpt_max_chars);
        self.graph_weight = graph_weight;
        self
    }

    /// Sets whether the local citation-repair pass (D-14) runs on unresolved citation
    /// markers. Defaults to true, matching the `citation_repair_enabled` configuration
    /// default (D-84); callers that need the pre-D-14 fail-closed behavior opt out
    /// explicitly.
    pub fn with_citation_repair_enabled(mut self, citation_repair_enabled: bool) -> Self {
        self.citation_repair_enabled = citation_repair_enabled;
        self
    }
}

impl Default for GenerateAnswerNode {
    fn default() -> Self {
        Self::new(None)
    }
}

impl Node for GenerateAnswerNode {
    fn kind(&self) -> NodeKind {
        NodeKind::GenerateAnswer
    }

    fn prepare<'a>(&'a self) -> BoxFuture<'a, Result<(), NodeError>> {
        Box::pin(async move {
            let Some(generator) = &self.generator else {
                return Ok(());
            };

            generator.prepare().await.map_err(|err| {
                let kind = match err.kind {
                    GenerationErrorKind::Cancelled => NodeErrorKind::Cancelled,
                    GenerationErrorKind::Timeout => NodeErrorKind::Timeout,
                    _ => NodeErrorKind::LlmGenerationFailed,
                };
                NodeError::new(kind, err.message()).with_retryable(false)
            })
        })
    }

    fn run<'a>(
        &'a self,
        ctx: &'a mut WorkflowContext,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<(), NodeError>> {
        Box::pin(async move {
            if cancel.is_cancelled() {
                return Err(NodeError::cancelled().with_context(
                    Some(ctx.session_id.clone()),
                    Some(ctx.trace_id.clone()),
                ));
            }

            let generator = match &self.generator {
                Some(g) => g,
                None => {
                    return Err(NodeError::new(
                        NodeErrorKind::LlmGenerationFailed,
                        "No generator configured for GenerateAnswer node",
                    ));
                }
            };

            let mut req =
                GenerationRequest::new(ctx.original_query.clone(), ctx.evidence_blocks.clone());
            req.graph_facts = ctx.graph_facts.clone();
            req.graph_weight = self.graph_weight;
            req.allow_model_only = ctx.allow_model_only;
            req.session_id = Some(ctx.session_id.clone());
            req.correlation_id = Some(ctx.trace_id.clone());
            req.cancel = Some(cancel.clone());

            let request_snapshot = req;

            // Attempt 1
            ctx.generation_attempts = 1;
            let attempt1_span = tracing::info_span!(
                "llm_attempt",
                attempt = 1u64,
                gen_ai.request.model = "google/gemini-2.5-flash",
                lancet.attempt.outcome = tracing::field::Empty,
                gen_ai.usage.input_tokens = tracing::field::Empty,
                gen_ai.usage.output_tokens = tracing::field::Empty,
            );

            let result1 = generator
                .generate(request_snapshot.clone())
                .instrument(attempt1_span.clone())
                .await;

            match &result1 {
                Ok(output) => {
                    attempt1_span.record("lancet.attempt.outcome", "ok");
                    if let Some(usage) = &output.usage {
                        attempt1_span.record("gen_ai.usage.input_tokens", usage.prompt_tokens as u64);
                        attempt1_span.record("gen_ai.usage.output_tokens", usage.completion_tokens as u64);
                    }
                }
                Err(err) => {
                    attempt1_span.record("lancet.attempt.outcome", "error");
                    tracing_opentelemetry::OpenTelemetrySpanExt::set_status(
                        &attempt1_span,
                        opentelemetry::trace::Status::error(format!("attempt 1 failed: {:?}", err.kind)),
                    );
                }
            }

            let final_result = match result1 {
                Ok(output) => Ok(output),
                Err(err1) => {
                    if cancel.is_cancelled() || err1.kind == GenerationErrorKind::Cancelled {
                        return Err(NodeError::cancelled().with_context(
                            Some(ctx.session_id.clone()),
                            Some(ctx.trace_id.clone()),
                        ));
                    }

                    // Only retry transient errors (Timeout and transient ProviderError)
                    let is_retryable = err1.kind == GenerationErrorKind::Timeout
                        || err1.kind == GenerationErrorKind::ProviderError;

                    if !is_retryable {
                        Err(err1)
                    } else {
                        // Retry attempt 2 immediately with byte-identical request snapshot
                        if cancel.is_cancelled() {
                            return Err(NodeError::cancelled().with_context(
                                Some(ctx.session_id.clone()),
                                Some(ctx.trace_id.clone()),
                            ));
                        }
                        ctx.generation_attempts = 2;
                        let attempt2_span = tracing::info_span!(
                            "llm_attempt",
                            attempt = 2u64,
                            gen_ai.request.model = "google/gemini-2.5-flash",
                            lancet.attempt.outcome = tracing::field::Empty,
                            gen_ai.usage.input_tokens = tracing::field::Empty,
                            gen_ai.usage.output_tokens = tracing::field::Empty,
                        );

                        let result2 = generator
                            .generate(request_snapshot.clone())
                            .instrument(attempt2_span.clone())
                            .await;

                        match &result2 {
                            Ok(output) => {
                                attempt2_span.record("lancet.attempt.outcome", "ok");
                                if let Some(usage) = &output.usage {
                                    attempt2_span.record("gen_ai.usage.input_tokens", usage.prompt_tokens as u64);
                                    attempt2_span.record("gen_ai.usage.output_tokens", usage.completion_tokens as u64);
                                }
                                crate::telemetry::metrics::record_generation_retry(
                                    crate::telemetry::metrics::RETRY_RECOVERED,
                                );
                            }
                            Err(err) => {
                                attempt2_span.record("lancet.attempt.outcome", "error");
                                tracing_opentelemetry::OpenTelemetrySpanExt::set_status(
                                    &attempt2_span,
                                    opentelemetry::trace::Status::error(format!("attempt 2 failed: {:?}", err.kind)),
                                );
                                crate::telemetry::metrics::record_generation_retry(
                                    crate::telemetry::metrics::RETRY_EXHAUSTED,
                                );
                            }
                        }
                        result2
                    }
                }
            };

            match final_result {
                Ok(output) => {
                    if ctx.allow_model_only
                        && output.should_treat_as_model_only(ctx.evidence_blocks.is_empty())
                    {
                        let for_validation = output.into_model_only();
                        if let Some(limits) = self.grounding_limits {
                            let limits = limits.with_allow_model_only(ctx.allow_model_only);
                            for_validation
                                .validate_grounding_with_limits(&ctx.evidence_blocks, limits)
                                .map_err(|err| {
                                    NodeError::new(
                                        NodeErrorKind::LlmGenerationFailed,
                                        err.message(),
                                    )
                                    .with_context(
                                        Some(ctx.session_id.clone()),
                                        Some(ctx.trace_id.clone()),
                                    )
                                })?;
                        }
                        ctx.update_from_model_output(&for_validation);
                        ctx.structured_citations.clear();
                        ctx.add_notice(crate::workflow::notice(
                            crate::pb::lancet::v1::NoticeCode::ModelOnly,
                            "Answer generated from parametric model knowledge without corpus evidence.",
                            crate::pb::lancet::v1::NoticeSeverity::Info,
                        ));
                    } else if self.citation_repair_enabled && self.grounding_limits.is_some() {
                        // D-14 only replaces the fail-closed branch that existed when
                        // `grounding_limits` is configured (validation is what made an
                        // unresolved marker fatal in the first place); without limits
                        // configured, citation resolution already behaved as a best-effort
                        // lookup against `ctx.evidence_blocks` with no fail-closed check to
                        // repair around, so that path is untouched below.
                        //
                        // Markers come from the
                        // widened extractor (option b, C3) on the raw answer text — never
                        // from `cited_evidence_ids` alone and never from a reconstructed
                        // `[<digits>]` token. Each outcome either keeps the marker (already
                        // exact), repairs it to the resolved evidence identifier, or drops
                        // it; drop and repair both rewrite the original extracted span.
                        let evidence_ids: Vec<&str> =
                            ctx.evidence_blocks.iter().map(|b| b.id.as_str()).collect();
                        let markers = citations::extract_markers(&output.answer);
                        let outcomes = citations::resolve_markers(&markers, &evidence_ids);

                        let mut repaired_answer = output.answer.clone();
                        let mut repaired_citations: Vec<String> = Vec::new();
                        let mut pending_notices = Vec::new();
                        let mut edits: Vec<(citations::MarkerSpan, Option<String>)> = Vec::new();

                        for outcome in &outcomes {
                            match &outcome.resolution {
                                Resolution::Unchanged(id) => {
                                    if !repaired_citations.contains(id) {
                                        repaired_citations.push(id.clone());
                                    }
                                }
                                Resolution::Repaired(id) => {
                                    if !repaired_citations.contains(id) {
                                        repaired_citations.push(id.clone());
                                    }
                                    edits.push((outcome.span, Some(id.clone())));
                                    pending_notices.push(crate::workflow::notice(
                                        crate::pb::lancet::v1::NoticeCode::CitationRepaired,
                                        format!(
                                            "citation marker '{}' repaired to '{}'",
                                            outcome.original, id
                                        ),
                                        crate::pb::lancet::v1::NoticeSeverity::Info,
                                    ));
                                    crate::telemetry::metrics::record_citation_repair(
                                        crate::telemetry::metrics::ACTION_REPAIRED,
                                    );
                                }
                                Resolution::Dropped => {
                                    edits.push((outcome.span, None));
                                    pending_notices.push(crate::workflow::notice(
                                        crate::pb::lancet::v1::NoticeCode::CitationDropped,
                                        format!(
                                            "citation marker '{}' could not be resolved and was dropped",
                                            outcome.original
                                        ),
                                        crate::pb::lancet::v1::NoticeSeverity::Info,
                                    ));
                                    crate::telemetry::metrics::record_citation_repair(
                                        crate::telemetry::metrics::ACTION_DROPPED,
                                    );
                                }
                            }
                        }

                        // Apply text edits right-to-left so earlier byte offsets stay valid.
                        edits.sort_by_key(|(span, _)| std::cmp::Reverse(span.start));
                        for (span, replacement) in edits {
                            let text = replacement.as_deref().unwrap_or("");
                            repaired_answer.replace_range(span.start..span.end, text);
                        }

                        // Total citation loss: markers existed but none survived repair.
                        // Validated (and later reconciled) as model-only rather than failing
                        // the run — the answer lost all grounding, it did not become invalid.
                        let total_drop = !markers.is_empty() && repaired_citations.is_empty();

                        if let Some(limits) = self.grounding_limits {
                            let for_validation = if total_drop {
                                output
                                    .with_answer_and_citations(
                                        repaired_answer.clone(),
                                        repaired_citations.clone(),
                                    )
                                    .into_model_only()
                            } else {
                                output.with_answer_and_citations(
                                    repaired_answer.clone(),
                                    repaired_citations.clone(),
                                )
                            };
                            let effective_allow = ctx.allow_model_only;
                            let limits = limits.with_allow_model_only(effective_allow);
                            for_validation
                                .validate_grounding_with_limits(&ctx.evidence_blocks, limits)
                                .map_err(|err| {
                                    NodeError::new(
                                        NodeErrorKind::LlmGenerationFailed,
                                        err.message(),
                                    )
                                    .with_context(
                                        Some(ctx.session_id.clone()),
                                        Some(ctx.trace_id.clone()),
                                    )
                                })?;
                        }

                        // Re-entry (locked option a): the clone's `answer` is already the
                        // post-strip text and `cited_evidence_ids` the post-repair set, so
                        // `update_from_model_output`'s `self.answer = output.answer.clone()`
                        // cannot restore a marker the strip just removed. The self-reported
                        // basis is left untouched here — reconciliation decides the final
                        // basis from the post-repair citation state, at its single seam.
                        let reentry =
                            output.with_answer_and_citations(repaired_answer, repaired_citations);
                        ctx.update_from_model_output(&reentry);
                        for pending in pending_notices {
                            ctx.add_notice(pending);
                        }

                        let resolved_citations = match self.citation_excerpt_max_chars {
                            Some(max_chars) => resolve_citations_with_max_chars(
                                &ctx.citations,
                                &ctx.evidence_blocks,
                                max_chars,
                            ),
                            None => resolve_citations(&ctx.citations, &ctx.evidence_blocks),
                        };
                        ctx.structured_citations = resolved_citations
                            .iter()
                            .map(|c| crate::pb::lancet::v1::StructuredCitation {
                                chunk_id: c.chunk_id.clone(),
                                document_id: c.document_id.clone(),
                                title: c
                                    .title
                                    .as_deref()
                                    .unwrap_or("Untitled Document")
                                    .to_string(),
                                section_path: c
                                    .section_path
                                    .as_deref()
                                    .unwrap_or("Root")
                                    .to_string(),
                                excerpt: c.bounded_excerpt.clone(),
                                is_truncated: c.is_truncated,
                                score: c.score,
                                rank: c.rank as i32,
                                content_type: c.content_type.clone(),
                            })
                            .collect();
                    } else {
                        // Repair disabled: exactly today's fail-closed behavior.
                        if let Some(limits) = self.grounding_limits {
                            let limits = limits.with_allow_model_only(ctx.allow_model_only);
                            output
                                .validate_grounding_with_limits(&ctx.evidence_blocks, limits)
                                .map_err(|err| {
                                    NodeError::new(
                                        NodeErrorKind::LlmGenerationFailed,
                                        err.message(),
                                    )
                                    .with_context(
                                        Some(ctx.session_id.clone()),
                                        Some(ctx.trace_id.clone()),
                                    )
                                })?;
                        }
                        ctx.update_from_model_output(&output);
                        let resolved_citations = match self.citation_excerpt_max_chars {
                            Some(max_chars) => resolve_citations_with_max_chars(
                                &ctx.citations,
                                &ctx.evidence_blocks,
                                max_chars,
                            ),
                            None => resolve_citations(&ctx.citations, &ctx.evidence_blocks),
                        };
                        if self.grounding_limits.is_some()
                            && resolved_citations.len() != ctx.citations.len()
                        {
                            return Err(NodeError::new(
                                NodeErrorKind::LlmGenerationFailed,
                                "failed to resolve all cited evidence identities completely",
                            )
                            .with_context(
                                Some(ctx.session_id.clone()),
                                Some(ctx.trace_id.clone()),
                            ));
                        }
                        ctx.structured_citations = resolved_citations
                            .iter()
                            .map(|c| crate::pb::lancet::v1::StructuredCitation {
                                chunk_id: c.chunk_id.clone(),
                                document_id: c.document_id.clone(),
                                title: c
                                    .title
                                    .as_deref()
                                    .unwrap_or("Untitled Document")
                                    .to_string(),
                                section_path: c
                                    .section_path
                                    .as_deref()
                                    .unwrap_or("Root")
                                    .to_string(),
                                excerpt: c.bounded_excerpt.clone(),
                                is_truncated: c.is_truncated,
                                score: c.score,
                                rank: c.rank as i32,
                                content_type: c.content_type.clone(),
                            })
                            .collect();
                    }
                    Ok(())
                }
                Err(err) => {
                    if cancel.is_cancelled() || err.kind == GenerationErrorKind::Cancelled {
                        return Err(NodeError::cancelled().with_context(
                            Some(ctx.session_id.clone()),
                            Some(ctx.trace_id.clone()),
                        ));
                    }
                    let node_kind = match err.kind {
                        GenerationErrorKind::Timeout => NodeErrorKind::Timeout,
                        _ => NodeErrorKind::LlmGenerationFailed,
                    };
                    Err(NodeError::new(node_kind, err.message())
                        .with_retryable(false)
                        .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone())))
                }
            }
        })
    }
}
