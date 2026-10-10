//! D-15 bad-input matrix: the enumerated bad-input surface for `query_rag`, proven end to end by
//! [`bad_input_matrix_rejects_and_dispositions_are_stable`] below. One row per input class; this
//! header table is the artifact D-15 asks for, and Phase 6.4 lifts it verbatim as API-contract
//! documentation (06-CONTEXT.md D-15).
//!
//! | Row | Input class | Status | Error kind | Reason (non-rejection rows only) |
//! |---|---|---|---|---|
//! | `empty_query` | empty query string | `InvalidArgument` | `empty_query` | — |
//! | `whitespace_only_query` | whitespace-only query | `InvalidArgument` | `empty_query` | — |
//! | `query_too_long` | query exceeding the configured `query_max_bytes` bound | `InvalidArgument` | `query_too_long` | — |
//! | `malformed_session_id` | syntactically invalid session id | `InvalidArgument` | `invalid_session_id` | — |
//! | `wrong_version_session_id` | syntactically valid UUID, wrong version/variant | `InvalidArgument` | `invalid_session_id` | — |
//! | `invalid_document_id` | malformed document id inside the filter | `InvalidArgument` | `invalid_document_id` | — |
//! | `unsupported_content_type` | unsupported content type inside the filter | `InvalidArgument` | `unsupported_content_type` | — |
//! | `empty_filter_value` | empty/whitespace-only document-id filter value | `InvalidArgument` | `empty_filter_value` | — |
//! | `filter_limit_exceeded_document_ids` | `document_ids` filter exceeds the configured count bound | `InvalidArgument` | `filter_limit_exceeded` | — |
//! | `filter_limit_exceeded_content_types` | `content_types` filter exceeds the configured count bound | `InvalidArgument` | `filter_limit_exceeded` | — |
//! | `unmatched_filter` | a well-formed, valid UUIDv4 `document_ids` filter that names no ingested document | success (not rejected) | n/a | Phase 03 shipped a valid zero-match success branch (the `NO_EVIDENCE` notice); rejecting this would contradict shipped behavior and would remove the abstention signal Phase 6.3's scoring depends on. |
//! | `contradictory_filter` | `document_ids` names the one ingested document but `content_types` names a type it does not have, so no candidate can satisfy both constraints at once | success (not rejected) | n/a | No rejection rule exists in the codebase for a document/content-type combination that cannot both be satisfied, and none is added here; it behaves identically to the unmatched case. |
//! | `invalid_retrieval_mode` | `retrieval_mode` integer outside the four known `RetrievalMode` values (99) | `InvalidArgument` | `invalid_retrieval_mode` | — |
//! | `negative_retrieval_mode` | negative `retrieval_mode` integer (-1) | `InvalidArgument` | `invalid_retrieval_mode` | — |
//! | `retrieval_mode_unspecified_admitted` | `retrieval_mode` 0 (the default), unmatched filter | success (not rejected) | n/a | Every known mode value is admitted; the zero-match filter keeps the row independent of corpus content. |
//! | `retrieval_mode_hybrid_admitted` | `retrieval_mode` 1, unmatched filter | success (not rejected) | n/a | As above. |
//! | `retrieval_mode_dense_only_admitted` | `retrieval_mode` 2, unmatched filter | success (not rejected) | n/a | As above. |
//! | `retrieval_mode_bm25_only_admitted` | `retrieval_mode` 3, unmatched filter | success (not rejected) | n/a | As above. |
//! | `invalid_lever` | `levers` holds an integer outside the declared `Lever` values (99) | `InvalidArgument` | `invalid_levers` | — |
//! | `negative_lever` | `levers` holds a negative integer (-1) | `InvalidArgument` | `invalid_levers` | — |
//! | `duplicate_lever` | `levers` names `binary_answer_format` twice | `InvalidArgument` | `invalid_levers` | — |
//! | `lever_unspecified_member` | `levers` holds `LEVER_UNSPECIFIED` (0) | `InvalidArgument` | `invalid_levers` | — |
//! | `lever_unavailable_rerank` | `levers` names `rerank` and this service holds no lever reranker (D-131; `levers_pins` admits it once one is wired) | `InvalidArgument` | `lever_unavailable` | — |
//! | `lever_unavailable_evidence_metadata` | `levers` names `evidence_metadata` while the snapshot's `DocMetaMap` is empty (D-136; the `levers_metadata_admitted` check below admits it once the snapshot holds metadata) | `InvalidArgument` | `lever_unavailable` | — |
//! | `lever_unavailable_graph_v2` | `levers` names `graph_v2`, whose resource is not wired yet | `InvalidArgument` | `lever_unavailable` | — |
//! | `lever_unavailable_when_mixed_with_an_available_lever` | `levers` names `binary_answer_format` and `rerank` with no lever reranker wired | `InvalidArgument` | `lever_unavailable` | — |
//! | `graph_v2_with_graph_disabled` | `levers` names `graph_v2` and `disable_graph_context` is true (D-165) | `InvalidArgument` | `invalid_lever_combination` | — |
//! | `levers_admitted` | `levers` names `binary_answer_format`, unmatched filter | success (not rejected) | n/a | `binary_answer_format` needs no resource and is admitted; the zero-match filter keeps the row independent of corpus content. |
//! | `levers_metadata_admitted` | `levers` names `evidence_metadata`, unmatched filter, after the service's snapshot is replaced by one whose `DocMetaMap` holds an entry | success (not rejected) | n/a | Run after the table above, on the same service, so the one request is refused on the empty map and admitted on the non-empty one. |
//!
//! **Negative filter bound (not a request-level row).** D-15's enumeration mentions a negative
//! filter bound, but [`DocumentFilter`] carries only two repeated string lists and no numeric
//! field — there is no negative value a caller can put on the request wire. The numeric bounds
//! (`candidate_limit`, `final_limit`, `max_document_ids`, `max_content_types`, the RRF weights,
//! `rrf_k`) are configuration settings, already validated by `RetrievalSettings::validate` and
//! already covered by the existing `invalid_settings` error-kind category (mapped to an internal
//! status, since it identifies an operator misconfiguration rather than a caller input) — no
//! request-level rule is added for a case the request cannot express.
//!
//! **Dense/lexical retrieval non-invocation on a rejecting row is a structural property proven by
//! reading the admission path, not by a mock call counter.** `LancetServiceImpl::query_rag`
//! (`engine/src/service.rs`) calls `QueryRequest::from_values(...).map_err(...)?` before it ever
//! constructs the `mpsc` channel or calls `self.build_production_workflow()` — the method that
//! builds the `ProductionDenseRetrievalPort` / `ProductionBm25RetrievalPort` adapters and hands
//! them to the workflow. The `?` on a rejecting row returns before either is reached, so dense and
//! lexical retrieval are not merely "called zero times" on a rejecting row — they are never
//! constructed. `LancetServiceImpl`'s `nodes: Table` and `bm25_index: Bm25IndexStore` fields are
//! concrete production types (not `Arc<dyn Trait>`), so there is no seam to inject
//! `engine::workflow::ports::FakeDenseRetrievalPort` / `FakeBm25RetrievalPort` at this entry point
//! without adding a production-code seam, which this test-only task does not have scope to add.
//! Constructing those fakes here without ever wiring them to the code under test would read
//! `.calls() == 0` regardless of whether `query_rag` is correct — exactly the kind of test that
//! passes by construction rust-guidelines.md's M-TAUTOLOGICAL-TESTS warns against — so this module
//! does not do that.
//!
//! **The generator *is* independently wired** (`LancetServiceImpl::generator: Arc<dyn
//! Generator>`), so `FakeGenerator::calls()` below is asserted directly: a real, non-tautological
//! proof for that one port — and it stays `0` for all twenty-seven rows, not just the twenty rejecting
//! ones. `WorkflowRunner::run_workflow` (`engine/src/workflow/runner.rs`) skips both
//! `AssemblePrompt` and `GenerateAnswer` whenever `!ctx.allow_model_only` and the retrieval pass
//! left zero evidence — which is exactly what `unmatched_filter`, `contradictory_filter` and the
//! four `retrieval_mode_*_admitted` rows and `levers_admitted` construct. Dense and lexical retrieval, unlike
//! generation, **do** run for those seven rows
//! (`RetrieveHybridNode` is never skipped) — the corpus really is queried and really does come
//! back empty; only the two downstream nodes are skipped.

use std::sync::Arc;

use uuid::Uuid;

use engine::config::EffectiveRagSettings;
use engine::db::DatabaseManager;
use engine::doc_meta::{DocMeta, DocMetaMap};
use engine::generation;
use engine::ingest::{process_job, read_staged_jobs};
use engine::pb::lancet::v1::{
    DocumentFilter, Lever, NoticeCode, QueryRagRequest, RetrievalMode,
};
use engine::rerank;
use engine::testkit::test_query_request;

use super::{configured_service, database_path, stage_document, FakeEmbedder, FakeGenerator};

/// The expected disposition of one matrix row.
enum Outcome {
    /// The row must be rejected with this gRPC status code and this stable error-kind string.
    Reject {
        code: tonic::Code,
        error_kind: &'static str,
    },
    /// The row must succeed and carry the zero-evidence notice.
    Succeed,
}

/// One row of the bad-input matrix: a request and its expected outcome.
struct Row {
    label: &'static str,
    request: QueryRagRequest,
    outcome: Outcome,
}

#[tokio::test]
async fn bad_input_matrix_rejects_and_dispositions_are_stable() {
    let path = database_path("bad-input-matrix");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    // One real, ingested document backs the non-rejection rows so "matches nothing" is a
    // genuine claim about a populated corpus, not a tautology over an empty one.
    let doc_id = Uuid::new_v4().to_string();
    stage_document(
        &database,
        &doc_id,
        b"# Matrix Document\n\nContent backing the D-15 bad-input matrix's non-rejection rows.",
    )
    .await;
    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    // Reduce max_content_types below the 3 supported values so the content-type-limit row can
    // exceed the bound with real, distinct, valid content types instead of an unreachable
    // duplicate (only 3 valid content-type strings exist system-wide; the default bound of 16
    // could never be exceeded by unique valid values).
    let mut effective_settings = EffectiveRagSettings::default();
    effective_settings.retrieval.max_content_types = 2;
    let query_max_bytes = effective_settings.retrieval.query_max_bytes;
    let max_document_ids = effective_settings.retrieval.max_document_ids;

    // Never consumed: WorkflowRunner::run_workflow skips both AssemblePrompt and GenerateAnswer
    // when evidence is empty and allow_model_only is false (the default), which is exactly what
    // every non-rejection row below constructs. A response queued here would only be reached if
    // that skip regressed — the response's placeholder text says so directly.
    let fake_gen = Arc::new(FakeGenerator::new(Ok(generation::ModelOutput {
        answer: "Should not be called — zero evidence must skip generation.".into(),
        cited_evidence_ids: vec![],
        answer_basis: generation::AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        final_answer: None,
        usage: None,
    })));
    let reranker = Arc::new(rerank::NoOpReranker::new());

    let service = configured_service(
        &database,
        effective_settings,
        Arc::new(FakeEmbedder),
        fake_gen.clone() as Arc<dyn generation::Generator>,
        reranker,
    )
    .await;

    let oversized_query = "a".repeat(query_max_bytes + 1);
    let too_many_document_ids: Vec<String> = (0..=max_document_ids)
        .map(|_| Uuid::new_v4().to_string())
        .collect();

    let rows = vec![
        Row {
            label: "empty_query",
            request: test_query_request("", "00000000-0000-4000-8000-000000000001"),
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "empty_query",
            },
        },
        Row {
            label: "whitespace_only_query",
            request: test_query_request("   \t  ", "00000000-0000-4000-8000-000000000002"),
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "empty_query",
            },
        },
        Row {
            label: "query_too_long",
            request: test_query_request(&oversized_query, "00000000-0000-4000-8000-000000000003"),
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "query_too_long",
            },
        },
        Row {
            label: "malformed_session_id",
            request: test_query_request("valid query", "not-a-uuid"),
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_session_id",
            },
        },
        Row {
            label: "wrong_version_session_id",
            // Syntactically valid UUID (version 1, RFC4122 variant) — parses, but the wrong
            // version, which the session-id check rejects identically to a malformed string.
            request: test_query_request("valid query", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_session_id",
            },
        },
        Row {
            label: "invalid_document_id",
            request: QueryRagRequest {
                query: "valid query".into(),
                session_id: "00000000-0000-4000-8000-000000000004".into(),
                filter: Some(DocumentFilter {
                    document_ids: vec!["not-a-document-id".into()],
                    content_types: vec![],
                }),
                ..Default::default()
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_document_id",
            },
        },
        Row {
            label: "unsupported_content_type",
            request: QueryRagRequest {
                query: "valid query".into(),
                session_id: "00000000-0000-4000-8000-000000000005".into(),
                filter: Some(DocumentFilter {
                    document_ids: vec![],
                    content_types: vec!["text/html".into()],
                }),
                ..Default::default()
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "unsupported_content_type",
            },
        },
        Row {
            label: "empty_filter_value",
            request: QueryRagRequest {
                query: "valid query".into(),
                session_id: "00000000-0000-4000-8000-000000000006".into(),
                filter: Some(DocumentFilter {
                    document_ids: vec!["   ".into()],
                    content_types: vec![],
                }),
                ..Default::default()
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "empty_filter_value",
            },
        },
        Row {
            label: "filter_limit_exceeded_document_ids",
            request: QueryRagRequest {
                query: "valid query".into(),
                session_id: "00000000-0000-4000-8000-000000000007".into(),
                filter: Some(DocumentFilter {
                    document_ids: too_many_document_ids,
                    content_types: vec![],
                }),
                ..Default::default()
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "filter_limit_exceeded",
            },
        },
        Row {
            label: "filter_limit_exceeded_content_types",
            request: QueryRagRequest {
                query: "valid query".into(),
                session_id: "00000000-0000-4000-8000-000000000008".into(),
                filter: Some(DocumentFilter {
                    document_ids: vec![],
                    content_types: vec![
                        "application/json".into(),
                        "text/markdown".into(),
                        "text/plain".into(),
                    ],
                }),
                ..Default::default()
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "filter_limit_exceeded",
            },
        },
        Row {
            label: "unmatched_filter",
            request: QueryRagRequest {
                query: "valid query".into(),
                session_id: String::new(), // Absent session id is accepted; one is generated.
                filter: Some(DocumentFilter {
                    document_ids: vec![Uuid::new_v4().to_string()],
                    content_types: vec![],
                }),
                ..Default::default()
            },
            outcome: Outcome::Succeed,
        },
        Row {
            label: "contradictory_filter",
            request: QueryRagRequest {
                query: "valid query".into(),
                session_id: "00000000-0000-4000-8000-000000000009".into(),
                filter: Some(DocumentFilter {
                    document_ids: vec![doc_id],
                    content_types: vec!["application/json".into()],
                }),
                ..Default::default()
            },
            outcome: Outcome::Succeed,
        },
        Row {
            label: "invalid_retrieval_mode",
            request: QueryRagRequest {
                retrieval_mode: 99,
                ..test_query_request("valid query", "00000000-0000-4000-8000-00000000000a")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_retrieval_mode",
            },
        },
        Row {
            label: "negative_retrieval_mode",
            request: QueryRagRequest {
                retrieval_mode: -1,
                ..test_query_request("valid query", "00000000-0000-4000-8000-00000000000b")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_retrieval_mode",
            },
        },
        Row {
            label: "invalid_lever",
            request: QueryRagRequest {
                levers: vec![99],
                ..test_query_request("valid query", "00000000-0000-4000-8000-00000000000c")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_levers",
            },
        },
        Row {
            label: "negative_lever",
            request: QueryRagRequest {
                levers: vec![-1],
                ..test_query_request("valid query", "00000000-0000-4000-8000-00000000000d")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_levers",
            },
        },
        Row {
            label: "duplicate_lever",
            // Two copies of an admissible lever: the duplicate is refused before availability.
            request: QueryRagRequest {
                levers: vec![
                    Lever::BinaryAnswerFormat as i32,
                    Lever::BinaryAnswerFormat as i32,
                ],
                ..test_query_request("valid query", "00000000-0000-4000-8000-00000000000e")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_levers",
            },
        },
        Row {
            label: "lever_unspecified_member",
            request: QueryRagRequest {
                levers: vec![Lever::Unspecified as i32],
                ..test_query_request("valid query", "00000000-0000-4000-8000-00000000000f")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_levers",
            },
        },
        Row {
            label: "lever_unavailable_rerank",
            request: QueryRagRequest {
                levers: vec![Lever::Rerank as i32],
                ..test_query_request("valid query", "00000000-0000-4000-8000-000000000010")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "lever_unavailable",
            },
        },
        Row {
            label: "lever_unavailable_evidence_metadata",
            request: QueryRagRequest {
                levers: vec![Lever::EvidenceMetadata as i32],
                ..test_query_request("valid query", "00000000-0000-4000-8000-000000000011")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "lever_unavailable",
            },
        },
        Row {
            label: "lever_unavailable_graph_v2",
            request: QueryRagRequest {
                levers: vec![Lever::GraphV2 as i32],
                ..test_query_request("valid query", "00000000-0000-4000-8000-000000000012")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "lever_unavailable",
            },
        },
        Row {
            label: "lever_unavailable_when_mixed_with_an_available_lever",
            // One available and one unavailable lever: the whole request is refused, never
            // admitted with a subset, because the echo would then claim fewer levers than named.
            request: QueryRagRequest {
                levers: vec![Lever::BinaryAnswerFormat as i32, Lever::Rerank as i32],
                ..test_query_request("valid query", "00000000-0000-4000-8000-000000000013")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "lever_unavailable",
            },
        },
        Row {
            label: "graph_v2_with_graph_disabled",
            // The D-165 combination check runs before availability, so this row reports the
            // contradiction and not the unavailability of graph_v2.
            request: QueryRagRequest {
                levers: vec![Lever::GraphV2 as i32],
                disable_graph_context: Some(true),
                ..test_query_request("valid query", "00000000-0000-4000-8000-000000000014")
            },
            outcome: Outcome::Reject {
                code: tonic::Code::InvalidArgument,
                error_kind: "invalid_lever_combination",
            },
        },
        Row {
            label: "levers_admitted",
            request: QueryRagRequest {
                query: "valid query".into(),
                session_id: String::new(),
                filter: Some(DocumentFilter {
                    document_ids: vec![Uuid::new_v4().to_string()],
                    content_types: vec![],
                }),
                levers: vec![Lever::BinaryAnswerFormat as i32],
                ..Default::default()
            },
            outcome: Outcome::Succeed,
        },
    ];
    let admitted_modes = [
        (
            "retrieval_mode_unspecified_admitted",
            RetrievalMode::Unspecified,
        ),
        ("retrieval_mode_hybrid_admitted", RetrievalMode::Hybrid),
        (
            "retrieval_mode_dense_only_admitted",
            RetrievalMode::DenseOnly,
        ),
        ("retrieval_mode_bm25_only_admitted", RetrievalMode::Bm25Only),
    ];
    let rows = rows
        .into_iter()
        .chain(admitted_modes.map(|(label, mode)| Row {
            label,
            request: QueryRagRequest {
                query: "valid query".into(),
                session_id: String::new(),
                filter: Some(DocumentFilter {
                    document_ids: vec![Uuid::new_v4().to_string()],
                    content_types: vec![],
                }),
                retrieval_mode: mode as i32,
                ..Default::default()
            },
            outcome: Outcome::Succeed,
        }));

    for row in rows {
        match row.outcome {
            Outcome::Reject { code, error_kind } => {
                let status = match super::execute_query_rag(&service, row.request).await {
                    Err(status) => status,
                    Ok(_) => panic!("row '{}' must be rejected, but succeeded", row.label),
                };
                assert_eq!(status.code(), code, "row '{}' status code", row.label);
                let got_error_kind = status
                    .metadata()
                    .get("x-lancet-error-kind")
                    .unwrap_or_else(|| {
                        panic!("row '{}' missing x-lancet-error-kind trailer", row.label)
                    })
                    .to_str()
                    .unwrap();
                assert_eq!(got_error_kind, error_kind, "row '{}' error-kind", row.label);
            }
            Outcome::Succeed => {
                let response = super::execute_query_rag(&service, row.request)
                    .await
                    .unwrap_or_else(|err| panic!("row '{}' must succeed: {err}", row.label));
                assert!(
                    response
                        .notices
                        .iter()
                        .any(|n| n.typed_code == NoticeCode::NoEvidence as i32),
                    "row '{}' must carry the zero-evidence notice",
                    row.label
                );
            }
        }
    }

    // `levers_metadata_admitted`: the request refused on the empty map above (row
    // `lever_unavailable_evidence_metadata`) is admitted once the snapshot holds metadata.
    {
        let mut store = service.corpus_store.write().await;
        let prior = Arc::clone(&*store);
        let map = DocMetaMap::from_entries([(
            Uuid::new_v4().to_string(),
            DocMeta {
                doc_title: Some("A real headline".to_owned()),
                source: None,
                published_date: None,
            },
        )]);
        *store = Arc::new((*prior).clone().with_doc_meta(Arc::new(map)));
    }
    let admitted = super::execute_query_rag(
        &service,
        QueryRagRequest {
            query: "valid query".into(),
            session_id: String::new(),
            filter: Some(DocumentFilter {
                document_ids: vec![Uuid::new_v4().to_string()],
                content_types: vec![],
            }),
            levers: vec![Lever::EvidenceMetadata as i32],
            ..Default::default()
        },
    )
    .await
    .expect("row 'levers_metadata_admitted' must succeed once the snapshot holds metadata");
    assert!(
        admitted
            .notices
            .iter()
            .any(|n| n.typed_code == NoticeCode::NoEvidence as i32),
        "row 'levers_metadata_admitted' must carry the zero-evidence notice"
    );

    assert_eq!(
        fake_gen.calls(),
        0,
        "no row reaches the generator: rejecting rows never reach the workflow, and both \
         non-rejection rows construct genuine zero evidence, which WorkflowRunner skips \
         generation for"
    );

    let _ = std::fs::remove_dir_all(path);
}
