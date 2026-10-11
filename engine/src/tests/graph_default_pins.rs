//! Pins for the request-level opt-out from configured default levers (06.4 D-198) and for the
//! configured graph-context default (06.4 D-207).
//!
//! Every test sends a request through the real service admission and workflow over the existing
//! fakes, and reads the effective lever set or the graph state back from the response. The
//! service fixture is shared with [`super::levers_pins`].

use engine::pb::lancet::v1::{Lever, NoticeCode, QueryRagRequest};

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
