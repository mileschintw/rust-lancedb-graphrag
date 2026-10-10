//! Tests for the production graph cutover (06.3.4.1-14, D-75, D-76, D-78, D-79).
//!
//! Production graph augmentation seeds from the entities the question names and injects only
//! seed-to-seed path facts. These tests pin that behaviour at three levels: the service function
//! `attempt_graph_augmentation`, the `ProductionGraphQueryPort` that runs it over the snapshot's
//! graph index, and the `ExtractGraphContext` node that records the result on the workflow context.

use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use futures::future::BoxFuture;
use tokio_util::sync::CancellationToken;

use crate::config::GraphSettings;
use crate::db::DatabaseManager;
use crate::graph::index::GraphIndex;
use crate::graph::paths::{build_paths, EdgeRow, PathSettings, DEGREE_CAP, MAX_PATH_FACTS};
use crate::graph::seeding::{MatchKind, MentionVectorSearch, Seed};
use crate::graph::tests::seed_paths::{
    id, temp_path, write_store_edges, write_store_entities, StoreEntity,
};
use crate::ingest::EmbeddingProvider;
use crate::prompt::GraphFactBlock;
use crate::service::{
    attempt_graph_augmentation, attempt_graph_augmentation_with_search, GraphAugmentationOutcome,
    ProductionGraphQueryPort,
};
use crate::testkit::test_query_request;
use crate::workflow::node::Node;
use crate::workflow::ports::{
    FakeGraphQueryPort, FakeQueryEmbeddingPort, GraphQueryOutput, GraphQueryPort,
};
use crate::workflow::{self, WorkflowContext};

// ---- fixtures -------------------------------------------------------------------------------

/// A store, and the index built from it, holding this graph:
///
/// `Acme Corp -owns-> Gamma Bridge -supplies-> Beta Works`, plus two entities with no edge at all
/// (`Delta Solo`, `Echo Island`). Acme Corp and Beta Works are joined by a two-hop path.
pub(crate) struct Fixture {
    pub(crate) database: DatabaseManager,
    pub(crate) index: GraphIndex,
    path: String,
}

impl Fixture {
    pub(crate) async fn new(name: &str) -> Self {
        let path = temp_path(name);
        let database = DatabaseManager::initialize(&path).await.unwrap();
        let entity = |n: u128, name: &'static str| StoreEntity {
            n,
            name,
            chunks: vec![format!("{}:0", id(900 + n))],
            vector_value: 0.1 * n as f32,
        };
        write_store_entities(
            &database,
            &[
                entity(1, "Acme Corp"),
                entity(2, "Beta Works"),
                entity(3, "Gamma Bridge"),
                entity(4, "Delta Solo"),
                entity(5, "Echo Island"),
            ],
        )
        .await;
        write_store_edges(&database, &[(1, 3, "owns", 1.0), (3, 2, "supplies", 1.0)]).await;
        let index = GraphIndex::build(&database).await.unwrap();
        Self {
            database,
            index,
            path,
        }
    }

    pub(crate) fn cleanup(self) {
        drop(self.database);
        let _ = std::fs::remove_dir_all(self.path);
    }
}

/// A mention vector search that answers from a table keyed by the lower-cased mention and counts
/// its calls.
struct StubSearch {
    hits: HashMap<String, Vec<(String, f64)>>,
    fail: bool,
    calls: AtomicUsize,
}

impl StubSearch {
    fn none() -> Self {
        Self {
            hits: HashMap::new(),
            fail: false,
            calls: AtomicUsize::new(0),
        }
    }

    fn with_hit(mention: &str, entity: u128, score: f64) -> Self {
        let mut search = Self::none();
        search
            .hits
            .insert(mention.to_lowercase(), vec![(id(entity), score)]);
        search
    }

    fn failing() -> Self {
        Self {
            fail: true,
            ..Self::none()
        }
    }

    fn calls(&self) -> usize {
        self.calls.load(Ordering::SeqCst)
    }
}

#[tonic::async_trait]
impl MentionVectorSearch for StubSearch {
    async fn search(
        &self,
        mentions: &[String],
        _top_k: usize,
    ) -> Result<Vec<Vec<(String, f64)>>, String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if self.fail {
            return Err("injected vector search failure".to_string());
        }
        Ok(mentions
            .iter()
            .map(|mention| {
                self.hits
                    .get(&mention.to_lowercase())
                    .cloned()
                    .unwrap_or_default()
            })
            .collect())
    }
}

/// An embedding provider that counts how many times it is asked to embed.
struct CountingEmbedder {
    calls: AtomicUsize,
}

impl EmbeddingProvider for CountingEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async move { Ok(texts.iter().map(|_| vec![0.25; 2048]).collect()) })
    }
}

fn settings() -> GraphSettings {
    GraphSettings::default()
}

fn two_entity_question() -> &'static str {
    "Does Acme Corp work with Beta Works?"
}

fn sorted(mut values: Vec<String>) -> Vec<String> {
    values.sort();
    values
}

// ---- attempt_graph_augmentation -------------------------------------------------------------

/// Behavior 1: a question naming two entities joined by a two-hop path.
#[tokio::test]
async fn a_question_naming_two_entities_joined_by_a_two_hop_path_yields_the_path_fact() {
    let fixture = Fixture::new("cutover-two-hop").await;

    let (outcome, report) = attempt_graph_augmentation_with_search(
        &fixture.database,
        &fixture.index,
        two_entity_question(),
        &StubSearch::none(),
        &settings(),
    )
    .await;

    let GraphAugmentationOutcome::Succeeded { facts } = outcome else {
        panic!("expected Succeeded, got {outcome:?}");
    };
    assert_eq!(facts.len(), 1, "one path joins the two seeds");
    assert_eq!(
        facts[0].edge_summary(),
        Some("Acme Corp \u{2014}owns\u{2192} Gamma Bridge \u{2014}supplies\u{2192} Beta Works"),
        "the fact carries the readable path with hop directions"
    );
    assert_eq!(facts[0].entity_a_name(), "Acme Corp");
    assert_eq!(facts[0].entity_b_name(), "Beta Works");
    assert_eq!(
        facts[0].relation_type(),
        "owns\u{2192}Gamma Bridge\u{2192}supplies",
        "the relation attribute agrees with the readable text for two forward hops"
    );
    assert_eq!(report.seed_count, 2);
    assert!(report.path_found);
    assert_eq!(report.degree_capped_count, 0);
    assert_eq!(report.node_count, 3, "Acme Corp, Gamma Bridge and Beta Works");
    assert_eq!(report.edge_count, 2, "owns and supplies");
    assert_eq!(
        sorted(report.chunk_candidates),
        sorted(vec![
            format!("{}:0", id(901)),
            format!("{}:0", id(902)),
            format!("{}:0", id(903)),
        ]),
        "the chunks of the entities on the path"
    );
    fixture.cleanup();
}

/// Behavior 2 and the Task 3 decision (`paths-only`): seeds with no path between them.
#[tokio::test]
async fn seeds_with_no_path_between_them_yield_no_facts_and_no_chunk_candidates() {
    let fixture = Fixture::new("cutover-no-path").await;

    let (outcome, report) = attempt_graph_augmentation_with_search(
        &fixture.database,
        &fixture.index,
        "Compare Delta Solo and Echo Island.",
        &StubSearch::none(),
        &settings(),
    )
    .await;

    let GraphAugmentationOutcome::Succeeded { facts } = outcome else {
        panic!("seeds with no path is a success with no facts, got {outcome:?}");
    };
    assert!(facts.is_empty());
    assert_eq!(report.seed_count, 2);
    assert!(!report.path_found);
    assert!(
        report.chunk_candidates.is_empty(),
        "paths-only: the seeds' own source chunks are not candidates, got {:?}",
        report.chunk_candidates
    );
    assert_eq!((report.node_count, report.edge_count), (0, 0));
    assert_eq!(
        report.seed_document_ids,
        vec![id(904), id(905)],
        "the seeds' source documents are still reported"
    );
    fixture.cleanup();
}

/// Behavior 3, first half: no mention means no model call and no match.
#[tokio::test]
async fn a_question_with_no_capitalised_mention_matches_nothing_and_embeds_nothing() {
    let fixture = Fixture::new("cutover-no-mention").await;
    let embedder = Arc::new(CountingEmbedder {
        calls: AtomicUsize::new(0),
    });
    let provider: Arc<dyn EmbeddingProvider> = embedder.clone();

    let (outcome, report) = attempt_graph_augmentation(
        &fixture.database,
        &fixture.index,
        "what is the weather like today?",
        &provider,
        &settings(),
    )
    .await;

    assert!(matches!(outcome, GraphAugmentationOutcome::NoMatchFound), "{outcome:?}");
    assert_eq!(report, Default::default());
    assert_eq!(embedder.calls.load(Ordering::SeqCst), 0, "no mention, no embedding call");
    fixture.cleanup();
}

/// Behavior 3, second half: a mention that no name and no vector matches.
#[tokio::test]
async fn a_mention_with_no_name_and_no_vector_match_is_no_match_found() {
    let fixture = Fixture::new("cutover-no-vector").await;
    let search = StubSearch::none();

    let (outcome, report) = attempt_graph_augmentation_with_search(
        &fixture.database,
        &fixture.index,
        "Who is Zorblax Quux?",
        &search,
        &settings(),
    )
    .await;

    assert!(matches!(outcome, GraphAugmentationOutcome::NoMatchFound), "{outcome:?}");
    assert_eq!(report.seed_count, 0);
    assert_eq!(search.calls(), 1, "the unmatched mention went to the vector search");
    fixture.cleanup();
}

#[tokio::test]
async fn a_vector_matched_mention_becomes_a_seed_and_can_join_a_path() {
    let fixture = Fixture::new("cutover-vector-seed").await;
    // "Acme Group" is no entity name; the vector search says it is Acme Corp.
    let search = StubSearch::with_hit("Acme Group", 1, 0.9);

    let (outcome, report) = attempt_graph_augmentation_with_search(
        &fixture.database,
        &fixture.index,
        "Does Acme Group work with Beta Works?",
        &search,
        &settings(),
    )
    .await;

    assert!(matches!(outcome, GraphAugmentationOutcome::Succeeded { .. }), "{outcome:?}");
    assert_eq!(report.seed_count, 2);
    assert!(report.path_found);
    fixture.cleanup();
}

#[tokio::test]
async fn a_seed_matching_failure_is_attempted_and_failed() {
    let fixture = Fixture::new("cutover-search-fails").await;

    let (outcome, report) = attempt_graph_augmentation_with_search(
        &fixture.database,
        &fixture.index,
        "Who is Zorblax Quux?",
        &StubSearch::failing(),
        &settings(),
    )
    .await;

    let GraphAugmentationOutcome::AttemptedAndFailed { reason } = outcome else {
        panic!("a failed search must not look like an empty success, got {outcome:?}");
    };
    assert!(reason.contains("injected vector search failure"), "{reason}");
    assert_eq!(report, Default::default());
    fixture.cleanup();
}

#[tokio::test]
async fn the_configured_seed_cap_limits_the_seeds_a_question_can_use() {
    let fixture = Fixture::new("cutover-seed-cap").await;
    let one_seed = GraphSettings {
        max_seeds: 1,
        ..settings()
    };

    let (_, report) = attempt_graph_augmentation_with_search(
        &fixture.database,
        &fixture.index,
        two_entity_question(),
        &StubSearch::none(),
        &one_seed,
    )
    .await;

    assert_eq!(report.seed_count, 1);
    assert!(!report.path_found, "one seed cannot be joined to another");
    fixture.cleanup();
}

#[tokio::test]
async fn the_configured_degree_cap_drops_a_path_through_a_hub() {
    let fixture = Fixture::new("cutover-degree-cap").await;
    // Gamma Bridge has degree 2, so a cap of 1 makes it a hub.
    let strict = GraphSettings {
        degree_cap: 1,
        ..settings()
    };

    let (outcome, report) = attempt_graph_augmentation_with_search(
        &fixture.database,
        &fixture.index,
        two_entity_question(),
        &StubSearch::none(),
        &strict,
    )
    .await;

    let GraphAugmentationOutcome::Succeeded { facts } = outcome else {
        panic!("expected Succeeded, got {outcome:?}");
    };
    assert!(facts.is_empty());
    assert!(!report.path_found);
    assert_eq!(report.degree_capped_count, 1);
    assert_eq!(report.seed_count, 2);
    fixture.cleanup();
}

#[tokio::test]
async fn an_empty_graph_index_is_no_match_before_any_search_or_store_read() {
    let path = temp_path("cutover-empty-index");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let search = StubSearch::with_hit("Acme Corp", 1, 0.9);

    let (outcome, report) = attempt_graph_augmentation_with_search(
        &database,
        &GraphIndex::empty(),
        two_entity_question(),
        &search,
        &settings(),
    )
    .await;

    assert!(matches!(outcome, GraphAugmentationOutcome::NoMatchFound), "{outcome:?}");
    assert_eq!(report, Default::default());
    assert_eq!(search.calls(), 0, "an empty graph never reaches the vector search");
    drop(database);
    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn graph_settings_select_the_seed_and_path_settings() {
    let configured = GraphSettings {
        seed_match_min_score: 0.7,
        max_hop_cap: 2,
        max_seeds: 4,
        mention_vector_top_k: 2,
        degree_cap: 20,
        max_path_facts: 5,
        max_graph_chunk_candidates: 6,
    };

    let seeds = configured.seed_settings();
    assert_eq!(
        (seeds.max_seeds, seeds.mention_vector_top_k, seeds.seed_match_min_score),
        (4, 2, 0.7)
    );
    let paths = configured.path_settings();
    assert_eq!(
        (paths.degree_cap, paths.max_path_facts, paths.max_graph_chunk_candidates),
        (20, 5, 6)
    );
}

// ---- the production port --------------------------------------------------------------------

#[tokio::test]
async fn the_production_port_returns_path_facts_and_the_d79_fields_from_the_snapshot_index() {
    let fixture = Fixture::new("cutover-port").await;
    let Fixture {
        database,
        index,
        path,
    } = fixture;
    let port = ProductionGraphQueryPort {
        database: database.clone(),
        graph_settings: settings(),
        graph_index: Arc::new(index),
        embedder: Arc::new(CountingEmbedder {
            calls: AtomicUsize::new(0),
        }),
    };
    let cancel = CancellationToken::new();

    let output = port
        .query_graph(two_entity_question(), &[0.0; 2048], &cancel)
        .await
        .unwrap();

    assert_eq!(output.facts.len(), 1);
    assert_eq!(output.seed_count, 2);
    assert!(output.path_found);
    assert_eq!((output.node_count, output.edge_count), (3, 2));
    assert_eq!(output.seed_document_ids, vec![id(901), id(902)]);
    assert_eq!(output.chunk_candidates.len(), 3);
    drop(database);
    let _ = std::fs::remove_dir_all(path);
}

// ---- the ExtractGraphContext node -----------------------------------------------------------

fn path_output() -> GraphQueryOutput {
    let fact = crate::graph::context_strategy::GraphFact::new(
        "Acme Corp",
        "owns\u{2192}Gamma Bridge\u{2192}supplies",
        "Beta Works",
        Some("Acme Corp \u{2014}owns\u{2192} Gamma Bridge \u{2014}supplies\u{2192} Beta Works"),
        0.9,
    );
    GraphQueryOutput {
        facts: vec![GraphFactBlock { fact }],
        node_count: 3,
        edge_count: 2,
        seed_count: 2,
        path_found: true,
        degree_capped_count: 1,
        seed_document_ids: vec![id(901), id(902)],
        chunk_candidates: vec![format!("{}:0", id(901)), format!("{}:0", id(903))],
    }
}

fn node_with(
    port: Arc<FakeGraphQueryPort>,
    graph_operation_timeout_ms: u64,
) -> workflow::nodes::ExtractGraphContextNode {
    workflow::nodes::ExtractGraphContextNode::new(
        Some(Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 8]))),
        Some(port),
    )
    .with_timeouts(1_000, graph_operation_timeout_ms)
}

fn new_context(question: &str) -> WorkflowContext {
    let session = "00000000-0000-4000-8000-000000000141";
    WorkflowContext::new(
        session.into(),
        "trace-cutover".into(),
        &test_query_request(question, session),
    )
}

#[tokio::test]
async fn the_node_records_the_seed_and_path_fields_and_path_counts_on_a_successful_query() {
    let port = Arc::new(FakeGraphQueryPort::success_output(path_output()));
    let node = node_with(Arc::clone(&port), 1_000);
    let mut ctx = new_context(two_entity_question());

    node.run(&mut ctx, &CancellationToken::new()).await.unwrap();

    assert_eq!(ctx.graph_facts.len(), 1);
    assert_eq!(ctx.graph_seed_count, 2);
    assert!(ctx.graph_path_found);
    assert_eq!(ctx.graph_degree_capped_count, 1);
    assert_eq!(ctx.graph_seed_document_ids, vec![id(901), id(902)]);
    assert_eq!(
        ctx.graph_chunk_candidates,
        vec![format!("{}:0", id(901)), format!("{}:0", id(903))]
    );
    assert_eq!(
        (ctx.graph_node_count, ctx.graph_edge_count),
        (3, 2),
        "the presence counters are the path entities and relations, not the fact endpoints"
    );
    assert!(
        ctx.graph_context.contains("Acme Corp \u{2014}owns\u{2192} Gamma Bridge"),
        "the context line shows the directional path: {}",
        ctx.graph_context
    );
}

#[tokio::test]
async fn the_node_records_seeds_that_found_no_path_and_reports_no_facts() {
    let port = Arc::new(FakeGraphQueryPort::success_output(GraphQueryOutput {
        seed_count: 2,
        seed_document_ids: vec![id(904), id(905)],
        ..GraphQueryOutput::default()
    }));
    let node = node_with(port, 1_000);
    let mut ctx = new_context("Compare Delta Solo and Echo Island.");

    node.run(&mut ctx, &CancellationToken::new()).await.unwrap();

    assert!(ctx.graph_facts.is_empty());
    assert_eq!(ctx.graph_seed_count, 2, "seeds are recorded even with no path");
    assert!(!ctx.graph_path_found);
    assert_eq!(ctx.graph_seed_document_ids, vec![id(904), id(905)]);
    assert!(ctx.graph_chunk_candidates.is_empty());
    assert_eq!((ctx.graph_node_count, ctx.graph_edge_count), (0, 0));
    assert!(
        ctx.notices.iter().any(|n| n.code == "GRAPH_UNAVAILABLE"),
        "an empty result keeps the existing unavailable notice"
    );
}

/// Behavior 4: graph-off returns before the port is asked anything.
#[tokio::test]
async fn graph_off_returns_before_the_port_and_leaves_every_new_field_at_its_default() {
    let port = Arc::new(FakeGraphQueryPort::success_output(path_output()));
    let node = node_with(Arc::clone(&port), 1_000);
    let mut ctx = new_context(two_entity_question());
    ctx.disable_graph_context = true;

    node.run(&mut ctx, &CancellationToken::new()).await.unwrap();

    assert_eq!(port.calls(), 0, "no mention extraction and no index access");
    assert_eq!(ctx.graph_seed_count, 0);
    assert!(!ctx.graph_path_found);
    assert_eq!(ctx.graph_degree_capped_count, 0);
    assert!(ctx.graph_seed_document_ids.is_empty());
    assert!(ctx.graph_chunk_candidates.is_empty());
    assert!(ctx.graph_facts.is_empty());
    assert!(ctx.notices.iter().any(|n| n.code == "GRAPH_ABLATION"));
}

/// The node copies the question for the port only after the ablation return, and calls the port
/// from one place. (The variants seeding and the variant-zero embedding before the return are
/// existing behaviour that makes no graph lookup.)
#[test]
fn the_node_copies_the_question_for_the_port_only_after_the_ablation_return() {
    let source = include_str!("../workflow/nodes/graph_context.rs");
    let ablation = source
        .find("if ctx.disable_graph_context {")
        .expect("the ablation early return");
    let question_for_port = source
        .find("let question = ctx.original_query.clone();")
        .expect("the node copies the original question for the port");
    let port_call = source
        .find("graph_port.query_graph(")
        .expect("the node calls the graph port");
    assert!(
        ablation < question_for_port && question_for_port < port_call,
        "order must be ablation return ({ablation}), question copy ({question_for_port}), port call ({port_call})"
    );
    assert_eq!(
        source.matches("graph_port.query_graph(").count(),
        1,
        "the port is called at exactly one place"
    );
}

/// Behavior: the port is given what the user wrote, not a reformulated variant.
#[tokio::test]
async fn the_node_passes_the_original_question_to_the_port_not_a_variant() {
    let port = Arc::new(FakeGraphQueryPort::success_output(GraphQueryOutput::default()));
    let node = node_with(Arc::clone(&port), 1_000);
    let mut ctx = new_context("Original Question about Acme Corp?");
    ctx.variants = vec![
        "rewritten variant one".to_string(),
        "rewritten variant two".to_string(),
    ];

    node.run(&mut ctx, &CancellationToken::new()).await.unwrap();

    assert_eq!(
        port.questions(),
        vec!["Original Question about Acme Corp?".to_string()]
    );
}

/// Behavior 5: a graph operation over its budget degrades the query and does not fail it.
#[tokio::test]
async fn a_graph_timeout_is_a_non_fatal_notice_and_leaves_every_new_field_at_its_default() {
    let node = node_with(Arc::new(FakeGraphQueryPort::stall()), 20);
    let mut ctx = new_context(two_entity_question());

    node.run(&mut ctx, &CancellationToken::new()).await.unwrap();

    assert!(
        ctx.notices.iter().any(|n| n.code == "GRAPH_TIMEOUT"),
        "a timeout still emits GRAPH_TIMEOUT"
    );
    assert_eq!(ctx.graph_seed_count, 0);
    assert!(!ctx.graph_path_found);
    assert!(ctx.graph_chunk_candidates.is_empty());
    assert!(ctx.graph_facts.is_empty());
}

// ---- the removed seeding and the paths-only rule ---------------------------------------------

fn function_source<'a>(source: &'a str, start: &str, end: &str) -> &'a str {
    let from = source.find(start).unwrap_or_else(|| panic!("{start} must exist"));
    let to = source[from..]
        .find(end)
        .map(|offset| from + offset)
        .unwrap_or_else(|| panic!("{end} must follow {start}"));
    &source[from..to]
}

/// The assumption-delta invariant: every graph-on query goes through `match_seeds` and
/// `find_seed_paths`, and nothing keeps the old single-nearest-entity lookup.
#[test]
fn no_production_code_keeps_the_old_single_nearest_entity_lookup() {
    let service = include_str!("../service.rs");
    assert_eq!(
        service.matches(concat!("limit", "(1)")).count(),
        0,
        "service.rs must not hold a single-result nearest-entity query"
    );
    let augmentation = function_source(
        service,
        "pub async fn attempt_graph_augmentation(",
        "/// Production adapter implementing `QueryEmbeddingPort`",
    );
    for forbidden in ["nearest_to", "fetch_neighborhood", "narrow_via_cypher", "name_vector"] {
        assert!(
            !augmentation.contains(forbidden),
            "the graph augmentation must not use {forbidden}"
        );
    }
    assert!(augmentation.contains("match_seeds("), "seeds come from mention matching");
    assert!(augmentation.contains("find_seed_paths("), "facts come from seed-to-seed paths");
}

/// The boost decision `paths-only`: the seeds' own chunks are never the candidates.
#[test]
fn the_seed_chunk_fallback_is_not_called_from_the_service_or_the_workflow() {
    for (name, source) in [
        ("service.rs", include_str!("../service.rs")),
        ("workflow/mod.rs", include_str!("../workflow/mod.rs")),
        ("workflow/ports.rs", include_str!("../workflow/ports.rs")),
        (
            "workflow/nodes/graph_context.rs",
            include_str!("../workflow/nodes/graph_context.rs"),
        ),
    ] {
        assert!(
            !source.contains("seed_chunk_candidates"),
            "{name} must not use the seed-chunk fallback that paths-only rejected"
        );
    }
}

// ---- how a path fact reaches the prompt -------------------------------------------------------

/// One two-hop path fact over three named entities, as `build_paths` builds it.
///
/// `along[i]` says whether hop `i` is stored in the direction the path runs: the first hop from
/// `start` to `via`, the second from `via` to `end`.
fn two_hop_fact(names: [&str; 3], relations: [&str; 2], along: [bool; 2]) -> GraphFactBlock {
    let [start, via, end] = names;
    let record = |n: u128, name: &str| crate::graph::index::EntityRecord {
        entity_id: id(n),
        name: name.into(),
        source_chunk_ids: vec![],
    };
    let (first_source, first_target) = if along[0] { (1, 3) } else { (3, 1) };
    let (second_source, second_target) = if along[1] { (3, 2) } else { (2, 3) };
    let index = GraphIndex::from_parts(
        vec![record(1, start), record(2, end), record(3, via)],
        &[
            (id(first_source), id(first_target)),
            (id(second_source), id(second_target)),
        ],
    );
    let edge = |n: u32, source: u128, target: u128, relation: &str| EdgeRow {
        edge_id: format!("edge-{n}"),
        source: id(source),
        target: id(target),
        relation: relation.to_string(),
        weight: 1.0,
    };
    let seed = |n: u128, name: &str| Seed {
        entity_id: id(n),
        name: name.to_string(),
        match_kind: MatchKind::Exact,
        score: 1.0,
        degree: index.degree(&id(n)),
    };
    let result = build_paths(
        &index,
        &[seed(1, start), seed(2, end)],
        &[
            edge(0, first_source, first_target, relations[0]),
            edge(1, second_source, second_target, relations[1]),
        ],
        &PathSettings {
            degree_cap: DEGREE_CAP,
            max_path_facts: MAX_PATH_FACTS,
            max_graph_chunk_candidates: 8,
        },
    );
    let fact = result.facts.into_iter().next().expect("one path joins the seeds");
    GraphFactBlock { fact }
}

/// Penn State <-ASSOCIATED_WITH- Sherrone Moore -SUBSTITUTE_FOR-> Jim Harbaugh: the first hop is
/// stored against the path direction, the second along it (a path from the offline probe).
fn penn_state_fact() -> GraphFactBlock {
    two_hop_fact(
        ["Penn State", "Sherrone Moore", "Jim Harbaugh"],
        ["ASSOCIATED_WITH", "SUBSTITUTE_FOR"],
        [false, true],
    )
}

fn one_evidence_block() -> Vec<crate::prompt::EvidenceBlock> {
    vec![crate::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "chunk-1".into(),
        document_id: "doc-1".into(),
        chunk_index: 0,
        title: Some("Title".into()),
        section_path: None,
        content_type: Some("text/markdown".into()),
        provenance: "p".into(),
        text: "Evidence text".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
        graph_boosted: false,
        evidence_meta: None,
    }]
}

/// The prompt shows the model the path with the direction of every hop. A chain of relation
/// names alone (`r1->X->r2`) would state that both hops point along the path.
#[tokio::test]
async fn a_two_hop_path_fact_reaches_the_prompt_with_the_direction_of_every_hop() {
    let facts = vec![penn_state_fact()];

    let packed = crate::prompt::pack_evidence_and_graph_prompt(
        "Who replaced Harbaugh?",
        &one_evidence_block(),
        &facts,
        1.0,
        4096,
        512,
        &CancellationToken::new(),
    )
    .await
    .unwrap();

    assert!(
        packed.prompt.contains(
            "Penn State \u{2190}ASSOCIATED_WITH\u{2014} Sherrone Moore \u{2014}SUBSTITUTE_FOR\u{2192} Jim Harbaugh"
        ),
        "the prompt must carry the directional path text: {}",
        packed.prompt
    );
    assert!(
        packed
            .prompt
            .contains("relation=\"ASSOCIATED_WITH\u{2190}Sherrone Moore\u{2192}SUBSTITUTE_FOR\""),
        "the relation attribute must point the first hop backwards, as the text does: {}",
        packed.prompt
    );
    assert_eq!(packed.graph_facts.len(), 1);
}

/// Rendering the directional text instead of the relation chain costs a few more tokens per
/// fact. The confirmed cap of 8 (06.3.4.1-13) was derived from the old rendering (one forward
/// arrow in the relation chain for both hops, and the chain as the block body) at a measured p95
/// of 69 tokens per fact, so the cap must still follow from the new cost.
#[test]
fn the_directional_path_text_keeps_the_confirmed_path_fact_cap() {
    use crate::graph::context_strategy::{ContextAssemblyStrategy, GraphFact};

    let block_tokens = |fact: &GraphFact, strategy: ContextAssemblyStrategy| {
        let block = format!(
            "<GRAPH_FACT entity_a=\"{}\" relation=\"{}\" entity_b=\"{}\" score=\"{:.4}\">\n{}\n</GRAPH_FACT>\n\n",
            fact.entity_a_name(),
            fact.relation_type(),
            fact.entity_b_name(),
            fact.score,
            strategy.assemble(fact)
        );
        tiktoken_rs::cl100k_base_singleton()
            .encode_with_special_tokens(&block)
            .len()
    };

    let measured_p95 = 69_usize;
    let samples = [
        penn_state_fact(),
        two_hop_fact(
            ["The Verge", "Snap", "TechCrunch"],
            ["reported_by", "REPORTED_TO"],
            [true, true],
        ),
    ];
    let mut worst_increase = 0_usize;
    for sample in &samples {
        let new = &sample.fact;
        // The block as it was measured: forward arrows for both hops, and the chain as the body.
        let old = GraphFact::new(
            new.entity_a_name(),
            &new.relation_type().replace('\u{2190}', "\u{2192}"),
            new.entity_b_name(),
            None,
            new.score,
        );
        let before = block_tokens(&old, ContextAssemblyStrategy::SourceChunks);
        let after = block_tokens(new, ContextAssemblyStrategy::PrecomputedSemantics);
        worst_increase = worst_increase.max(after.saturating_sub(before));
    }

    assert!(
        worst_increase <= 8,
        "the directional text may add at most a few tokens per fact, added {worst_increase}"
    );
    assert_eq!(
        crate::graph::paths::derive_max_path_facts(
            8192,
            2048,
            (measured_p95 + worst_increase) as u32
        ),
        Some(MAX_PATH_FACTS),
        "the cap of 8 still follows from the p95 plus the added tokens ({worst_increase})"
    );
}
