//! Generate-only engine bin (v1.1 #11, D-247): runs the engine's own prompt and answer tail over
//! context-export rows.
//!
//! ```text
//! generate_from_context <pack|generate> --input <context_export.jsonl> [--levers <names>]
//! generate_from_context render --input <context_export.jsonl> --results <results.jsonl> [--levers <names>]
//! ```
//!
//! Each input line is one context-export row, the contract `eval/src/lancet_eval/context_export.py`
//! validates. The bin rebuilds the engine's evidence blocks and graph facts from the row, runs
//! `AssemblePromptNode` and `GenerateAnswerNode` on them with the engine's own configuration
//! (`config/config.toml` plus `LANCET_*` overrides, read as the engine reads them), and writes one
//! JSON line per row to stdout, in input order.
//!
//! - `pack` makes no network call and needs no API key. A success line carries `body`: the exact
//!   chat-completions request body the engine would post, as a string.
//! - `generate` calls the configured reader through `OpenRouterGenerator` (`OPENROUTER_API_KEY`).
//!   A success line carries the rendered `answer` (ending in the engine's `Answer:` line),
//!   `final_answer`, `citations`, `structured_citations`, `notices`, `answer_basis` and `usage`.
//! - `render` makes no network call either. It takes each row's reader output from the results
//!   file and runs it through the same checks and tail as `generate`, so a success line is the
//!   line `generate` would write for that output (#50, D-254).
//!
//! A results-file line (`render`) holds one reader output for one row:
//!
//! ```text
//! {"question_id": "...", "arm": "...", "content": "<the reader's message content>",
//!  "finish_reason": "stop", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
//! ```
//!
//! `question_id` and `arm` match the row. `content` is the raw message content, the JSON text of
//! the engine's `ModelOutput`. `finish_reason` takes the chat-completions values: `stop` is the
//! only one accepted, and any other (`refusal`, `length`, ...) or `null` rejects the output.
//! `usage` is the chat-completions token usage. A row with no result line becomes a
//! `MISSING_RESULT` error line; a result line whose key reads but whose other fields do not
//! becomes an `INVALID_RESULT` error line for its row. A line with no readable key, or a second
//! line for one key, fails the whole input.
//!
//! `--levers` names the levers the row ran with, comma-separated wire names; an empty value is no
//! lever. Without it the configured `[engine.levers] defaults` apply, as for a request that names
//! none.
//!
//! A row the engine would refuse (no evidence fits, a reader failure, a rejected output) becomes an
//! `error` line with `error_type` and `error`, and the run goes on. Unreadable input or
//! configuration exits non-zero before any row is written.
//!
//! An export row carries no `chunk_index`. For an engine chunk ID, `<document_id>:<n>`, or a
//! LlamaIndex-export one, `<document_id>#<n>`, the index is `n`; any other chunk ID shape renders
//! `chunk_index=0` in the evidence provenance.

use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use engine::config::{load_settings, EffectiveRagSettings};
use engine::doc_meta::DocMeta;
use engine::generation::openrouter::{
    chat_request_body, OpenRouterGenerationConfig, OpenRouterGenerator, ProviderChoice,
};
use engine::generation::{
    BoxFuture, GenerationError, GenerationErrorKind, GenerationRequest, Generator, ModelOutput,
    ModelUsage,
};
use engine::graph::context_strategy::GraphFact;
use engine::pb::lancet::v1::QueryRagRequest;
use engine::prompt::{EvidenceBlock, GraphFactBlock};
use engine::retrieval::{Candidate, FusedCandidate};
use engine::workflow::events::{CheckpointNotice, CheckpointStructuredCitation};
use engine::workflow::nodes::{AssemblePromptNode, GenerateAnswerNode};
use engine::workflow::{LeverSet, Node, WorkflowContext};
use serde::{Deserialize, Serialize};
use tokio_util::sync::CancellationToken;

const USAGE: &str = "usage: generate_from_context <pack|generate> --input <context_export.jsonl> [--levers <names>]
       generate_from_context render --input <context_export.jsonl> --results <results.jsonl> [--levers <names>]";

/// The session ID every rebuilt workflow context carries.
const SESSION_ID: &str = "generate_from_context";

/// What the bin does with each row.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// Emit the chat-completions request body; no network call.
    Pack,
    /// Call the configured reader and emit its validated answer.
    Generate,
    /// Validate and emit the reader output a results file gives; no network call.
    Render,
}

/// The parsed command line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Command {
    pub mode: Mode,
    pub input: String,
    /// The `--levers` names; `None` when the flag is absent.
    pub levers: Option<Vec<String>>,
    /// The `--results` file; `render` only.
    pub results: Option<String>,
}

pub fn parse_args<I: IntoIterator<Item = String>>(args: I) -> Result<Command, String> {
    let mut iter = args.into_iter();
    let mode = match iter.next().as_deref() {
        Some("pack") => Mode::Pack,
        Some("generate") => Mode::Generate,
        Some("render") => Mode::Render,
        Some(other) => return Err(format!("unknown mode '{other}'\n{USAGE}")),
        None => return Err(USAGE.to_owned()),
    };
    let mut input = None;
    let mut levers = None;
    let mut results = None;
    while let Some(arg) = iter.next() {
        let mut value = || {
            iter.next()
                .ok_or_else(|| format!("{arg} needs a value\n{USAGE}"))
        };
        match arg.as_str() {
            "--input" => input = Some(value()?),
            "--results" => results = Some(value()?),
            "--levers" => {
                let names = value()?;
                levers = Some(
                    names
                        .split(',')
                        .map(str::trim)
                        .filter(|name| !name.is_empty())
                        .map(str::to_owned)
                        .collect(),
                );
            }
            _ => return Err(format!("unknown argument '{arg}'\n{USAGE}")),
        }
    }
    let input = input.ok_or_else(|| format!("--input is required\n{USAGE}"))?;
    match (mode, &results) {
        (Mode::Render, None) => return Err(format!("render needs --results\n{USAGE}")),
        (Mode::Pack | Mode::Generate, Some(_)) => {
            return Err(format!("only render reads --results\n{USAGE}"))
        }
        _ => {}
    }
    Ok(Command {
        mode,
        input,
        levers,
        results,
    })
}

/// One context-export row (D-249), as `context_export.py` writes it.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExportRow {
    pub corpus: String,
    pub question_id: String,
    pub arm: String,
    pub question: String,
    pub evidence: Vec<EvidenceEntry>,
    pub graph_facts: Vec<serde_json::Value>,
    #[serde(default)]
    pub assembled_prompt: Option<String>,
    #[serde(default)]
    pub correlation_id: Option<String>,
}

/// One ranked evidence entry of an export row.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceEntry {
    pub rank: usize,
    pub chunk_id: String,
    pub document_id: String,
    pub text: String,
    pub title: Option<String>,
    pub section_path: Option<String>,
    pub content_type: Option<String>,
    pub score: f64,
    pub suspicious: bool,
    pub document_metadata: DocMeta,
}

/// The chunk index a chunk ID `<document_id>:<n>` (engine) or `<document_id>#<n>` (LlamaIndex
/// export) encodes. The separator is the one right after the row's whole document ID, so a
/// document ID that itself holds `:` or `#` reads from its last separator. Any other chunk ID,
/// and an `n` that is not plain digits within `i32`, gives `0`.
pub fn chunk_index_of(entry: &EvidenceEntry) -> i32 {
    entry
        .chunk_id
        .strip_prefix(entry.document_id.as_str())
        .and_then(|rest| rest.strip_prefix([':', '#']))
        .filter(|index| !index.is_empty() && index.bytes().all(|b| b.is_ascii_digit()))
        .and_then(|index| index.parse().ok())
        .unwrap_or(0)
}

/// Rebuilds the engine's evidence blocks from a row's ranked entries.
///
/// Each block comes from `EvidenceBlock::from_candidate`, so its ID, provenance and suspicious
/// check are the engine's own; the metadata is attached as `RetrieveHybrid` attaches it. The row's
/// own suspicious flag can only raise the block's. Ranks must be 1..n in order.
pub fn evidence_blocks(entries: &[EvidenceEntry]) -> Result<Vec<EvidenceBlock>, String> {
    entries
        .iter()
        .enumerate()
        .map(|(index, entry)| {
            if entry.rank != index + 1 {
                return Err(format!(
                    "evidence entry {} has rank {}, expected {}",
                    index + 1,
                    entry.rank,
                    index + 1
                ));
            }
            let candidate = FusedCandidate {
                candidate: Candidate {
                    document_id: entry.document_id.clone(),
                    chunk_id: entry.chunk_id.clone(),
                    chunk_index: chunk_index_of(entry),
                    char_start: 0,
                    char_end: 0,
                    content: entry.text.clone(),
                    title: entry.title.clone(),
                    section_path: entry.section_path.clone(),
                    content_type: entry.content_type.clone(),
                    embedding_model: None,
                    ingested_at: None,
                    score: entry.score,
                },
                fused_score: entry.score,
                vector_rank: None,
                bm25_rank: None,
                vector_score: None,
                bm25_score: None,
                variant_provenance: Vec::new(),
            };
            let mut block = EvidenceBlock::from_candidate(index, &candidate);
            let meta = &entry.document_metadata;
            if meta.source.is_some() || meta.doc_title.is_some() || meta.published_date.is_some() {
                block.attach_evidence_meta(meta.clone());
            }
            block.suspicious |= entry.suspicious;
            Ok(block)
        })
        .collect()
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SerializedFactBlock {
    fact: SerializedFact,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SerializedFact {
    entity_a_name: String,
    relation_type: String,
    entity_b_name: String,
    edge_summary: Option<String>,
    score: f64,
}

/// Undoes the prompt escaping a serialized `GraphFact` carries, so `GraphFact::new` can escape it
/// again exactly once.
fn unescape(value: &str) -> String {
    value
        .replace("&apos;", "'")
        .replace("&quot;", "\"")
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&amp;", "&")
}

/// Rebuilds the engine's graph fact blocks from a row's serialized facts.
///
/// A serialized fact holds already-escaped values. Each is unescaped and passed through
/// `GraphFact::new`; a fact whose rebuilt serialization differs from the row's is refused, so a
/// fact can never reach the prompt escaped twice or not at all.
pub fn graph_fact_blocks(facts: &[serde_json::Value]) -> Result<Vec<GraphFactBlock>, String> {
    facts
        .iter()
        .enumerate()
        .map(|(index, value)| {
            let parsed: SerializedFactBlock = serde_json::from_value(value.clone())
                .map_err(|err| format!("graph fact {}: {err}", index + 1))?;
            let fact = parsed.fact;
            let block = GraphFactBlock {
                fact: GraphFact::new(
                    &unescape(&fact.entity_a_name),
                    &unescape(&fact.relation_type),
                    &unescape(&fact.entity_b_name),
                    fact.edge_summary.as_deref().map(unescape).as_deref(),
                    fact.score,
                ),
            };
            let rebuilt = serde_json::to_value(&block)
                .map_err(|err| format!("graph fact {}: {err}", index + 1))?;
            if &rebuilt != value {
                return Err(format!(
                    "graph fact {} does not round-trip through GraphFact::new",
                    index + 1
                ));
            }
            Ok(block)
        })
        .collect()
}

/// The workflow context the live engine would hold for `row` just before `AssemblePrompt`.
pub fn context_for(
    row: &ExportRow,
    levers: LeverSet,
    allow_model_only: bool,
) -> Result<WorkflowContext, String> {
    let request = QueryRagRequest {
        query: row.question.clone(),
        ..Default::default()
    };
    let trace_id = row
        .correlation_id
        .clone()
        .unwrap_or_else(|| format!("{SESSION_ID}:{}:{}", row.question_id, row.arm));
    let mut ctx = WorkflowContext::new(SESSION_ID.to_owned(), trace_id, &request);
    ctx.levers = levers;
    ctx.allow_model_only = allow_model_only;
    ctx.evidence_blocks = evidence_blocks(&row.evidence)?;
    ctx.graph_facts = graph_fact_blocks(&row.graph_facts)?;
    Ok(ctx)
}

/// A `Generator` that records what `GenerateAnswerNode` asks and gets.
///
/// With no inner generator (`pack`) it records the request and refuses it, so the node's own
/// request construction feeds `chat_request_body`. With one (`generate`) it records the output,
/// whose `final_answer` and total token count the context does not keep.
struct RecordingGenerator {
    inner: Option<Arc<dyn Generator>>,
    request: Mutex<Option<GenerationRequest>>,
    output: Mutex<Option<ModelOutput>>,
}

impl RecordingGenerator {
    fn take(&self) -> (Option<GenerationRequest>, Option<ModelOutput>) {
        (
            self.request.lock().expect("request lock").take(),
            self.output.lock().expect("output lock").take(),
        )
    }
}

/// The message a `pack` refusal carries; never published.
const PACK_REFUSAL: &str = "pack mode makes no reader call";

impl Generator for RecordingGenerator {
    fn model_id(&self) -> &str {
        self.inner
            .as_ref()
            .map_or("unspecified", |inner| inner.model_id())
    }

    fn prepare<'a>(&'a self) -> BoxFuture<'a, Result<(), GenerationError>> {
        Box::pin(async move {
            match &self.inner {
                Some(inner) => inner.prepare().await,
                None => Ok(()),
            }
        })
    }

    fn generate<'a>(
        &'a self,
        request: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
        Box::pin(async move {
            *self.request.lock().expect("request lock") = Some(request.clone());
            let Some(inner) = &self.inner else {
                return Err(GenerationError::new(
                    GenerationErrorKind::InvalidRequest,
                    PACK_REFUSAL,
                ));
            };
            let result = inner.generate(request).await;
            if let Ok(output) = &result {
                *self.output.lock().expect("output lock") = Some(output.clone());
            }
            result
        })
    }
}

/// One results-file line: a reader's output for one row.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResultLine {
    pub question_id: String,
    pub arm: String,
    pub content: String,
    pub finish_reason: Option<String>,
    pub usage: ModelUsage,
}

#[derive(Deserialize)]
struct ResultKey {
    question_id: String,
    arm: String,
}

/// A results file, keyed by `(question_id, arm)`. A line whose key reads but whose other fields
/// do not holds the read error for its row.
#[derive(Debug, Default)]
pub struct Results(HashMap<(String, String), Result<ResultLine, String>>);

impl Results {
    fn get(&self, row: &ExportRow) -> Option<&Result<ResultLine, String>> {
        self.0.get(&(row.question_id.clone(), row.arm.clone()))
    }
}

/// Reads a results file. A line without a readable key, or a second line for one key, fails the
/// whole input.
pub fn read_results(reader: impl BufRead) -> Result<Results, String> {
    let mut results = HashMap::new();
    for (index, line) in reader.lines().enumerate() {
        let line = line.map_err(|err| format!("results line {}: {err}", index + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        let key: ResultKey = serde_json::from_str(&line)
            .map_err(|err| format!("results line {}: {err}", index + 1))?;
        let result = serde_json::from_str::<ResultLine>(&line)
            .map_err(|err| format!("results line {}: {err}", index + 1));
        let key = (key.question_id, key.arm);
        if results.contains_key(&key) {
            return Err(format!(
                "results line {}: a second result for question {} arm {}",
                index + 1,
                key.0,
                key.1
            ));
        }
        results.insert(key, result);
    }
    Ok(Results(results))
}

/// A `Generator` that returns a given reader output instead of calling the network, checked by
/// `OpenRouterGenerationConfig::accept_choice` as the OpenRouter adapter checks a live one.
struct ReplayGenerator {
    config: OpenRouterGenerationConfig,
    result: Mutex<Option<ResultLine>>,
}

impl Generator for ReplayGenerator {
    fn model_id(&self) -> &str {
        self.config.model()
    }

    fn prepare<'a>(&'a self) -> BoxFuture<'a, Result<(), GenerationError>> {
        Box::pin(async { Ok(()) })
    }

    fn generate<'a>(
        &'a self,
        request: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
        Box::pin(async move {
            let result = self.result.lock().expect("result lock").clone();
            let Some(result) = result else {
                return Err(GenerationError::new(
                    GenerationErrorKind::InvalidRequest,
                    "render has no result for this row",
                ));
            };
            self.config.accept_choice(
                &request,
                ProviderChoice {
                    content: &result.content,
                    finish_reason: result.finish_reason.as_deref(),
                    usage: Some(result.usage),
                },
            )
        })
    }
}

/// One output line.
#[derive(Debug, Serialize)]
pub struct OutputLine {
    pub question_id: String,
    pub arm: String,
    /// `success` or `error`.
    pub outcome: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub body: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub answer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub final_answer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub citations: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub structured_citations: Option<Vec<CheckpointStructuredCitation>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub notices: Option<Vec<CheckpointNotice>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub answer_basis: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub usage: Option<ModelUsage>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl OutputLine {
    fn empty(row: &ExportRow, outcome: &'static str) -> Self {
        Self {
            question_id: row.question_id.clone(),
            arm: row.arm.clone(),
            outcome,
            body: None,
            answer: None,
            final_answer: None,
            citations: None,
            structured_citations: None,
            notices: None,
            answer_basis: None,
            usage: None,
            error_type: None,
            error: None,
        }
    }

    fn error(row: &ExportRow, error_type: &str, error: impl Into<String>) -> Self {
        let mut line = Self::empty(row, "error");
        line.error_type = Some(error_type.to_owned());
        line.error = Some(error.into());
        line
    }
}

/// The engine's generation tail, `AssemblePrompt` then `GenerateAnswer`, configured as the
/// service configures it.
pub struct Tail {
    mode: Mode,
    config: OpenRouterGenerationConfig,
    allow_model_only: bool,
    assemble: AssemblePromptNode,
    generate: GenerateAnswerNode,
    recorder: Arc<RecordingGenerator>,
    replay: Option<Arc<ReplayGenerator>>,
}

impl Tail {
    /// A tail for `mode`. `reader` is the generator `generate` calls; `pack` and `render`
    /// ignore it.
    pub fn new(
        mode: Mode,
        settings: &EffectiveRagSettings,
        config: OpenRouterGenerationConfig,
        reader: Option<Arc<dyn Generator>>,
    ) -> Self {
        let replay = (mode == Mode::Render).then(|| {
            Arc::new(ReplayGenerator {
                config: config.clone(),
                result: Mutex::new(None),
            })
        });
        let recorder = Arc::new(RecordingGenerator {
            inner: match mode {
                Mode::Pack => None,
                Mode::Generate => reader,
                Mode::Render => replay.clone().map(|replay| replay as Arc<dyn Generator>),
            },
            request: Mutex::new(None),
            output: Mutex::new(None),
        });
        let limits = settings.grounding_limits();
        let assemble = AssemblePromptNode::with_settings(
            limits.evidence_token_budget() as usize,
            limits.max_output_tokens() as usize,
            settings.retrieval.graph_weight,
        );
        let generate = GenerateAnswerNode::new(Some(recorder.clone() as Arc<dyn Generator>))
            .with_settings(
                *limits,
                settings.citation_excerpt_max_chars,
                settings.retrieval.graph_weight,
            )
            .with_citation_repair_enabled(settings.workflow.citation_repair_enabled);
        Self {
            mode,
            config,
            allow_model_only: settings.workflow.allow_model_only_answers,
            assemble,
            generate,
            recorder,
            replay,
        }
    }

    /// Runs the reader's capability check once, as the engine does at startup.
    pub async fn prepare(&self) -> Result<(), String> {
        self.generate
            .prepare()
            .await
            .map_err(|err| format!("reader preflight failed: {}", err.message))
    }

    /// The `render` output line for one row, from its line in `results`.
    pub async fn render_row(
        &self,
        row: &ExportRow,
        levers: LeverSet,
        results: &Results,
    ) -> OutputLine {
        let result = match results.get(row) {
            None => {
                return OutputLine::error(
                    row,
                    "MISSING_RESULT",
                    "the results file has no line for this row",
                )
            }
            Some(Err(err)) => return OutputLine::error(row, "INVALID_RESULT", err.clone()),
            Some(Ok(result)) => result.clone(),
        };
        let Some(replay) = &self.replay else {
            return OutputLine::error(row, "INVALID_MODE", "render_row needs a render tail");
        };
        *replay.result.lock().expect("result lock") = Some(result);
        let line = self.run_row(row, levers).await;
        replay.result.lock().expect("result lock").take();
        line
    }

    /// The output line for one row. In `render` mode the row's result is the one `render_row`
    /// set.
    pub async fn run_row(&self, row: &ExportRow, levers: LeverSet) -> OutputLine {
        let mut ctx = match context_for(row, levers, self.allow_model_only) {
            Ok(ctx) => ctx,
            Err(err) => return OutputLine::error(row, "INVALID_ROW", err),
        };
        let cancel = CancellationToken::new();
        self.recorder.take();
        if let Err(err) = self.assemble.run(&mut ctx, &cancel).await {
            return OutputLine::error(row, err.kind.as_str_name(), err.message);
        }
        let result = self.generate.run(&mut ctx, &cancel).await;
        let (request, output) = self.recorder.take();
        match self.mode {
            Mode::Pack => {
                let Some(request) = request else {
                    let message = result.err().map_or_else(
                        || "GenerateAnswer made no reader request".to_owned(),
                        |err| err.message,
                    );
                    return OutputLine::error(row, "PACK_FAILED", message);
                };
                match chat_request_body(&self.config, &request).await {
                    Ok(bytes) => match String::from_utf8(bytes) {
                        Ok(body) => {
                            let mut line = OutputLine::empty(row, "success");
                            line.body = Some(body);
                            line
                        }
                        Err(err) => OutputLine::error(row, "PACK_FAILED", err.to_string()),
                    },
                    Err(err) => OutputLine::error(row, "PACK_FAILED", err.message()),
                }
            }
            Mode::Generate | Mode::Render => {
                if let Err(err) = result {
                    return OutputLine::error(row, err.kind.as_str_name(), err.message);
                }
                let snapshot = engine::workflow::events::CheckpointSnapshot::from_context(&ctx);
                let mut line = OutputLine::empty(row, "success");
                line.answer = Some(snapshot.answer);
                line.final_answer = output.as_ref().and_then(|out| out.final_answer.clone());
                line.citations = Some(snapshot.citations);
                line.structured_citations = Some(snapshot.structured_citations);
                line.notices = Some(snapshot.notices);
                line.answer_basis = Some(ctx.answer_basis.as_str_name().to_owned());
                line.usage = output.and_then(|out| out.usage);
                line
            }
        }
    }
}

/// Reads the rows of a context-export file; any unreadable line fails the whole input.
pub fn read_rows(reader: impl BufRead) -> Result<Vec<ExportRow>, String> {
    let mut rows = Vec::new();
    for (index, line) in reader.lines().enumerate() {
        let line = line.map_err(|err| format!("input line {}: {err}", index + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        let row = serde_json::from_str(&line)
            .map_err(|err| format!("input line {}: {err}", index + 1))?;
        rows.push(row);
    }
    Ok(rows)
}

/// The generation config `main.rs` builds for the engine's reader.
fn generation_config(
    settings: &EffectiveRagSettings,
) -> Result<OpenRouterGenerationConfig, String> {
    Ok(OpenRouterGenerationConfig::from_effective_limits(
        settings.generation_model.clone(),
        settings.chat_endpoint.clone(),
        settings.model_metadata_endpoint.clone(),
        Duration::from_secs(settings.generation_timeout_secs),
        settings.temperature,
        settings.top_p,
        settings.grounding_limits_arc(),
    )
    .map_err(|err| format!("invalid generation configuration: {}", err.message()))?
    .with_provider_order(settings.generation_provider_order.clone()))
}

#[tokio::main]
async fn main() -> Result<(), String> {
    let command = parse_args(std::env::args().skip(1))?;
    let settings = load_settings().map_err(|err| format!("loading configuration: {err}"))?;
    let effective = EffectiveRagSettings::try_from_settings(&settings)
        .map_err(|err| format!("invalid RAG configuration: {err}"))?;
    let levers = match &command.levers {
        Some(names) => LeverSet::try_from_names(names).map_err(|err| format!("--levers: {err}"))?,
        None => effective.default_levers,
    };
    let file = std::fs::File::open(&command.input)
        .map_err(|err| format!("opening {}: {err}", command.input))?;
    let rows = read_rows(std::io::BufReader::new(file))?;
    let config = generation_config(&effective)?;
    let results = match &command.results {
        Some(path) => {
            let file = std::fs::File::open(path).map_err(|err| format!("opening {path}: {err}"))?;
            Some(read_results(std::io::BufReader::new(file))?)
        }
        None => None,
    };
    let reader: Option<Arc<dyn Generator>> = match command.mode {
        Mode::Pack | Mode::Render => None,
        Mode::Generate => {
            let api_key = std::env::var("OPENROUTER_API_KEY")
                .map_err(|_| "OPENROUTER_API_KEY is not set".to_owned())?;
            Some(Arc::new(
                OpenRouterGenerator::new_with_config(api_key, config.clone())
                    .map_err(|err| err.message().to_owned())?,
            ))
        }
    };
    let tail = Tail::new(command.mode, &effective, config, reader);
    tail.prepare().await?;
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    for row in &rows {
        let line = match &results {
            Some(results) => tail.render_row(row, levers, results).await,
            None => tail.run_row(row, levers).await,
        };
        let json = serde_json::to_string(&line).map_err(|err| err.to_string())?;
        writeln!(out, "{json}").map_err(|err| err.to_string())?;
    }
    out.flush().map_err(|err| err.to_string())
}

#[cfg(test)]
#[path = "../generate_from_context_tests.rs"]
mod tests;
