//! Pins for the request-level opt-out from configured default levers (06.4 D-198) and for the
//! configured graph-context default (06.4 D-207).
//!
//! Every test sends a request through the real service admission and workflow over the existing
//! fakes, and reads the effective lever set or the graph state back from the response. The
//! service fixture is shared with [`super::levers_pins`].

use engine::config::{EffectiveRagSettings, GraphConfigSettings, Settings};
use engine::pb::lancet::v1::{
    AnswerBasis, Lever, Notice, NoticeCode, NoticeSeverity, QueryRagRequest,
};
use engine::testkit::test_query_request;
use engine::workflow::{derive_degraded_mode, notice};

use super::levers_pins::{
    default_lever_notices, error_kind_of, fresh_no_lever_request, request_without_evidence,
    service_with_default_levers, BINARY, RERANK,
};

/// The configured defaults that every `d198_` test starts from.
const DEFAULTS: &[&str] = &["rerank", "evidence_metadata"];

/// A request that names no lever and carries `disable_default_levers` as given.
fn no_lever_request(disable_default_levers: Option<bool>) -> QueryRagRequest {
    QueryRagRequest {
        disable_default_levers,
        ..fresh_no_lever_request()
    }
}

#[tokio::test]
async fn d198_opt_out_with_no_lever_runs_no_lever() {
    // Both defaults are available: without the opt-out they would run, so an empty echo proves
    // the opt-out removed them.
    let (path, service) =
        service_with_default_levers("d198-opt-out-available", DEFAULTS, true, true).await;
    let response = super::execute_query_rag(&service, no_lever_request(Some(true)))
        .await
        .expect("a lever-free request is admitted");
    assert!(
        response.snapshot.expect("a snapshot").levers.is_empty(),
        "the opt-out runs no configured default"
    );
    assert!(
        default_lever_notices(&response.notices).is_empty(),
        "nothing was dropped, so no code-24 notice: {:?}",
        response.notices
    );
    let _ = std::fs::remove_dir_all(path);

    // Both defaults are unavailable: without the opt-out each would be dropped with a code-24
    // notice, so no notice proves the opt-out never consulted the defaults at all.
    let (path, service) =
        service_with_default_levers("d198-opt-out-unavailable", DEFAULTS, false, false).await;
    let response = super::execute_query_rag(&service, no_lever_request(Some(true)))
        .await
        .expect("a lever-free request is admitted");
    assert!(response.snapshot.expect("a snapshot").levers.is_empty());
    assert!(
        default_lever_notices(&response.notices).is_empty(),
        "the opt-out drops no default, so it carries no code-24 notice: {:?}",
        response.notices
    );
    assert!(
        !response
            .notices
            .iter()
            .any(|notice| notice.typed_code == NoticeCode::DefaultLeverUnavailable as i32),
        "no DEFAULT_LEVER_UNAVAILABLE notice of any kind"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn d198_named_levers_stay_exact_with_the_opt_out() {
    let (path, service) =
        service_with_default_levers("d198-named-exact", DEFAULTS, true, true).await;
    for disable_default_levers in [Some(true), Some(false), None] {
        let response = super::execute_query_rag(
            &service,
            QueryRagRequest {
                disable_default_levers,
                ..request_without_evidence(BINARY, &uuid::Uuid::new_v4().to_string())
            },
        )
        .await
        .expect("binary_answer_format needs no resource");
        assert_eq!(
            response.snapshot.expect("a snapshot").levers,
            vec![Lever::BinaryAnswerFormat as i32],
            "opt-out {disable_default_levers:?}: a named lever runs alone, never the union"
        );
    }
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn d198_absent_field_keeps_the_configured_defaults() {
    let (path, service) =
        service_with_default_levers("d198-absent-field", DEFAULTS, true, true).await;
    let response = super::execute_query_rag(&service, no_lever_request(None))
        .await
        .expect("the defaults are available, so the request is admitted");
    assert_eq!(
        response.snapshot.expect("a snapshot").levers,
        vec![Lever::Rerank as i32, Lever::EvidenceMetadata as i32],
        "an absent field is today's behaviour: the configured defaults run"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn d198_explicit_false_keeps_the_configured_defaults() {
    let (path, service) =
        service_with_default_levers("d198-explicit-false", DEFAULTS, true, true).await;
    let response = super::execute_query_rag(&service, no_lever_request(Some(false)))
        .await
        .expect("the defaults are available, so the request is admitted");
    assert_eq!(
        response.snapshot.expect("a snapshot").levers,
        vec![Lever::Rerank as i32, Lever::EvidenceMetadata as i32],
        "an explicit false is the same as an absent field"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn d198_named_unavailable_lever_is_still_refused() {
    // No lever reranker is wired: naming `rerank` fails closed, with or without the opt-out.
    let (path, service) =
        service_with_default_levers("d198-named-unavailable", DEFAULTS, false, true).await;
    for disable_default_levers in [Some(true), Some(false), None] {
        let refused = super::execute_query_rag(
            &service,
            QueryRagRequest {
                disable_default_levers,
                ..request_without_evidence(RERANK, &uuid::Uuid::new_v4().to_string())
            },
        )
        .await
        .expect_err("a named lever whose resource is absent is refused, never dropped");
        assert_eq!(refused.code(), tonic::Code::InvalidArgument);
        assert_eq!(
            error_kind_of(&refused),
            "lever_unavailable",
            "opt-out {disable_default_levers:?}"
        );
    }
    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// The configured graph-context default (06.4 D-207)
// ---------------------------------------------------------------------------

/// A service whose `[engine.graph] context_default_enabled` is `default_enabled`, over the shared
/// fixture, with no configured default lever and no lever resource.
async fn service_with_graph_default(
    name: &str,
    default_enabled: bool,
) -> (String, crate::service::LancetServiceImpl) {
    // Production builds the prompt tokenizer before serving (D-93). A test process that reaches
    // `AssemblePrompt` first would pay that one-off cost inside the node's budget and time out.
    let _ = engine::prompt::warm_prompt_tokenizer();
    let (path, mut service) = service_with_default_levers(name, &[], false, false).await;
    service.effective_settings.graph.context_default_enabled = default_enabled;
    (path, service)
}

/// A request that retrieves evidence, names `levers`, and carries `disable_graph_context` as given.
fn graph_request(disable_graph_context: Option<bool>, levers: &[i32]) -> QueryRagRequest {
    QueryRagRequest {
        disable_graph_context,
        levers: levers.to_vec(),
        ..test_query_request("reranker evidence", &uuid::Uuid::new_v4().to_string())
    }
}

/// The notices of `notices` that carry `code`.
fn with_code(notices: &[Notice], code: NoticeCode) -> Vec<&Notice> {
    notices
        .iter()
        .filter(|notice| notice.typed_code == code as i32)
        .collect()
}

#[tokio::test]
async fn d207_absent_field_under_a_default_off_config_runs_graph_off_with_code_25() {
    let (path, service) = service_with_graph_default("d207-absent-default-off", false).await;
    let response = super::execute_query_rag(&service, graph_request(None, &[]))
        .await
        .expect("a default request is admitted");

    let off = with_code(&response.notices, NoticeCode::GraphDisabledByConfig);
    assert_eq!(off.len(), 1, "exactly one code-25 notice: {:?}", response.notices);
    assert_eq!(off[0].code, "GRAPH_DISABLED_BY_CONFIG");
    assert_eq!(off[0].severity, NoticeSeverity::Info as i32);
    assert_eq!(off[0].message, "Graph context disabled by configured default");
    assert!(
        with_code(&response.notices, NoticeCode::GraphAblation).is_empty(),
        "an absent field is not a caller ablation: {:?}",
        response.notices
    );
    assert!(
        with_code(&response.notices, NoticeCode::GraphUnavailable).is_empty(),
        "the graph was never queried, so it cannot be unavailable: {:?}",
        response.notices
    );
    assert_eq!(
        response.answer_basis,
        AnswerBasis::Retrieval as i32,
        "the run is grounded, so degraded_mode below reads the notices alone"
    );
    assert!(
        !derive_degraded_mode(&response.notices, AnswerBasis::Retrieval),
        "code 25 is request-shape information, not a degradation"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn d207_explicit_false_runs_the_graph_node() {
    let (path, service) = service_with_graph_default("d207-explicit-false", false).await;
    let response = super::execute_query_rag(&service, graph_request(Some(false), &[]))
        .await
        .expect("an explicit false is admitted");
    assert!(
        with_code(&response.notices, NoticeCode::GraphDisabledByConfig).is_empty(),
        "an explicit false overrides the configured default: {:?}",
        response.notices
    );
    assert!(
        with_code(&response.notices, NoticeCode::GraphAblation).is_empty(),
        "an explicit false is not an ablation: {:?}",
        response.notices
    );
    // The fixture holds no graph, so a node that ran its query reports the empty result.
    assert_eq!(
        with_code(&response.notices, NoticeCode::GraphUnavailable).len(),
        1,
        "the graph node ran and found nothing: {:?}",
        response.notices
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn d207_explicit_true_keeps_graph_ablation_and_no_code_25() {
    for default_enabled in [false, true] {
        let (path, service) =
            service_with_graph_default("d207-explicit-true", default_enabled).await;
        let response = super::execute_query_rag(&service, graph_request(Some(true), &[]))
            .await
            .expect("an explicit true is admitted");
        let ablation = with_code(&response.notices, NoticeCode::GraphAblation);
        assert_eq!(
            ablation.len(),
            1,
            "default_enabled {default_enabled}: GRAPH_ABLATION as before: {:?}",
            response.notices
        );
        assert_eq!(ablation[0].message, "Graph context disabled by caller request");
        assert!(
            with_code(&response.notices, NoticeCode::GraphDisabledByConfig).is_empty(),
            "default_enabled {default_enabled}: the caller chose this, the config did not: {:?}",
            response.notices
        );
        let _ = std::fs::remove_dir_all(path);
    }
}

#[tokio::test]
async fn d207_default_on_config_keeps_the_pre_6_4_request_shape() {
    // The compiled-in default is true: an absent field runs the graph node and carries neither
    // a GRAPH_ABLATION nor a code-25 notice.
    assert!(EffectiveRagSettings::default().graph.context_default_enabled);
    let (path, service) = service_with_graph_default("d207-default-on", true).await;
    let response = super::execute_query_rag(&service, graph_request(None, &[]))
        .await
        .expect("a default request is admitted");
    assert!(with_code(&response.notices, NoticeCode::GraphDisabledByConfig).is_empty());
    assert!(with_code(&response.notices, NoticeCode::GraphAblation).is_empty());
    assert_eq!(
        with_code(&response.notices, NoticeCode::GraphUnavailable).len(),
        1,
        "the graph node ran: {:?}",
        response.notices
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn d207_graph_v2_with_an_absent_field_under_a_default_off_config_is_refused() {
    let (path, service) = service_with_graph_default("d207-graph-v2-absent", false).await;
    let graph_v2 = [Lever::GraphV2 as i32];
    let refused = super::execute_query_rag(&service, graph_request(None, &graph_v2))
        .await
        .expect_err("graph_v2 with the graph resolved off is a contradiction");
    assert_eq!(refused.code(), tonic::Code::InvalidArgument);
    assert_eq!(error_kind_of(&refused), "invalid_lever_combination");
    assert!(
        refused.message().contains("disable_graph_context=false"),
        "the refusal tells the caller how to run graph_v2: {}",
        refused.message()
    );

    // An explicit true is the same contradiction, with the caller's own message.
    let refused = super::execute_query_rag(&service, graph_request(Some(true), &graph_v2))
        .await
        .expect_err("graph_v2 with an explicit ablation is a contradiction");
    assert_eq!(error_kind_of(&refused), "invalid_lever_combination");
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn d207_graph_v2_with_explicit_false_is_admitted() {
    let (path, service) = service_with_graph_default("d207-graph-v2-false", false).await;
    let response = super::execute_query_rag(
        &service,
        graph_request(Some(false), &[Lever::GraphV2 as i32]),
    )
    .await
    .expect("graph_v2 with the graph explicitly on is admitted");
    assert_eq!(
        response.snapshot.expect("a snapshot").levers,
        vec![Lever::GraphV2 as i32]
    );
    assert!(with_code(&response.notices, NoticeCode::GraphDisabledByConfig).is_empty());
    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn d207_startup_refuses_graph_v2_default_levers_with_graph_default_off() {
    fn settings(defaults: &[&str], context_default_enabled: bool) -> Settings {
        let mut settings = Settings::default();
        settings.engine.levers.defaults = defaults.iter().map(|name| (*name).to_owned()).collect();
        settings.engine.graph.context_default_enabled = context_default_enabled;
        settings
    }

    let refused = EffectiveRagSettings::try_from_settings(&settings(&["graph_v2"], false))
        .expect_err("a graph_v2 default beside a default-off graph must stop startup");
    assert!(
        refused.contains("engine.levers.defaults")
            && refused.contains("engine.graph.context_default_enabled"),
        "the error names both keys: {refused}"
    );
    EffectiveRagSettings::try_from_settings(&settings(&["graph_v2"], true))
        .expect("graph_v2 is a valid default while the graph default is on");
    EffectiveRagSettings::try_from_settings(&settings(&["rerank", "evidence_metadata"], false))
        .expect("other default levers do not need the graph");
}

#[test]
fn d207_code_25_is_outside_the_degraded_mode_set() {
    let off = notice(
        NoticeCode::GraphDisabledByConfig,
        "Graph context disabled by configured default",
        NoticeSeverity::Info,
    );
    assert!(
        !derive_degraded_mode(&[off], AnswerBasis::Retrieval),
        "a config-off graph is not a degraded run, like GRAPH_ABLATION"
    );
    let unavailable = notice(
        NoticeCode::GraphUnavailable,
        "Graph query returned no facts for this query",
        NoticeSeverity::Info,
    );
    assert!(
        derive_degraded_mode(&[unavailable], AnswerBasis::Retrieval),
        "the contrast: an unavailable graph still counts"
    );
}

/// The committed operator configuration, read as the engine reads it at startup.
const CONFIG_TOML: &str = include_str!("../../../config/config.toml");
const CONFIG_EXAMPLE_TOML: &str = include_str!("../../../config/config.example.toml");

/// Reads `engine.graph.context_default_enabled` from a TOML document as written, failing when the
/// key is absent instead of falling back to the compiled-in default.
fn file_context_default_enabled(raw: &str) -> bool {
    ::config::Config::builder()
        .add_source(::config::File::from_str(raw, ::config::FileFormat::Toml))
        .build()
        .expect("configuration file must parse as TOML")
        .get::<bool>("engine.graph.context_default_enabled")
        .unwrap_or_else(|error| panic!("engine.graph.context_default_enabled must be present: {error}"))
}

/// D-207 (owner decision, 2026-10-11): the compiled-in default keeps the pre-6.4 request shape,
/// both committed files ship graph context off, and each file passes startup validation as that
/// effective setting. The two-file pin mirrors the one for the default levers (D-157).
#[test]
fn d207_graph_default_is_true_in_code_and_both_files_carry_false() {
    assert!(GraphConfigSettings::default().context_default_enabled);
    assert!(
        EffectiveRagSettings::default().graph.context_default_enabled,
        "the compiled-in default must stay on, so a service built without the file keeps the old request shape"
    );
    for (file_name, raw) in [
        ("config/config.toml", CONFIG_TOML),
        ("config/config.example.toml", CONFIG_EXAMPLE_TOML),
    ] {
        assert!(
            !file_context_default_enabled(raw),
            "{file_name} engine.graph.context_default_enabled must be false (D-207)"
        );
        let settings: Settings = ::config::Config::builder()
            .add_source(::config::File::from_str(raw, ::config::FileFormat::Toml))
            .build()
            .expect("configuration file must parse as TOML")
            .try_deserialize()
            .expect("configuration file must deserialize through Settings");
        let effective = EffectiveRagSettings::try_from_settings(&settings)
            .unwrap_or_else(|error| panic!("{file_name} must pass startup validation: {error}"));
        assert!(
            !effective.graph.context_default_enabled,
            "{file_name} must resolve to a default-off graph"
        );
    }
}
