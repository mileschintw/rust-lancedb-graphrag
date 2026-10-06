//! Bounded seed-to-seed path search over `entity_edges` (D-76, D-77).
//!
//! Given the seeds that [`crate::graph::seeding::match_seeds`] chose, this module finds the short
//! paths that connect them: a direct seed-to-seed edge is a one-hop path, and a neighbour shared
//! by two seeds is a two-hop path `A - X - B`. Only these path facts are produced; the
//! unfiltered one-hop neighbourhood of a seed is never returned.
//!
//! One scan reads every edge that touches a seed. Everything after that is in-memory set work, so
//! the cost is the number of edges at the seeds plus at most `MAX_PATH_SEEDS * (MAX_PATH_SEEDS -
//! 1) / 2` seed pairs, and no Cypher query is built or run. A seed is never expanded beyond that
//! scan. A two-hop intermediate whose degree is above [`DEGREE_CAP`] is excluded, because an
//! intermediate with hundreds of edges connects almost anything and carries no information.
//!
//! The only values that reach a LanceDB predicate are seed entity IDs, and they are parsed as
//! UUIDs and SQL-literal escaped first. Mention text never gets here.
//!
//! The functions are pure where they can be: [`build_paths`] works on rows already scanned, and
//! [`find_seed_paths`] adds the validated scan around it.

use std::cmp::Reverse;
use std::collections::{BTreeMap, HashMap, HashSet};

use arrow_array::{Array, Float32Array, RecordBatch, StringArray};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use uuid::Uuid;

use crate::db::DatabaseManager;
use crate::graph::context_strategy::GraphFact;
use crate::graph::escape_sql_literal;
use crate::graph::index::GraphIndex;
use crate::graph::seeding::Seed;

/// The largest entity degree that a two-hop path may pass through.
///
/// **Derivation.** The cap is the 99th percentile of the entity degree distribution of the
/// reconciled eval store, rounded up. `reconcile/graph_population_post.json` records, over 27,855
/// entities and 45,052 `entity_edges` rows, a median degree of 1, `p95` 10, `p99` 33.0 and a
/// maximum of 543 (`Google`). Degree is source plus target occurrences, with a self-loop counted
/// twice, which is how [`GraphIndex`] counts it, so the figures are the same quantity. The
/// percentile is recomputed from the index in the seed probe (`06.3.4.1-SEED-PROBE.md`).
///
/// **Effect of changing it.** A smaller cap, such as `p95 = 10`, would also exclude mid-size real
/// entities as bridges and lose paths. A larger cap admits more hubs: at the maximum of 543 a
/// single intermediate can join any two seeds that both mention a large publisher, and every such
/// path is noise. The cap affects intermediates only; a hub that is itself a seed stays a seed.
///
/// Confirmed or amended at the `06.3.4.1-13` Task 3 decision checkpoint.
pub const DEGREE_CAP: u32 = 33;

/// The most path facts one question may inject into the prompt, whatever the budget formula says.
///
/// **Derivation.** `MAX_PATH_FACTS = min(16, floor(0.10 * (evidence_token_budget -
/// answer_budget) / p95_fact_tokens))` (see [`derive_max_path_facts`]). The ceiling of 16 keeps
/// the graph section a small part of the evidence even when facts are short; RESEARCH §F.6 gives
/// `0.10 * 6144 / ~25 = ~24` and rounds it down to at most 16. The measured `p95_fact_tokens` and
/// the resulting value are recorded in `06.3.4.1-SEED-PROBE.md`.
///
/// **Effect of changing it.** Raising it spends prompt budget that evidence chunks would use;
/// lowering it drops lower-ranked paths.
pub const MAX_PATH_FACTS_CEILING: usize = 16;

/// The share of the evidence token budget that graph facts may occupy.
///
/// One tenth keeps graph facts a minor part of the evidence section, the same order as the
/// default `graph_weight` competition in prompt packing. Raising it lets graph facts displace
/// retrieved chunks.
const PATH_FACT_BUDGET_PERCENT: u64 = 10;

/// Most seeds the path search reads, whatever the caller passes.
///
/// Seeds arrive in priority order and `SeedSettings::max_seeds` already caps them at 6, which is
/// 15 pairs. This second bound keeps the pair count at 28 or fewer if a caller passes more, so
/// the work stays bounded by construction (T-06.3.4.1-13-02).
const MAX_PATH_SEEDS: usize = 8;

/// One `entity_edges` row as the path search consumes it.
#[derive(Debug, Clone, PartialEq)]
pub struct EdgeRow {
    /// The edge's unique ID, used only to break ties deterministically.
    pub edge_id: String,
    /// The source entity's UUID string.
    pub source: String,
    /// The target entity's UUID string.
    pub target: String,
    /// The relation text.
    pub relation: String,
    /// The extraction weight of the edge.
    pub weight: f64,
}

/// Path-search settings.
///
/// Plain values here; `06.3.4.1-14` maps configuration onto them.
#[derive(Debug, Clone, PartialEq)]
pub struct PathSettings {
    /// Largest degree an intermediate may have. See [`DEGREE_CAP`].
    pub degree_cap: u32,
    /// Most path facts kept after ranking. See [`MAX_PATH_FACTS_CEILING`].
    pub max_path_facts: usize,
    /// Most candidate chunk IDs returned.
    pub max_graph_chunk_candidates: usize,
}

/// One seed-to-seed path.
#[derive(Debug, Clone, PartialEq)]
pub struct PathFact {
    /// Entity IDs along the path: two for a direct edge, three for a path through one neighbour.
    pub entities: Vec<String>,
    /// The relation text of each hop, in path order.
    pub relations: Vec<String>,
    /// The path score: the sum over hops of `weight / ln(2 + max endpoint degree)`.
    pub score: f64,
    /// The path as readable text with hop directions. This is raw entity text for diagnostics and
    /// is not escaped for the prompt; prompt text goes through [`GraphFact`], which escapes.
    pub rendered: String,
}

/// The result of a seed-to-seed path search.
#[derive(Debug, Clone, PartialEq)]
pub struct SeedPathResult {
    /// One prompt-ready fact per kept path, in rank order.
    pub facts: Vec<GraphFact>,
    /// The kept paths, in rank order.
    pub paths: Vec<PathFact>,
    /// Whether at least one path was kept.
    pub path_found: bool,
    /// Ranked source-chunk IDs of the entities on the kept paths, capped.
    pub candidate_chunk_ids: Vec<String>,
    /// Two-hop paths dropped because their intermediate's degree was above the cap.
    pub degree_capped_count: u32,
}

impl SeedPathResult {
    fn empty() -> Self {
        Self {
            facts: Vec::new(),
            paths: Vec::new(),
            path_found: false,
            candidate_chunk_ids: Vec::new(),
            degree_capped_count: 0,
        }
    }
}

/// Derives the path-fact cap from the prompt budget and the measured size of a rendered fact.
///
/// Returns `min(MAX_PATH_FACTS_CEILING, floor(0.10 * (evidence_token_budget - answer_token_budget)
/// / p95_fact_tokens))`, computed in integers so a floor never rounds the wrong way. Returns
/// `None` when `p95_fact_tokens` is `0`, because no fact was measured and no cap follows from it.
pub fn derive_max_path_facts(
    evidence_token_budget: u32,
    answer_token_budget: u32,
    p95_fact_tokens: u32,
) -> Option<usize> {
    if p95_fact_tokens == 0 {
        return None;
    }
    let room = u64::from(evidence_token_budget.saturating_sub(answer_token_budget));
    let facts = room * PATH_FACT_BUDGET_PERCENT / (100 * u64::from(p95_fact_tokens));
    Some((facts as usize).min(MAX_PATH_FACTS_CEILING))
}

/// The best edge between a seed and one neighbour, with its stored direction.
#[derive(Clone, Copy)]
struct Hop<'a> {
    edge: &'a EdgeRow,
    /// Whether the stored edge points from the seed to the neighbour.
    from_seed: bool,
}

/// Whether `candidate` is a better edge than `current`: higher weight, then the smaller relation
/// text, then the smaller edge ID.
fn better_edge(candidate: &EdgeRow, current: &EdgeRow) -> bool {
    candidate
        .weight
        .total_cmp(&current.weight)
        .then_with(|| current.relation.cmp(&candidate.relation))
        .then_with(|| current.edge_id.cmp(&candidate.edge_id))
        .is_gt()
}

fn offer_hop<'a>(map: &mut BTreeMap<&'a str, Hop<'a>>, neighbour: &'a str, hop: Hop<'a>) {
    match map.get(neighbour) {
        Some(current) if !better_edge(hop.edge, current.edge) => {}
        _ => {
            map.insert(neighbour, hop);
        }
    }
}

/// `1 / ln(2 + degree)`: the HippoRAG-style specificity weight. It is `1 / ln 2` at degree 0 and
/// falls slowly, so a hub is demoted without a sharp cut-off.
fn specificity(degree: u32) -> f64 {
    1.0 / (2.0 + f64::from(degree)).ln()
}

fn hop_score(index: &GraphIndex, hop: &EdgeRow) -> f64 {
    let degree = index.degree(&hop.source).max(index.degree(&hop.target));
    hop.weight * specificity(degree)
}

fn display_name<'a>(index: &'a GraphIndex, entity_id: &'a str) -> &'a str {
    index.entity_name(entity_id).unwrap_or(entity_id)
}

/// The text between two entity names for one hop: a right arrow when the stored edge points
/// along the path, and a left arrow when it points against it.
fn connector(relation: &str, forward: bool) -> String {
    if forward {
        format!(" \u{2014}{relation}\u{2192} ")
    } else {
        format!(" \u{2190}{relation}\u{2014} ")
    }
}

/// Builds one path from a seed through zero or one neighbour to another seed.
fn make_path(
    index: &GraphIndex,
    first: &str,
    middle: Option<(&str, Hop<'_>)>,
    last: &str,
    first_hop: Hop<'_>,
) -> (PathFact, GraphFact) {
    let first_name = display_name(index, first);
    let last_name = display_name(index, last);
    match middle {
        None => {
            let rendered = format!(
                "{first_name}{}{last_name}",
                connector(&first_hop.edge.relation, first_hop.from_seed)
            );
            let (fact_a, fact_b) = if first_hop.from_seed {
                (first_name, last_name)
            } else {
                (last_name, first_name)
            };
            let fact = GraphFact::new(
                fact_a,
                &first_hop.edge.relation,
                fact_b,
                Some(rendered.as_str()),
                hop_score(index, first_hop.edge),
            );
            (
                PathFact {
                    entities: vec![first.to_string(), last.to_string()],
                    relations: vec![first_hop.edge.relation.clone()],
                    score: hop_score(index, first_hop.edge),
                    rendered,
                },
                fact,
            )
        }
        Some((via, second_hop)) => {
            let via_name = display_name(index, via);
            // `first_hop` is stored relative to the first seed; `second_hop` relative to the last
            // seed, so its stored direction as seen along the path is reversed.
            let rendered = format!(
                "{first_name}{}{via_name}{}{last_name}",
                connector(&first_hop.edge.relation, first_hop.from_seed),
                connector(&second_hop.edge.relation, !second_hop.from_seed)
            );
            let score = hop_score(index, first_hop.edge) + hop_score(index, second_hop.edge);
            let chain = format!(
                "{}\u{2192}{via_name}\u{2192}{}",
                first_hop.edge.relation, second_hop.edge.relation
            );
            let fact = GraphFact::new(
                first_name,
                &chain,
                last_name,
                Some(rendered.as_str()),
                score,
            );
            (
                PathFact {
                    entities: vec![first.to_string(), via.to_string(), last.to_string()],
                    relations: vec![
                        first_hop.edge.relation.clone(),
                        second_hop.edge.relation.clone(),
                    ],
                    score,
                    rendered,
                },
                fact,
            )
        }
    }
}

/// Ranks the chunks that a list of entities cites and returns the best `cap` of them.
///
/// `entities` is in priority order and holds each entity once. A chunk cited by several of the
/// entities comes first, because a chunk that mentions both ends of a bridge is the strongest
/// evidence for it. Ties go to the chunk that is earlier in its entity's own list (so each
/// entity contributes its first chunk before any contributes its second, which keeps a hub with
/// hundreds of chunks from filling the cap alone), then to the higher-priority entity, then to
/// the chunk ID.
fn rank_chunks(index: &GraphIndex, entities: &[&str], cap: usize) -> Vec<String> {
    if cap == 0 {
        return Vec::new();
    }
    // chunk -> (entities citing it, earliest position in any entity's list, best entity rank)
    let mut stats: HashMap<&str, (u32, usize, usize)> = HashMap::new();
    for (rank, entity_id) in entities.iter().enumerate() {
        let mut seen: HashSet<&str> = HashSet::new();
        for (position, chunk) in index.source_chunk_ids(entity_id).iter().enumerate() {
            if !seen.insert(chunk.as_str()) {
                continue;
            }
            let entry = stats.entry(chunk.as_str()).or_insert((0, position, rank));
            entry.0 += 1;
            entry.1 = entry.1.min(position);
            entry.2 = entry.2.min(rank);
        }
    }
    let mut ranked: Vec<(&str, (u32, usize, usize))> = stats.into_iter().collect();
    ranked.sort_by(|a, b| {
        (Reverse(a.1 .0), a.1 .1, a.1 .2, a.0).cmp(&(Reverse(b.1 .0), b.1 .1, b.1 .2, b.0))
    });
    ranked
        .into_iter()
        .take(cap)
        .map(|(chunk, _)| chunk.to_string())
        .collect()
}

/// Source chunks of the seeds themselves, ranked and capped: the candidates of a length-0 path.
///
/// This is what the `paths-plus-seed-chunks` option of the `06.3.4.1-13` Task 3 decision would
/// use when a question has seeds but no path. Nothing in the retrieval path calls it until that
/// option is chosen; the offline probe calls it to measure the option. `seeds` is in priority
/// order.
pub fn seed_chunk_candidates(index: &GraphIndex, seeds: &[Seed], cap: usize) -> Vec<String> {
    let mut seen: HashSet<&str> = HashSet::new();
    let ordered: Vec<&str> = seeds
        .iter()
        .map(|seed| seed.entity_id.as_str())
        .filter(|entity_id| seen.insert(*entity_id))
        .collect();
    rank_chunks(index, &ordered, cap)
}

/// Builds the seed-to-seed paths from edges that have already been scanned.
///
/// `edges` must hold every edge that touches a seed; edges that touch no seed are ignored.
/// Seeds are taken in the given priority order, de-duplicated, and limited to eight. For each pair
/// of seeds the best direct edge (highest weight, then relation text, then edge ID) makes a
/// one-hop path, and each neighbour shared by the pair makes a two-hop path through the best
/// edge of each hop. A neighbour that is itself a seed is skipped, because its two edges are
/// already one-hop paths. A neighbour whose degree is above `settings.degree_cap` is skipped and
/// counted in `degree_capped_count`.
///
/// Paths are ranked by score, then by fewer hops, then by entity IDs, so the order is
/// deterministic. The path score is the sum over its hops of `weight / ln(2 + d)`, where `d` is
/// the larger degree of the hop's two ends. The ranked list is cut to `settings.max_path_facts`,
/// and the candidate chunks are those of the entities on the kept paths.
pub fn build_paths(
    index: &GraphIndex,
    seeds: &[Seed],
    edges: &[EdgeRow],
    settings: &PathSettings,
) -> SeedPathResult {
    let mut seen: HashSet<&str> = HashSet::new();
    let seed_ids: Vec<&str> = seeds
        .iter()
        .map(|seed| seed.entity_id.as_str())
        .filter(|entity_id| seen.insert(*entity_id))
        .take(MAX_PATH_SEEDS)
        .collect();
    if seed_ids.len() < 2 {
        return SeedPathResult::empty();
    }
    let seed_position: HashMap<&str, usize> = seed_ids
        .iter()
        .enumerate()
        .map(|(i, id)| (*id, i))
        .collect();

    // For each seed, its neighbours and the best edge to each (a BTreeMap, for stable order).
    let mut neighbours: Vec<BTreeMap<&str, Hop<'_>>> = vec![BTreeMap::new(); seed_ids.len()];
    for edge in edges {
        if edge.source == edge.target {
            continue;
        }
        if let Some(&position) = seed_position.get(edge.source.as_str()) {
            offer_hop(
                &mut neighbours[position],
                edge.target.as_str(),
                Hop {
                    edge,
                    from_seed: true,
                },
            );
        }
        if let Some(&position) = seed_position.get(edge.target.as_str()) {
            offer_hop(
                &mut neighbours[position],
                edge.source.as_str(),
                Hop {
                    edge,
                    from_seed: false,
                },
            );
        }
    }

    let mut found: Vec<(PathFact, GraphFact)> = Vec::new();
    let mut degree_capped_count = 0u32;
    for i in 0..seed_ids.len() {
        for j in (i + 1)..seed_ids.len() {
            if let Some(&hop) = neighbours[i].get(seed_ids[j]) {
                found.push(make_path(index, seed_ids[i], None, seed_ids[j], hop));
            }
            for (&via, &first_hop) in &neighbours[i] {
                if seed_position.contains_key(via) {
                    continue;
                }
                let Some(&second_hop) = neighbours[j].get(via) else {
                    continue;
                };
                if index.degree(via) > settings.degree_cap {
                    degree_capped_count += 1;
                    continue;
                }
                found.push(make_path(
                    index,
                    seed_ids[i],
                    Some((via, second_hop)),
                    seed_ids[j],
                    first_hop,
                ));
            }
        }
    }

    found.sort_by(|a, b| {
        b.0.score
            .total_cmp(&a.0.score)
            .then_with(|| a.0.entities.len().cmp(&b.0.entities.len()))
            .then_with(|| a.0.entities.cmp(&b.0.entities))
    });
    found.truncate(settings.max_path_facts);

    let mut entity_order: Vec<&str> = Vec::new();
    let mut entity_seen: HashSet<&str> = HashSet::new();
    for (path, _) in &found {
        for entity_id in &path.entities {
            if entity_seen.insert(entity_id.as_str()) {
                entity_order.push(entity_id.as_str());
            }
        }
    }
    let candidate_chunk_ids =
        rank_chunks(index, &entity_order, settings.max_graph_chunk_candidates);

    let (paths, facts): (Vec<PathFact>, Vec<GraphFact>) = found.into_iter().unzip();
    SeedPathResult {
        path_found: !paths.is_empty(),
        facts,
        paths,
        candidate_chunk_ids,
        degree_capped_count,
    }
}

/// Reads the edges that touch the seeds in one scan.
async fn scan_seed_edges(db: &DatabaseManager, seed_ids: &[&str]) -> Result<Vec<EdgeRow>, String> {
    let in_list = seed_ids
        .iter()
        .map(|id| format!("'{}'", escape_sql_literal(id)))
        .collect::<Vec<_>>()
        .join(",");
    let predicate = format!("source_node_id IN ({in_list}) OR target_node_id IN ({in_list})");
    let table = db.entity_edges_table().await?;
    let batches: Vec<RecordBatch> = table
        .query()
        .only_if(predicate)
        .select(Select::columns(&[
            "edge_id",
            "source_node_id",
            "target_node_id",
            "relation_type",
            "weight",
        ]))
        .execute()
        .await
        .map_err(|error| format!("failed to scan seed edges: {error}"))?
        .try_collect()
        .await
        .map_err(|error| format!("failed to collect seed edges: {error}"))?;

    let mut rows = Vec::new();
    for batch in &batches {
        let string = |name: &str| -> Result<&StringArray, String> {
            batch
                .column_by_name(name)
                .and_then(|column| column.as_any().downcast_ref::<StringArray>())
                .ok_or_else(|| format!("entity_edges.{name} is missing or not a string"))
        };
        let edge_ids = string("edge_id")?;
        let sources = string("source_node_id")?;
        let targets = string("target_node_id")?;
        let relations = string("relation_type")?;
        let weights = batch
            .column_by_name("weight")
            .and_then(|column| column.as_any().downcast_ref::<Float32Array>())
            .ok_or_else(|| "entity_edges.weight is missing or not a float".to_string())?;
        for row in 0..batch.num_rows() {
            if weights.is_null(row) {
                continue;
            }
            rows.push(EdgeRow {
                edge_id: edge_ids.value(row).to_string(),
                source: sources.value(row).to_string(),
                target: targets.value(row).to_string(),
                relation: relations.value(row).to_string(),
                weight: f64::from(weights.value(row)),
            });
        }
        tokio::task::yield_now().await;
    }
    Ok(rows)
}

/// Finds the paths that connect the seeds, with one scan of `entity_edges`.
///
/// Every seed ID is parsed as a UUID before any predicate is built. With fewer than two distinct
/// seeds there is nothing to connect and no scan is made.
///
/// # Errors
/// Returns a message when a seed ID is not a UUID or the scan fails.
pub async fn find_seed_paths(
    db: &DatabaseManager,
    index: &GraphIndex,
    seeds: &[Seed],
    settings: &PathSettings,
) -> Result<SeedPathResult, String> {
    for seed in seeds {
        Uuid::parse_str(&seed.entity_id)
            .map_err(|error| format!("seed entity id is not a valid UUID: {error}"))?;
    }
    let mut seen: HashSet<&str> = HashSet::new();
    let seed_ids: Vec<&str> = seeds
        .iter()
        .map(|seed| seed.entity_id.as_str())
        .filter(|entity_id| seen.insert(*entity_id))
        .take(MAX_PATH_SEEDS)
        .collect();
    if seed_ids.len() < 2 {
        return Ok(SeedPathResult::empty());
    }
    let edges = scan_seed_edges(db, &seed_ids).await?;
    Ok(build_paths(index, seeds, &edges, settings))
}
