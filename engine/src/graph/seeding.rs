//! Mention extraction and seed matching for graph retrieval (D-75).
//!
//! A question is turned into candidate entity mentions without any model call, and each mention
//! is matched to graph entities in a fixed order: case-folded exact name, then normalised name,
//! then a nearest-neighbour search over `entities.name_vector` for the mentions that are still
//! unmatched. All unmatched mentions are embedded in one batch and searched in one multi-vector
//! query, so a question costs at most one embedding call and one scan.
//!
//! Mention text is only ever compared in memory or embedded. It is never placed into a LanceDB
//! predicate or a Cypher query; entity IDs are the only values that reach a predicate, and
//! `graph::paths` validates those as UUIDs first.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use arrow_array::{Array, Float32Array, Int32Array, RecordBatch, StringArray};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use serde::Serialize;

use crate::db::DatabaseManager;
use crate::graph::index::{normalize_name, GraphIndex};
use crate::ingest::EmbeddingProvider;
use crate::retrieval::dense::dense_score;

/// Longest question text, in characters, that mention extraction reads.
///
/// Evaluation questions are a few hundred characters. The bound keeps the tokeniser's work
/// proportional to a fixed ceiling when the text is hostile or accidentally huge. Text past it is
/// ignored, not rejected.
const MAX_QUESTION_CHARS: usize = 4_096;

/// Most mentions returned for one question.
///
/// The observed median is 5 mentions per question and the maximum on the diagnostic sample is
/// well under this value. The cap bounds the embedding batch and the vector scan per question
/// (T-06.3.4.1-13-02). Mentions are kept in question order, so the cap drops the latest ones.
const MAX_MENTIONS: usize = 32;

/// Longest accepted mention, in characters.
///
/// Entity names are short. A longer capitalised run is a heading or a title in capitals, which
/// would only produce a poor embedding. Such a span is dropped rather than truncated.
const MAX_MENTION_CHARS: usize = 128;

/// Shortest accepted mention, in characters. A single letter is never a useful entity name.
const MIN_MENTION_CHARS: usize = 2;

/// Most lower-case connector words that may sit between two capitalised words in one span.
///
/// `Pirates of the Caribbean` needs two (`of the`). Three leaves room without letting a run of
/// function words join unrelated names.
const MAX_INNER_CONNECTORS: usize = 3;

/// Lower-case words that may join two capitalised words into one span (D-75).
///
/// `of`, `and`, `&`, `de` and `the` cover names such as `Bank of America` and
/// `Procter & Gamble`. `-` and `.` cover a spaced hyphen or dot between name parts. A connector
/// never starts or ends a span.
const INNER_CONNECTORS: &[&str] = &["of", "and", "&", "de", "the", "-", "."];

/// Connectors at which a span is also split into separate mentions.
///
/// `Apple and Google` names two entities, while `Procter & Gamble` names one. The whole span is
/// always emitted, and each part is emitted as well, so both readings can match.
const SPLIT_CONNECTORS: &[&str] = &["and", "&"];

/// Words stripped from the front of a capitalised span (case-insensitive).
///
/// These are English question words, auxiliary verbs, prepositions, conjunctions and imperative
/// verbs that start a sentence and are therefore capitalised without naming anything. The list
/// holds no corpus-specific name; a publisher is not a stop-word, and hubs are demoted by degree,
/// not by this list. `the` is deliberately absent: `The Verge` keeps its article and the span
/// without it is added separately.
#[rustfmt::skip]
const LEADING_STOP_WORDS: &[&str] = &[
    "a", "about", "according", "after", "all", "also", "although", "among", "amongst", "an", "and",
    "any", "are", "as", "at", "based", "before", "between", "both", "but", "by", "can", "compare",
    "compared", "considering", "could", "describe", "despite", "did", "do", "does", "during",
    "each", "either", "every", "explain", "find", "following", "for", "from", "give", "given",
    "had", "has", "have", "here", "how", "i", "identify", "if", "in", "into", "is", "it", "its",
    "list", "may", "might", "must", "name", "neither", "no", "not", "of", "on", "or", "other",
    "over", "per", "regarding", "shall", "should", "since", "so", "some", "such", "tell", "that",
    "then", "there", "these", "this", "those", "though", "to", "under", "until", "upon", "via",
    "was", "were", "what", "when", "where", "whether", "which", "while", "who", "whom", "whose",
    "why", "will", "with", "within", "without", "would", "yes",
];

/// How a seed entity was matched to a mention, best first.
///
/// The derived order is the match priority: exact beats normalised beats vector.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MatchKind {
    /// The case-folded mention equals the case-folded entity name.
    Exact,
    /// The mention and the entity name share one normalised form.
    Normalized,
    /// The mention's embedding is near the entity's `name_vector`.
    Vector,
}

/// One matched seed entity.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Seed {
    /// The entity's UUID string.
    pub entity_id: String,
    /// The entity's display name.
    pub name: String,
    /// How the entity was matched.
    pub match_kind: MatchKind,
    /// `1.0` for a name match, the dense score for a vector match.
    pub score: f64,
    /// The entity's degree in the graph index.
    pub degree: u32,
}

/// Seed-matching settings.
///
/// Plain values here; `06.3.4.1-14` maps configuration onto them.
#[derive(Debug, Clone, PartialEq)]
pub struct SeedSettings {
    /// Most seeds kept after ordering.
    pub max_seeds: usize,
    /// Nearest entities fetched per unmatched mention.
    pub mention_vector_top_k: usize,
    /// Smallest dense score (`1 / (1 + distance)`) accepted for a vector match.
    pub seed_match_min_score: f64,
}

/// Default seed cap.
///
/// Seven or more seeds would make more than 15 seed pairs for path search, and RESEARCH §F.1
/// recommends about 6. Raising it grows the pair count quadratically (6 seeds make 15 pairs).
pub const DEFAULT_MAX_SEEDS: usize = 6;

/// Default nearest entities per unmatched mention (RESEARCH §F.1, k = 3).
///
/// Raising it widens recall for misspelt names and admits more weak seeds.
pub const DEFAULT_MENTION_VECTOR_TOP_K: usize = 3;

impl Default for SeedSettings {
    /// Defaults from RESEARCH §F.1, with the score floor the engine already uses for its one
    /// whole-question seed (`engine.graph.seed_match_min_score`).
    fn default() -> Self {
        Self {
            max_seeds: DEFAULT_MAX_SEEDS,
            mention_vector_top_k: DEFAULT_MENTION_VECTOR_TOP_K,
            seed_match_min_score: crate::config::default_seed_match_min_score(),
        }
    }
}

/// Batched nearest-neighbour search over entity name vectors.
#[tonic::async_trait]
pub trait MentionVectorSearch: Send + Sync {
    /// Returns, for each mention in order, up to `top_k` `(entity_id, score)` pairs, best first.
    ///
    /// # Errors
    /// Returns a message when embedding or the vector scan fails.
    async fn search(
        &self,
        mentions: &[String],
        top_k: usize,
    ) -> Result<Vec<Vec<(String, f64)>>, String>;
}

/// Production [`MentionVectorSearch`]: one batched embedding call, one multi-vector KNN.
pub struct LanceMentionVectorSearch {
    /// The store to search. It must already be validated.
    pub database: DatabaseManager,
    /// Provider that embeds the mentions.
    pub embedder: Arc<dyn EmbeddingProvider>,
}

#[tonic::async_trait]
impl MentionVectorSearch for LanceMentionVectorSearch {
    async fn search(
        &self,
        mentions: &[String],
        top_k: usize,
    ) -> Result<Vec<Vec<(String, f64)>>, String> {
        if mentions.is_empty() || top_k == 0 {
            return Ok(vec![Vec::new(); mentions.len()]);
        }
        let vectors = self
            .embedder
            .get_embeddings(mentions)
            .await
            .map_err(|error| format!("mention embedding failed: {error}"))?;
        if vectors.len() != mentions.len() {
            return Err(format!(
                "mention embedding returned {} vectors for {} mentions",
                vectors.len(),
                mentions.len()
            ));
        }
        if vectors
            .iter()
            .any(|vector| vector.is_empty() || vector.iter().any(|value| !value.is_finite()))
        {
            return Err("mention embedding returned an empty or non-finite vector".to_string());
        }

        let table = self.database.entities_table().await?;
        let mut vectors = vectors.into_iter();
        let first = vectors
            .next()
            .ok_or_else(|| "mention embedding returned no vectors".to_string())?;
        let mut query = table
            .query()
            .nearest_to(first)
            .map_err(|error| format!("mention nearest_to failed: {error}"))?;
        for vector in vectors {
            query = query
                .add_query_vector(vector)
                .map_err(|error| format!("mention add_query_vector failed: {error}"))?;
        }
        // `entities` has two vector columns, so the column must be named. `limit` applies to each
        // query vector separately, and the result carries a `query_index` column that maps a row
        // back to its mention; row order across query vectors is not defined.
        let batches: Vec<RecordBatch> = query
            .column("name_vector")
            .select(Select::columns(&["entity_id", "_distance"]))
            .limit(top_k)
            .execute()
            .await
            .map_err(|error| format!("mention vector search failed: {error}"))?
            .try_collect()
            .await
            .map_err(|error| format!("mention vector search collect failed: {error}"))?;

        let mut grouped: Vec<Vec<(String, f64)>> = vec![Vec::new(); mentions.len()];
        for batch in &batches {
            let ids = batch
                .column_by_name("entity_id")
                .and_then(|column| column.as_any().downcast_ref::<StringArray>())
                .ok_or_else(|| "mention search result has no entity_id column".to_string())?;
            let distances = batch
                .column_by_name("_distance")
                .and_then(|column| column.as_any().downcast_ref::<Float32Array>())
                .ok_or_else(|| "mention search result has no _distance column".to_string())?;
            // A single-vector query may omit `query_index`; every row then belongs to mention 0.
            let query_index = batch
                .column_by_name("query_index")
                .and_then(|column| column.as_any().downcast_ref::<Int32Array>());
            for row in 0..batch.num_rows() {
                let slot = query_index.map_or(0, |column| column.value(row).max(0) as usize);
                let Some(list) = grouped.get_mut(slot) else {
                    return Err(format!(
                        "mention search returned query_index {slot} out of range"
                    ));
                };
                list.push((
                    ids.value(row).to_string(),
                    dense_score(f64::from(distances.value(row))),
                ));
            }
            tokio::task::yield_now().await;
        }
        for list in &mut grouped {
            list.sort_by(|a, b| b.1.total_cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
            list.truncate(top_k);
        }
        Ok(grouped)
    }
}

/// One whitespace-separated word after leading and trailing punctuation was removed.
struct Token {
    text: String,
    /// Whether the word ended in punctuation that closes a span (comma, sentence end, quote,
    /// closing bracket or possessive).
    ends_span: bool,
}

fn clean_token(raw: &str) -> Token {
    let mut text = raw.trim_start_matches(|c: char| {
        matches!(c, '"' | '\u{201c}' | '\u{2018}' | '\'' | '(' | '[' | '{')
    });
    let mut ends_span = false;
    loop {
        let Some(last) = text.chars().last() else {
            break;
        };
        match last {
            ',' | ';' | ':' | '?' | '!' | ')' | ']' | '}' | '"' | '\u{201d}' | '\''
            | '\u{2019}' => {
                ends_span = true;
                text = &text[..text.len() - last.len_utf8()];
            }
            // A trailing dot ends a span unless the word is an acronym such as `U.S.`.
            '.' => {
                text = &text[..text.len() - last.len_utf8()];
                if !text.contains('.') {
                    ends_span = true;
                }
            }
            _ => break,
        }
    }
    for suffix in ["'s", "\u{2019}s"] {
        if let Some(stem) = text.strip_suffix(suffix) {
            text = stem;
            ends_span = true;
            break;
        }
    }
    Token {
        text: text.to_string(),
        ends_span,
    }
}

/// A word counts as capitalised when it starts upper-case, or starts lower-case but has an
/// upper-case letter later (`iPhone`, `eBay`).
fn is_capitalised(text: &str) -> bool {
    let mut chars = text.chars();
    match chars.next() {
        Some(first) if first.is_uppercase() => true,
        Some(first) if first.is_lowercase() => chars.any(char::is_uppercase),
        _ => false,
    }
}

fn is_stop_word(text: &str) -> bool {
    LEADING_STOP_WORDS.contains(&text.to_lowercase().as_str())
}

fn is_the(text: &str) -> bool {
    text.eq_ignore_ascii_case("the")
}

/// Turns one finished span into its mentions: the span after stop-word stripping, the same span
/// without a leading `The`, and the parts split at `and` / `&`.
///
/// Stripping a leading stop-word can leave a lower-case connector at the front (`Does the
/// Engadget` leaves `the Engadget`). A connector never starts a span, so those are stripped too;
/// the capitalised `The` of `The Verge` is not a connector and stays.
fn span_mentions(span: &[String]) -> Vec<String> {
    let start = span
        .iter()
        .take_while(|word| is_stop_word(word) || INNER_CONNECTORS.contains(&word.as_str()))
        .count();
    let core = &span[start..];
    if core.is_empty() || (core.len() == 1 && is_the(&core[0])) {
        return Vec::new();
    }
    let mut mentions = vec![core.join(" ")];
    if core.len() > 1 && is_the(&core[0]) {
        mentions.push(core[1..].join(" "));
    }
    if core
        .iter()
        .any(|word| SPLIT_CONNECTORS.contains(&word.as_str()))
    {
        for part in core.split(|word| SPLIT_CONNECTORS.contains(&word.as_str())) {
            let part: Vec<&str> = part
                .iter()
                .map(String::as_str)
                .skip_while(|word| INNER_CONNECTORS.contains(word))
                .collect();
            let end = part
                .iter()
                .rposition(|word| !INNER_CONNECTORS.contains(word))
                .map_or(0, |last| last + 1);
            let part = &part[..end];
            if !part.is_empty() && !(part.len() == 1 && (is_the(part[0]) || is_stop_word(part[0])))
            {
                mentions.push(part.join(" "));
            }
        }
    }
    mentions
}

/// Extracts candidate entity mentions from question text, with no model call (D-75).
///
/// A mention is a maximal run of capitalised words, optionally joined by the lower-case
/// connectors `of`, `and`, `&`, `de` and `the`. A comma, a sentence end, a quote or a possessive
/// ends a run. English question words and other leading function words are stripped
/// (`Does CBSSports.com` gives `CBSSports.com`), possessives are removed (`The Verge's` gives
/// `The Verge`), and a run that starts with `The` also yields the run without it (`Verge`). A
/// run joined by `and` or `&` also yields its parts. Mentions come back in question order, once
/// each, at most [`MAX_MENTIONS`] of them.
///
/// The extractor contains no corpus-specific names. A publisher is a mention like any other;
/// publisher hubs are demoted later by degree, not here.
pub fn extract_mentions(question: &str) -> Vec<String> {
    let text: String = question.chars().take(MAX_QUESTION_CHARS).collect();
    let mut spans: Vec<Vec<String>> = Vec::new();
    let mut span: Vec<String> = Vec::new();
    let mut pending: Vec<String> = Vec::new();

    for raw in text.split_whitespace() {
        let token = clean_token(raw);
        let word = token.text;
        if word.is_empty() {
            pending.clear();
            if !span.is_empty() {
                spans.push(std::mem::take(&mut span));
            }
            continue;
        }
        if is_capitalised(&word) {
            if !span.is_empty() {
                span.append(&mut pending);
            }
            pending.clear();
            span.push(word);
            if token.ends_span {
                spans.push(std::mem::take(&mut span));
            }
        } else if !span.is_empty()
            && INNER_CONNECTORS.contains(&word.as_str())
            && pending.len() < MAX_INNER_CONNECTORS
        {
            pending.push(word);
            if token.ends_span {
                pending.clear();
                spans.push(std::mem::take(&mut span));
            }
        } else {
            pending.clear();
            if !span.is_empty() {
                spans.push(std::mem::take(&mut span));
            }
        }
    }
    if !span.is_empty() {
        spans.push(span);
    }

    let mut seen: HashSet<String> = HashSet::new();
    let mut mentions = Vec::new();
    for span in &spans {
        for mention in span_mentions(span) {
            let length = mention.chars().count();
            if !(MIN_MENTION_CHARS..=MAX_MENTION_CHARS).contains(&length)
                || !mention.chars().any(char::is_alphanumeric)
            {
                continue;
            }
            if seen.insert(mention.to_lowercase()) {
                mentions.push(mention);
                if mentions.len() == MAX_MENTIONS {
                    return mentions;
                }
            }
        }
    }
    mentions
}

fn seed_for(index: &GraphIndex, entity_id: &str, match_kind: MatchKind, score: f64) -> Seed {
    Seed {
        entity_id: entity_id.to_string(),
        name: index.entity_name(entity_id).unwrap_or_default().to_string(),
        match_kind,
        score,
        degree: index.degree(entity_id),
    }
}

/// Keeps the better of the stored and the offered seed for one entity: the better match kind,
/// then the higher score.
fn offer(best: &mut HashMap<String, Seed>, seed: Seed) {
    match best.get(&seed.entity_id) {
        Some(existing)
            if existing.match_kind < seed.match_kind
                || (existing.match_kind == seed.match_kind && existing.score >= seed.score) => {}
        _ => {
            best.insert(seed.entity_id.clone(), seed);
        }
    }
}

/// Matches mentions to seed entities (D-75).
///
/// Each mention is matched by case-folded exact name; a mention with no exact match is matched
/// by normalised name; the mentions still unmatched are sent to `search` together, in one call,
/// and a candidate is accepted only when its score is at least
/// [`SeedSettings::seed_match_min_score`] and its name has at least one letter or digit (an
/// entity named only with spaces or punctuation embeds to a degenerate vector that scores exactly
/// the minimum against any mention, so it is never a seed). One entity found through several
/// mentions is one seed, with its best match kind. Seeds are ordered by match kind, then by
/// degree ascending (which is specificity `1 / ln(2 + degree)` descending, so a hub sorts after
/// a specific entity of the same kind), then by entity ID, and cut to
/// [`SeedSettings::max_seeds`]. The order does not depend on the order of `mentions`.
///
/// # Errors
/// Returns the error of `search`, or a message when it returns the wrong number of result lists.
pub async fn match_seeds(
    index: &GraphIndex,
    mentions: &[String],
    search: &dyn MentionVectorSearch,
    settings: &SeedSettings,
) -> Result<Vec<Seed>, String> {
    let mut best: HashMap<String, Seed> = HashMap::new();
    let mut unmatched: Vec<String> = Vec::new();
    let mut unmatched_seen: HashSet<String> = HashSet::new();

    for mention in mentions {
        let exact = index.exact_matches(mention);
        if !exact.is_empty() {
            for entity_id in exact {
                offer(&mut best, seed_for(index, entity_id, MatchKind::Exact, 1.0));
            }
            continue;
        }
        let normalized = index.normalized_matches(mention);
        if !normalized.is_empty() {
            for entity_id in normalized {
                offer(
                    &mut best,
                    seed_for(index, entity_id, MatchKind::Normalized, 1.0),
                );
            }
            continue;
        }
        if unmatched_seen.insert(mention.to_lowercase()) {
            unmatched.push(mention.clone());
        }
    }

    if !unmatched.is_empty() && settings.mention_vector_top_k > 0 {
        let hits = search
            .search(&unmatched, settings.mention_vector_top_k)
            .await?;
        if hits.len() != unmatched.len() {
            return Err(format!(
                "mention vector search returned {} result lists for {} mentions",
                hits.len(),
                unmatched.len()
            ));
        }
        for list in hits {
            for (entity_id, score) in list.into_iter().take(settings.mention_vector_top_k) {
                if score.is_finite()
                    && score >= settings.seed_match_min_score
                    && index
                        .entity_name(&entity_id)
                        .is_some_and(|name| !normalize_name(name).is_empty())
                {
                    offer(
                        &mut best,
                        seed_for(index, &entity_id, MatchKind::Vector, score),
                    );
                }
            }
        }
    }

    let mut seeds: Vec<Seed> = best.into_values().collect();
    seeds.sort_by(|a, b| {
        a.match_kind
            .cmp(&b.match_kind)
            .then_with(|| a.degree.cmp(&b.degree))
            .then_with(|| a.entity_id.cmp(&b.entity_id))
    });
    seeds.truncate(settings.max_seeds);
    Ok(seeds)
}
