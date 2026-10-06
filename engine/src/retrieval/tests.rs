use std::sync::Arc;

use arrow_array::{
    new_null_array, types::Float32Type, FixedSizeListArray, Int32Array, Int64Array, RecordBatch,
    StringArray,
};
use engine::db::DatabaseManager;
use uuid::Uuid;

use super::bm25::analyze;
use super::fusion::VariantProvenanceSource;
use super::{
    fuse_candidates, fuse_cross_variant_candidates, Bm25Config, Bm25Index, Candidate,
    DenseRetriever, QueryFilters, QueryRequest, RetrievalErrorKind, RetrievalSettings,
    MAX_SERVICE_CANDIDATE_LIMIT, MAX_SERVICE_FINAL_LIMIT,
};

fn candidate(document_id: &str, chunk_id: &str, content: &str) -> Candidate {
    Candidate {
        document_id: document_id.to_owned(),
        chunk_id: chunk_id.to_owned(),
        chunk_index: 0,
        char_start: 0,
        char_end: content.chars().count() as i32,
        content: content.to_owned(),
        title: None,
        section_path: None,
        content_type: Some("text/plain".to_owned()),
        embedding_model: Some("test-model".to_owned()),
        ingested_at: Some(42),
        score: 0.0,
    }
}

#[test]
fn bm25_full_unicode_analyzer_and_global_idf() {
    let first = Uuid::new_v4().to_string();
    let second = Uuid::new_v4().to_string();
    let tokens = analyze("ＦＯＯ Straße OpenRouterClient foo_bar foo-bar");
    assert!(tokens.contains(&"foo".to_owned()));
    assert!(tokens.contains(&"strasse".to_owned()));
    assert!(tokens.contains(&"openrouterclient".to_owned()));
    assert!(tokens.contains(&"open".to_owned()));
    assert!(tokens.contains(&"router".to_owned()));
    assert!(tokens.contains(&"client".to_owned()));
    assert!(tokens.contains(&"foo_bar".to_owned()));

    let mut with_global_term = candidate(&first, "first:0", "Straße OpenRouterClient");
    with_global_term.title = Some("Unicode title".to_owned());
    let index = Bm25Index::from_candidates(
        vec![
            with_global_term.clone(),
            candidate(&second, "second:0", "Straße unrelated"),
        ],
        Bm25Config::default(),
    )
    .unwrap();
    let settings = RetrievalSettings::default();
    let request = QueryRequest::from_values(
        "  STRASSE open-router ",
        vec![first.clone()],
        vec!["TEXT/PLAIN".to_owned()],
        &settings,
    )
    .unwrap();
    let result = index.query(&request, &settings).unwrap();
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].chunk_id, "first:0");
    assert_eq!(result[0].content, with_global_term.content);
    assert!(result[0].score > 0.0);

    let filtered_request = QueryRequest::normalize(
        "strasse open-router",
        QueryFilters::new(vec![first], vec![]).unwrap(),
        &settings,
    )
    .unwrap();
    let filtered = index.query(&filtered_request, &settings).unwrap();
    assert_eq!(filtered.len(), 1);
    assert_eq!(
        filtered[0].score, result[0].score,
        "filters must not redefine IDF"
    );
}

#[test]
fn bm25_rejects_empty_required_content() {
    let document_id = Uuid::new_v4().to_string();
    let invalid = candidate(&document_id, "chunk:0", " \n\t ");
    let error = Bm25Index::from_candidates(vec![invalid], Bm25Config::default()).unwrap_err();
    assert_eq!(error.row, 0);
    assert_eq!(error.field, "content");
    assert!(error.reason.contains("whitespace-only"));
    assert!(error.to_string().contains("row 0 field content"));
}

fn database_path(test_name: &str) -> String {
    std::env::temp_dir()
        .join(format!("lancet-retrieval-{test_name}-{}", Uuid::new_v4()))
        .to_string_lossy()
        .into_owned()
}

#[tokio::test]
async fn retrieval_filter_fusion_and_determinism() {
    let path = database_path("filter-fusion");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let nodes = database.nodes_table().await.unwrap();
    let schema = nodes.schema().await.unwrap();
    let document_a = Uuid::new_v4().to_string();
    let document_b = Uuid::new_v4().to_string();
    let document_c = Uuid::new_v4().to_string();
    let contents = [
        "Rust retrieval happy path",
        "Filter semantics",
        "Rust retrieval global corpus",
        "BM25 reference",
    ];
    let document_ids = [&document_a, &document_a, &document_b, &document_c];
    let chunk_ids = ["chunk-a", "chunk-b", "chunk-c", "chunk-d"];
    let content_types = [
        Some("text/plain"),
        Some("text/markdown"),
        Some("application/json"),
        Some("text/plain"),
    ];
    let titles = [Some("Guide"), Some("Filters"), Some("Guide"), None];
    let section_paths = [Some("Retrieval"), Some("Filters"), Some("Retrieval"), None];
    let embedding_values = [0.0_f32, 0.25, 0.5, 0.75]
        .into_iter()
        .map(|value| Some(vec![Some(value); 2048]))
        .collect::<Vec<_>>();
    let embeddings =
        FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(embedding_values, 2048);
    let nullable = |name: &str| {
        new_null_array(
            schema.field_with_name(name).unwrap().data_type(),
            contents.len(),
        )
    };
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(
                document_ids
                    .iter()
                    .map(|value| Some(value.as_str()))
                    .collect::<Vec<_>>(),
            )),
            Arc::new(StringArray::from(
                chunk_ids
                    .iter()
                    .map(|value| Some(*value))
                    .collect::<Vec<_>>(),
            )),
            Arc::new(Int32Array::from(vec![0, 1, 0, 0])),
            Arc::new(Int32Array::from(vec![0, 25, 0, 0])),
            Arc::new(Int32Array::from(vec![27, 44, 31, 17])),
            Arc::new(StringArray::from(contents.to_vec())),
            Arc::new(embeddings),
            Arc::new(Int32Array::from(vec![4; 4])),
            Arc::new(StringArray::from(vec![Some("o200k_base"); 4])),
            Arc::new(StringArray::from(vec![Some("1"); 4])),
            Arc::new(StringArray::from(titles.to_vec())),
            Arc::new(StringArray::from(section_paths.to_vec())),
            nullable("page_start"),
            nullable("page_end"),
            nullable("content_hash"),
            nullable("chunker_version"),
            Arc::new(StringArray::from(vec![Some("test-model"); 4])),
            Arc::new(Int64Array::from(vec![Some(42); 4])),
            Arc::new(StringArray::from(content_types.to_vec())),
        ],
    )
    .unwrap();
    nodes.add(batch).execute().await.unwrap();

    let settings = RetrievalSettings {
        candidate_limit: 8,
        final_limit: 4,
        ..RetrievalSettings::default()
    };
    let request =
        QueryRequest::from_values("  rust retrieval  ", vec![], vec![], &settings).unwrap();
    let dense = DenseRetriever::new(nodes.clone());
    let all_dense = dense
        .query(&vec![0.0; 2048], &request, &settings)
        .await
        .unwrap();
    assert_eq!(
        all_dense.len(),
        4,
        "empty filters must search the global corpus"
    );

    let document_request = QueryRequest::from_values(
        "rust retrieval",
        vec![document_a.clone(), document_b.clone()],
        vec![],
        &settings,
    )
    .unwrap();
    let document_results = dense
        .query(&vec![0.0; 2048], &document_request, &settings)
        .await
        .unwrap();
    assert_eq!(document_results.len(), 3, "document IDs combine with OR");
    assert!(document_results.iter().all(
        |candidate| candidate.document_id == document_a || candidate.document_id == document_b
    ));

    let content_type_request = QueryRequest::from_values(
        "rust retrieval",
        vec![],
        vec!["TEXT/PLAIN".to_owned(), "text/markdown".to_owned()],
        &settings,
    )
    .unwrap();
    let content_type_results = dense
        .query(&vec![0.0; 2048], &content_type_request, &settings)
        .await
        .unwrap();
    assert_eq!(
        content_type_results.len(),
        3,
        "content types combine with OR"
    );
    assert!(content_type_results.iter().all(|candidate| {
        matches!(
            candidate.content_type.as_deref(),
            Some("text/plain" | "text/markdown")
        )
    }));

    let and_request = QueryRequest::from_values(
        "rust retrieval",
        vec![document_a.clone()],
        vec!["text/markdown".to_owned()],
        &settings,
    )
    .unwrap();
    let and_results = dense
        .query(&vec![0.0; 2048], &and_request, &settings)
        .await
        .unwrap();
    assert_eq!(
        and_results
            .iter()
            .map(|candidate| candidate.chunk_id.as_str())
            .collect::<Vec<_>>(),
        ["chunk-b"]
    );

    let no_match_request = QueryRequest::from_values(
        "rust retrieval",
        vec![document_c.clone()],
        vec!["application/json".to_owned()],
        &settings,
    )
    .unwrap();
    assert!(dense
        .query(&vec![0.0; 2048], &no_match_request, &settings)
        .await
        .unwrap()
        .is_empty());

    let invalid = QueryRequest::from_values(
        "rust retrieval",
        vec!["not-a-uuid".to_owned()],
        vec![],
        &settings,
    )
    .unwrap_err();
    assert_eq!(invalid.kind, super::RetrievalErrorKind::InvalidDocumentId);

    let lexical = Bm25Index::from_candidates(all_dense.clone(), Bm25Config::default()).unwrap();
    let lexical_all = lexical.query(&request, &settings).unwrap();
    let lexical_filtered = lexical.query(&document_request, &settings).unwrap();
    let all_score = lexical_all
        .iter()
        .find(|candidate| candidate.chunk_id == "chunk-a")
        .unwrap()
        .score;
    let filtered_score = lexical_filtered
        .iter()
        .find(|candidate| candidate.chunk_id == "chunk-a")
        .unwrap()
        .score;
    assert_eq!(
        all_score, filtered_score,
        "filters must not redefine global IDF"
    );

    let fused = fuse_candidates(all_dense.clone(), lexical_all.clone(), &settings).unwrap();
    let chunk_a = fused
        .iter()
        .find(|candidate| candidate.candidate.chunk_id == "chunk-a")
        .unwrap();
    assert_eq!(chunk_a.vector_rank, Some(1));
    assert!(chunk_a.bm25_rank.is_some());
    assert!(chunk_a.fused_score > 0.0);

    let repeated_dense = dense
        .query(&vec![0.0; 2048], &request, &settings)
        .await
        .unwrap();
    let repeated_lexical = lexical.query(&request, &settings).unwrap();
    let repeated_fused = fuse_candidates(repeated_dense, repeated_lexical, &settings).unwrap();
    assert_eq!(
        serde_json::to_vec(&fused).unwrap(),
        serde_json::to_vec(&repeated_fused).unwrap(),
        "repeated normalized runs must serialize identically"
    );

    let tie_left = candidate(&document_b, "tie-z", "tie");
    let tie_right = candidate(&document_a, "tie-a", "tie");
    let tie_settings = RetrievalSettings {
        candidate_limit: 2,
        final_limit: 2,
        ..settings.clone()
    };
    let tied = fuse_candidates(
        vec![tie_left.clone(), tie_right.clone()],
        vec![tie_right, tie_left],
        &tie_settings,
    )
    .unwrap();
    let expected_tie_document = document_a.as_str().min(document_b.as_str());
    assert_eq!(tied[0].candidate.document_id, expected_tie_document);

    drop(dense);
    drop(nodes);
    drop(database);
    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn retrieval_snapshot_values_are_lossless() {
    let valid = RetrievalSettings {
        candidate_limit: MAX_SERVICE_CANDIDATE_LIMIT,
        final_limit: MAX_SERVICE_FINAL_LIMIT,
        rrf_k: 60.0,
        ..RetrievalSettings::default()
    };
    assert!(valid.validate().is_ok());

    let fractional_k = RetrievalSettings {
        rrf_k: 60.5,
        ..RetrievalSettings::default()
    };
    assert!(fractional_k.validate().is_err());

    let non_finite_k = RetrievalSettings {
        rrf_k: f64::NAN,
        ..RetrievalSettings::default()
    };
    assert!(non_finite_k.validate().is_err());

    let out_of_range_k = RetrievalSettings {
        rrf_k: 3_000_000_000.0,
        ..RetrievalSettings::default()
    };
    assert!(out_of_range_k.validate().is_err());

    let limit_too_large = RetrievalSettings {
        candidate_limit: (i32::MAX as usize) + 1,
        ..RetrievalSettings::default()
    };
    assert!(limit_too_large.validate().is_err());
}

#[test]
fn zero_vector_weight_excludes_vector_only_candidates() {
    let mut settings = RetrievalSettings {
        candidate_limit: 4,
        final_limit: 4,
        vector_weight: 0.0,
        bm25_weight: 1.0,
        ..RetrievalSettings::default()
    };
    settings.rrf_k = 60.0;

    let vector_shared = candidate("doc-shared", "shared", "vector shared");
    let vector_only = candidate("doc-vector", "vector-only", "vector only");
    let bm25_shared = candidate("doc-shared", "shared", "bm25 shared");
    let bm25_only = candidate("doc-bm25", "bm25-only", "bm25 only");

    let fused = fuse_candidates(
        vec![vector_shared, vector_only],
        vec![bm25_shared, bm25_only],
        &settings,
    )
    .unwrap();

    assert_eq!(
        fused
            .iter()
            .map(|result| result.candidate.chunk_id.as_str())
            .collect::<Vec<_>>(),
        vec!["shared", "bm25-only"]
    );
    assert!(fused
        .iter()
        .all(|result| result.vector_rank.is_none() && result.vector_score.is_none()));
    assert!(fused.iter().all(|result| result.bm25_rank.is_some()));
}

#[test]
fn zero_bm25_weight_excludes_bm25_only_candidates() {
    let settings = RetrievalSettings {
        candidate_limit: 4,
        final_limit: 4,
        vector_weight: 1.0,
        bm25_weight: 0.0,
        ..RetrievalSettings::default()
    };

    let vector_shared = candidate("doc-shared", "shared", "vector shared");
    let vector_only = candidate("doc-vector", "vector-only", "vector only");
    let bm25_shared = candidate("doc-shared", "shared", "bm25 shared");
    let bm25_only = candidate("doc-bm25", "bm25-only", "bm25 only");

    let fused = fuse_candidates(
        vec![vector_shared, vector_only],
        vec![bm25_shared, bm25_only],
        &settings,
    )
    .unwrap();

    assert_eq!(
        fused
            .iter()
            .map(|result| result.candidate.chunk_id.as_str())
            .collect::<Vec<_>>(),
        vec!["shared", "vector-only"]
    );
    assert!(fused
        .iter()
        .all(|result| result.bm25_rank.is_none() && result.bm25_score.is_none()));
    assert!(fused.iter().all(|result| result.vector_rank.is_some()));
}

#[test]
fn positive_weights_preserve_rrf_dedup_and_ties() {
    let settings = RetrievalSettings {
        candidate_limit: 3,
        final_limit: 3,
        vector_weight: 1.0,
        bm25_weight: 1.0,
        rrf_k: 60.0,
        ..RetrievalSettings::default()
    };

    let vector_shared = candidate("doc-shared", "shared", "vector shared");
    let vector_only = candidate("doc-z", "vector-only", "vector only");
    let bm25_shared = candidate("doc-shared", "shared", "bm25 shared");
    let bm25_only = candidate("doc-a", "bm25-only", "bm25 only");

    let fused = fuse_candidates(
        vec![vector_shared.clone(), vector_only.clone()],
        vec![bm25_shared.clone(), bm25_only.clone()],
        &settings,
    )
    .unwrap();
    let repeated = fuse_candidates(
        vec![vector_shared, vector_only],
        vec![bm25_shared, bm25_only],
        &settings,
    )
    .unwrap();

    assert_eq!(fused.len(), 3, "shared chunk IDs must be deduplicated");
    assert_eq!(
        fused
            .iter()
            .map(|result| result.candidate.chunk_id.as_str())
            .collect::<Vec<_>>(),
        vec!["shared", "bm25-only", "vector-only"],
        "equal exclusive scores use the deterministic document-ID tie key"
    );

    let shared = &fused[0];
    assert_eq!(shared.vector_rank, Some(1));
    assert_eq!(shared.bm25_rank, Some(1));
    assert_eq!(shared.vector_score, Some(0.0));
    assert_eq!(shared.bm25_score, Some(0.0));
    assert_eq!(shared.fused_score, 1.0 / 61.0 + 1.0 / 61.0);
    assert_eq!(fused[1].fused_score, 1.0 / 62.0);
    assert_eq!(fused[2].fused_score, 1.0 / 62.0);
    assert_eq!(
        serde_json::to_vec(&fused).unwrap(),
        serde_json::to_vec(&repeated).unwrap(),
        "positive-weight fusion must remain byte-stable across identical runs"
    );
}

#[test]
fn service_ceiling_rejects_each_absolute_maximum() {
    let base = RetrievalSettings::default();

    // candidate_limit > 500
    let mut s = base.clone();
    s.candidate_limit = 501;
    assert_eq!(
        s.validate().unwrap_err().kind,
        RetrievalErrorKind::InvalidSettings
    );

    // final_limit > 100
    let mut s = base.clone();
    s.candidate_limit = 500;
    s.final_limit = 101;
    assert_eq!(
        s.validate().unwrap_err().kind,
        RetrievalErrorKind::InvalidSettings
    );

    // query_max_bytes > 8192
    let mut s = base.clone();
    s.query_max_bytes = 8193;
    assert_eq!(
        s.validate().unwrap_err().kind,
        RetrievalErrorKind::InvalidSettings
    );

    // max_document_ids > 100
    let mut s = base.clone();
    s.max_document_ids = 101;
    assert_eq!(
        s.validate().unwrap_err().kind,
        RetrievalErrorKind::InvalidSettings
    );

    // max_content_types > 100
    let mut s = base.clone();
    s.max_content_types = 101;
    assert_eq!(
        s.validate().unwrap_err().kind,
        RetrievalErrorKind::InvalidSettings
    );

    // vector_weight > 16.0
    let mut s = base.clone();
    s.vector_weight = 16.000001;
    assert_eq!(
        s.validate().unwrap_err().kind,
        RetrievalErrorKind::InvalidSettings
    );

    // bm25_weight > 16.0
    let mut s = base.clone();
    s.bm25_weight = 16.000001;
    assert_eq!(
        s.validate().unwrap_err().kind,
        RetrievalErrorKind::InvalidSettings
    );

    // rrf_k > 1000000.0
    let mut s = base.clone();
    s.rrf_k = 1000001.0;
    assert_eq!(
        s.validate().unwrap_err().kind,
        RetrievalErrorKind::InvalidSettings
    );
}

#[test]
fn request_filter_limit_enforces_unique_values_after_normalization() {
    let mut doc_ids = Vec::new();
    let uuid_str = "00000000-0000-4000-8000-000000000001";
    for _ in 0..200 {
        doc_ids.push(uuid_str.to_string());
    }

    let filters = QueryFilters::normalize_with_limits(doc_ids, vec![], 100, 16).unwrap();
    assert_eq!(filters.document_ids.len(), 1);

    let mut distinct_ids = Vec::new();
    for i in 0..101 {
        distinct_ids.push(format!("00000000-0000-4000-8000-{i:012x}"));
    }
    let err = QueryFilters::normalize_with_limits(distinct_ids, vec![], 100, 16).unwrap_err();
    assert_eq!(err.kind, RetrievalErrorKind::FilterLimitExceeded);
}

#[test]
fn bm25_candidate_workspace_respects_effective_limit() {
    let cand1 = candidate(
        "00000000-0000-4000-8000-000000000001",
        "chunk-1",
        "apple apple apple",
    );
    let cand2 = candidate(
        "00000000-0000-4000-8000-000000000002",
        "chunk-2",
        "apple apple",
    );
    let cand3 = candidate("00000000-0000-4000-8000-000000000003", "chunk-3", "apple");

    let index =
        Bm25Index::from_candidates(vec![cand1, cand2, cand3], Bm25Config::default()).unwrap();

    let settings = RetrievalSettings {
        candidate_limit: 2,
        final_limit: 2,
        ..RetrievalSettings::default()
    };

    let req = QueryRequest::new("apple", QueryFilters::empty()).unwrap();
    let res = index.query(&req, &settings).unwrap();

    assert_eq!(res.len(), 2, "must be bounded by candidate_limit 2");
    assert_eq!(res[0].chunk_id, "chunk-1");
    assert_eq!(res[1].chunk_id, "chunk-2");
}

#[test]
fn fusion_deduplicates_source_before_contribution() {
    let settings = RetrievalSettings::default();
    let cand1 = candidate("00000000-0000-4000-8000-000000000001", "chunk-1", "content");
    let cand1_dup = candidate("00000000-0000-4000-8000-000000000001", "chunk-1", "content");

    let fused = fuse_candidates(vec![cand1, cand1_dup], vec![], &settings).unwrap();
    assert_eq!(
        fused.len(),
        1,
        "duplicate candidate in vector source must be deduplicated before contribution"
    );
    assert_eq!(
        fused[0].fused_score,
        1.0 / 61.0,
        "should contribute only once at rank 1"
    );
}

#[test]
fn fusion_rejects_non_finite_scores() {
    let settings = RetrievalSettings::default();
    let mut cand_nan = candidate("00000000-0000-4000-8000-000000000001", "chunk-1", "content");
    cand_nan.score = f64::NAN;

    let err = fuse_candidates(vec![cand_nan], vec![], &settings).unwrap_err();
    assert_eq!(err.kind, RetrievalErrorKind::NonFiniteScore);
}

#[test]
fn fusion_rejects_non_finite_accumulator() {
    let settings = RetrievalSettings::default();
    let mut cand_inf = candidate("00000000-0000-4000-8000-000000000001", "chunk-1", "content");
    cand_inf.score = f64::INFINITY;

    let err = fuse_candidates(vec![cand_inf], vec![], &settings).unwrap_err();
    assert_eq!(err.kind, RetrievalErrorKind::NonFiniteScore);
}

#[test]
fn fusion_cross_variant_tracer() {
    let settings = RetrievalSettings::default();
    let cand_vec = candidate(
        "00000000-0000-4000-8000-000000000001",
        "chunk-1",
        "vector content",
    );
    let cand_bm25_v0 = candidate(
        "00000000-0000-4000-8000-000000000001",
        "chunk-1",
        "bm25 content v0",
    );
    let cand_bm25_v1 = candidate(
        "00000000-0000-4000-8000-000000000002",
        "chunk-2",
        "bm25 content v1",
    );

    let fused_v0 = fuse_candidates(vec![cand_vec], vec![cand_bm25_v0], &settings).unwrap();
    let fused_v1 = fuse_candidates(vec![], vec![cand_bm25_v1], &settings).unwrap();

    let fused = fuse_cross_variant_candidates(vec![fused_v0, fused_v1], vec![], &settings).unwrap();

    assert_eq!(fused.len(), 2);
    assert_eq!(fused[0].candidate.chunk_id, "chunk-1");
    assert_eq!(fused[0].variant_provenance.len(), 2);
    assert_eq!(fused[0].variant_provenance[0].variant_index, 0);
    assert_eq!(fused[0].variant_provenance[1].variant_index, 0);
    assert_eq!(fused[1].candidate.chunk_id, "chunk-2");
    assert_eq!(fused[1].variant_provenance.len(), 1);
    assert_eq!(fused[1].variant_provenance[0].variant_index, 1);
}

#[test]
fn fusion_variant_provenance_source_tracer() {
    let settings = RetrievalSettings::default();
    let mut vector_candidate = candidate(
        "00000000-0000-4000-8000-000000000001",
        "shared",
        "vector content",
    );
    vector_candidate.score = 0.75;
    let mut bm25_candidate = candidate(
        "00000000-0000-4000-8000-000000000001",
        "shared",
        "bm25 content",
    );
    bm25_candidate.score = 0.25;

    let fused = fuse_candidates(vec![vector_candidate], vec![bm25_candidate], &settings).unwrap();

    assert_eq!(fused.len(), 1);
    let shared = &fused[0];
    assert_eq!(shared.candidate.chunk_id, "shared");
    assert_eq!(shared.fused_score, 2.0 / 61.0);
    assert_eq!(shared.vector_rank, Some(1));
    assert_eq!(shared.vector_score, Some(0.75));
    assert_eq!(shared.bm25_rank, Some(1));
    assert_eq!(shared.bm25_score, Some(0.25));
    assert_eq!(shared.variant_provenance.len(), 2);
    assert_eq!(
        shared.variant_provenance[0].source,
        VariantProvenanceSource::Vector
    );
    assert_eq!(shared.variant_provenance[0].variant_index, 0);
    assert_eq!(shared.variant_provenance[0].rank, 1);
    assert_eq!(shared.variant_provenance[0].score, 0.75);
    assert_eq!(shared.variant_provenance[0].contribution, 1.0 / 61.0);
    assert_eq!(
        shared.variant_provenance[1].source,
        VariantProvenanceSource::Bm25
    );
    assert_eq!(shared.variant_provenance[1].variant_index, 0);
    assert_eq!(shared.variant_provenance[1].rank, 1);
    assert_eq!(shared.variant_provenance[1].score, 0.25);
    assert_eq!(shared.variant_provenance[1].contribution, 1.0 / 61.0);
}

#[test]
fn fusion_variant_provenance_source_is_typed() {
    assert_eq!(
        VariantProvenanceSource::Vector,
        VariantProvenanceSource::Vector
    );
    assert_ne!(
        VariantProvenanceSource::Vector,
        VariantProvenanceSource::Bm25
    );
    assert_eq!(
        serde_json::to_string(&VariantProvenanceSource::Vector).unwrap(),
        "\"vector\""
    );
    assert_eq!(
        serde_json::to_string(&VariantProvenanceSource::Bm25).unwrap(),
        "\"bm25\""
    );

    let settings = RetrievalSettings::default();
    let mut vector_candidate = candidate(
        "00000000-0000-4000-8000-000000000001",
        "shared",
        "vector content",
    );
    vector_candidate.score = 0.9;
    let mut bm25_variant_zero = candidate(
        "00000000-0000-4000-8000-000000000001",
        "shared",
        "bm25 variant zero",
    );
    bm25_variant_zero.score = 0.4;
    let mut bm25_variant_one = candidate(
        "00000000-0000-4000-8000-000000000001",
        "shared",
        "bm25 variant one",
    );
    bm25_variant_one.score = 0.8;

    let fused_v0 =
        fuse_candidates(vec![vector_candidate], vec![bm25_variant_zero], &settings).unwrap();
    let fused_v1 = fuse_candidates(vec![], vec![bm25_variant_one], &settings).unwrap();

    let fused = fuse_cross_variant_candidates(vec![fused_v0, fused_v1], vec![], &settings).unwrap();

    assert_eq!(fused.len(), 1);
    let shared = &fused[0];
    assert_eq!(shared.vector_rank, Some(1));
    assert_eq!(shared.vector_score, Some(0.9));
    assert_eq!(shared.bm25_rank, Some(1));
    assert_eq!(shared.bm25_score, Some(0.8));
    assert_eq!(shared.fused_score, 2.0 / 61.0);

    let vector_entries: Vec<_> = shared
        .variant_provenance
        .iter()
        .filter(|entry| entry.source == VariantProvenanceSource::Vector)
        .collect();
    let bm25_entries: Vec<_> = shared
        .variant_provenance
        .iter()
        .filter(|entry| entry.source == VariantProvenanceSource::Bm25)
        .collect();
    assert_eq!(vector_entries.len(), 1);
    assert_eq!(vector_entries[0].variant_index, 0);
    assert_eq!(vector_entries[0].rank, 1);
    assert_eq!(vector_entries[0].score, 0.9);
    assert_eq!(bm25_entries.len(), 2);
    assert_eq!(bm25_entries[0].variant_index, 0);
    assert_eq!(bm25_entries[0].rank, 1);
    assert_eq!(bm25_entries[0].score, 0.4);
    assert_eq!(bm25_entries[1].variant_index, 1);
    assert_eq!(bm25_entries[1].rank, 1);
    assert_eq!(bm25_entries[1].score, 0.8);
    assert!(shared
        .variant_provenance
        .iter()
        .all(|entry| entry.contribution == 1.0 / 61.0));
}

#[test]
fn variant_zero_one_variant_matches_existing_scores() {
    let settings = RetrievalSettings::default();
    let cand_vec = candidate(
        "00000000-0000-4000-8000-000000000001",
        "chunk-1",
        "vector content",
    );
    let cand_bm25 = candidate(
        "00000000-0000-4000-8000-000000000002",
        "chunk-2",
        "bm25 content",
    );

    let fused_single =
        fuse_candidates(vec![cand_vec.clone()], vec![cand_bm25.clone()], &settings).unwrap();

    let fused_variant =
        fuse_cross_variant_candidates(vec![fused_single.clone()], vec![], &settings).unwrap();

    assert_eq!(fused_single.len(), fused_variant.len());
    for (s, v) in fused_single.iter().zip(fused_variant.iter()) {
        assert_eq!(s.candidate.chunk_id, v.candidate.chunk_id);
        assert_eq!(s.fused_score, v.fused_score);
        assert_eq!(s.vector_rank, v.vector_rank);
        assert_eq!(s.bm25_rank, v.bm25_rank);
        assert_eq!(s.vector_score, v.vector_score);
        assert_eq!(s.bm25_score, v.bm25_score);
        assert_eq!(s.variant_provenance, v.variant_provenance);
    }
}

#[test]
fn cross_variant_provenance_is_bounded() {
    let settings = RetrievalSettings {
        candidate_limit: 2,
        final_limit: 2,
        ..RetrievalSettings::default()
    };

    let c1 = candidate(
        "00000000-0000-4000-8000-000000000001",
        "chunk-1",
        "content 1",
    );
    let c2 = candidate(
        "00000000-0000-4000-8000-000000000002",
        "chunk-2",
        "content 2",
    );
    let c3 = candidate(
        "00000000-0000-4000-8000-000000000003",
        "chunk-3",
        "content 3",
    );

    let mut per_variant_fused = Vec::new();
    per_variant_fused.push(
        fuse_candidates(
            vec![c1.clone(), c2.clone(), c3.clone()],
            vec![c1.clone(), c2.clone(), c3.clone()],
            &settings,
        )
        .unwrap(),
    );
    for _ in 1..8 {
        per_variant_fused.push(
            fuse_candidates(vec![], vec![c1.clone(), c2.clone(), c3.clone()], &settings).unwrap(),
        );
    }

    let fused = fuse_cross_variant_candidates(per_variant_fused, vec![], &settings).unwrap();

    let chunk1_fused = fused
        .iter()
        .find(|c| c.candidate.chunk_id == "chunk-1")
        .unwrap();
    assert_eq!(chunk1_fused.variant_provenance.len(), 9);
    assert!(fused.iter().all(|c| c.candidate.chunk_id != "chunk-3"));
}

#[tokio::test]
async fn cross_variant_rrf_two_variant_exact_scores() {
    use crate::workflow::nodes::RetrieveHybridNode;
    use crate::workflow::ports::{FakeBm25RetrievalPort, FakeDenseRetrievalPort};
    use crate::workflow::{Node, WorkflowContext};
    use tokio_util::sync::CancellationToken;

    let c_a = candidate(
        "00000000-0000-4000-8000-000000000001",
        "chunk-a",
        "content A",
    );
    let c_b = candidate(
        "00000000-0000-4000-8000-000000000002",
        "chunk-b",
        "content B",
    );

    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![c_a.clone()]));
    let fake_bm25 = Arc::new(FakeBm25RetrievalPort::with_map(vec![
        ("variant 0".to_string(), Ok(vec![c_a.clone(), c_b.clone()])),
        ("variant 1".to_string(), Ok(vec![c_b.clone(), c_a.clone()])),
    ]));

    let settings = RetrievalSettings::default();
    let node = RetrieveHybridNode::new(Some(fake_dense), Some(fake_bm25), None, settings);

    let req = crate::testkit::test_query_request("variant 0", "sess-1");
    let mut ctx = WorkflowContext::new("sess-1".into(), "trace-1".into(), &req);
    ctx.variants = vec!["variant 0".into(), "variant 1".into()];

    let cancel = CancellationToken::new();
    node.run(&mut ctx, &cancel).await.unwrap();

    assert_eq!(ctx.evidence_blocks.len(), 2);
    // c_a: rank 1 in var 0 (1/61), rank 2 in var 1 (1/62) -> cross_score = 1/61 + 1/62
    // c_b: rank 2 in var 0 (1/62), rank 1 in var 1 (1/61) -> cross_score = 1/62 + 1/61
    // Ties: both best_variant_rank = 1, both first_variant_index = 0, document_id tie-break chooses chunk-a first.
    assert_eq!(ctx.evidence_blocks[0].chunk_id, "chunk-a");
    assert_eq!(ctx.evidence_blocks[1].chunk_id, "chunk-b");
    let expected_score = 1.0 / 61.0 + 1.0 / 62.0;
    assert!((ctx.evidence_blocks[0].score - expected_score).abs() < 1e-9);
    assert!((ctx.evidence_blocks[1].score - expected_score).abs() < 1e-9);
}

#[test]
fn cross_variant_rrf_tie_order_is_deterministic() {
    let settings = RetrievalSettings::default();

    let c_y1 = candidate("00000000-0000-4000-8000-000000000001", "chunk-1", "y1");
    let c_y2 = candidate("00000000-0000-4000-8000-000000000002", "chunk-2", "y2");

    let fused_v0 = fuse_candidates(vec![], vec![c_y1.clone(), c_y2.clone()], &settings).unwrap();
    let fused_v1 = fuse_candidates(vec![], vec![c_y2.clone(), c_y1.clone()], &settings).unwrap();

    for _ in 0..5 {
        let fused = fuse_cross_variant_candidates(
            vec![fused_v0.clone(), fused_v1.clone()],
            vec![],
            &settings,
        )
        .unwrap();
        assert_eq!(fused.len(), 2);
        assert_eq!(fused[0].candidate.chunk_id, "chunk-1");
        assert_eq!(fused[1].candidate.chunk_id, "chunk-2");

        let serialized = serde_json::to_string(&fused).unwrap();
        let deserialized: Vec<serde_json::Value> = serde_json::from_str(&serialized).unwrap();
        assert_eq!(deserialized.len(), 2);
    }
}

#[test]
fn retrieval_snapshot_variant_provenance_wire_contract() {
    use prost::Message;

    let original = crate::pb::lancet::v1::RetrievalSnapshot {
        index_generation: "gen-2026-test".to_string(),
        embedding_model: "test-embedding-model-v1".to_string(),
        vector_weight: 1.0,
        bm25_weight: 0.8,
        rrf_k: 60,
        candidate_limit: 32,
        final_limit: 8,
        active_filter: Some(crate::pb::lancet::v1::DocumentFilter {
            document_ids: vec!["doc-001".to_string(), "doc-002".to_string()],
            content_types: vec!["text/markdown".to_string()],
        }),
        result_hash: "deadbeef01234567".to_string(),
        variant_count: 3,
        variant_identities: vec![
            "v0:original-query".to_string(),
            "v1:rephrased-query".to_string(),
            "v2:expanded-query".to_string(),
        ],
        retrieved_chunks: vec![],
    };

    let mut buf = Vec::new();
    original
        .encode(&mut buf)
        .expect("RetrievalSnapshot encoding must succeed");
    assert!(!buf.is_empty(), "encoded wire buffer must not be empty");

    // Decode tags present on the wire to prove field numbers 1..=11
    let mut tags = std::collections::BTreeSet::new();
    let mut slice = &buf[..];
    while !slice.is_empty() {
        let (tag, wire_type) =
            prost::encoding::decode_key(&mut slice).expect("protobuf wire key must decode cleanly");
        tags.insert(tag);
        prost::encoding::skip_field(
            wire_type,
            tag,
            &mut slice,
            prost::encoding::DecodeContext::default(),
        )
        .expect("protobuf field must skip cleanly");
    }

    // Historical fields 1 through 9 remain present and intact
    for historical_tag in 1..=9 {
        assert!(
            tags.contains(&historical_tag),
            "historical field tag {} must be present in encoded RetrievalSnapshot wire",
            historical_tag
        );
    }

    // Additive variant provenance fields 10 and 11
    assert!(
        tags.contains(&10),
        "tag 10 (variant_count) must be present in encoded wire"
    );
    assert!(
        tags.contains(&11),
        "tag 11 (variant_identities) must be present in encoded wire"
    );

    // Decode and verify round-trip equivalence and exact ordered identities
    let decoded = crate::pb::lancet::v1::RetrievalSnapshot::decode(&buf[..])
        .expect("RetrievalSnapshot decoding must succeed");

    assert_eq!(decoded.index_generation, original.index_generation);
    assert_eq!(decoded.embedding_model, original.embedding_model);
    assert_eq!(decoded.vector_weight, original.vector_weight);
    assert_eq!(decoded.bm25_weight, original.bm25_weight);
    assert_eq!(decoded.rrf_k, original.rrf_k);
    assert_eq!(decoded.candidate_limit, original.candidate_limit);
    assert_eq!(decoded.final_limit, original.final_limit);
    assert_eq!(decoded.active_filter, original.active_filter);
    assert_eq!(decoded.result_hash, original.result_hash);
    assert_eq!(decoded.variant_count, 3);
    assert_eq!(
        decoded.variant_identities,
        vec![
            "v0:original-query".to_string(),
            "v1:rephrased-query".to_string(),
            "v2:expanded-query".to_string(),
        ]
    );
    assert_eq!(decoded, original);
}

#[test]
fn retrieval_snapshot_retrieved_chunks_wire_contract() {
    use prost::Message;

    let chunk1 = crate::pb::lancet::v1::StructuredCitation {
        chunk_id: "chunk-001".to_string(),
        document_id: "00000000-0000-4000-8000-000000000001".to_string(),
        title: "Test Doc 1".to_string(),
        section_path: "Intro".to_string(),
        excerpt: "This is a test excerpt 1".to_string(),
        is_truncated: false,
        score: 0.95,
        rank: 1,
        content_type: "text/plain".to_string(),
    };
    let chunk2 = crate::pb::lancet::v1::StructuredCitation {
        chunk_id: "chunk-002".to_string(),
        document_id: "00000000-0000-4000-8000-000000000002".to_string(),
        title: "Test Doc 2".to_string(),
        section_path: "Methods".to_string(),
        excerpt: "This is a truncated excerpt...".to_string(),
        is_truncated: true,
        score: 0.85,
        rank: 2,
        content_type: "text/markdown".to_string(),
    };

    let populated = crate::pb::lancet::v1::RetrievalSnapshot {
        index_generation: "gen-2026-test".to_string(),
        embedding_model: "test-embedding-model-v1".to_string(),
        vector_weight: 1.0,
        bm25_weight: 0.8,
        rrf_k: 60,
        candidate_limit: 32,
        final_limit: 8,
        active_filter: Some(crate::pb::lancet::v1::DocumentFilter {
            document_ids: vec!["doc-001".to_string()],
            content_types: vec!["text/plain".to_string()],
        }),
        result_hash: "deadbeef01234567".to_string(),
        variant_count: 1,
        variant_identities: vec!["v0:test".to_string()],
        retrieved_chunks: vec![chunk1.clone(), chunk2.clone()],
    };

    let mut buf = Vec::new();
    populated
        .encode(&mut buf)
        .expect("RetrievalSnapshot encoding must succeed");

    // Decode tags present on wire
    let mut tags = std::collections::BTreeSet::new();
    let mut slice = &buf[..];
    while !slice.is_empty() {
        let (tag, wire_type) =
            prost::encoding::decode_key(&mut slice).expect("protobuf wire key must decode cleanly");
        tags.insert(tag);
        prost::encoding::skip_field(
            wire_type,
            tag,
            &mut slice,
            prost::encoding::DecodeContext::default(),
        )
        .expect("protobuf field must skip cleanly");
    }

    for historical_tag in 1..=11 {
        assert!(
            tags.contains(&historical_tag),
            "tag {} must be present in encoded wire",
            historical_tag
        );
    }
    assert!(
        tags.contains(&12),
        "tag 12 (retrieved_chunks) must be present in encoded wire when populated"
    );

    let decoded = crate::pb::lancet::v1::RetrievalSnapshot::decode(&buf[..])
        .expect("RetrievalSnapshot decoding must succeed");
    assert_eq!(decoded, populated);
    assert_eq!(decoded.retrieved_chunks.len(), 2);
    assert_eq!(decoded.retrieved_chunks[0].chunk_id, "chunk-001");
    assert_eq!(decoded.retrieved_chunks[0].rank, 1);
    assert_eq!(decoded.retrieved_chunks[0].score, 0.95);
    assert_eq!(decoded.retrieved_chunks[0].excerpt, "This is a test excerpt 1");
    assert!(!decoded.retrieved_chunks[0].is_truncated);
    assert_eq!(decoded.retrieved_chunks[1].chunk_id, "chunk-002");
    assert_eq!(decoded.retrieved_chunks[1].rank, 2);
    assert_eq!(decoded.retrieved_chunks[1].score, 0.85);
    assert_eq!(decoded.retrieved_chunks[1].excerpt, "This is a truncated excerpt...");
    assert!(decoded.retrieved_chunks[1].is_truncated);

    // Empty retrieved_chunks: tag 12 must be absent
    let empty_chunks_snapshot = crate::pb::lancet::v1::RetrievalSnapshot {
        index_generation: "gen-2026-test".to_string(),
        embedding_model: "test-embedding-model-v1".to_string(),
        vector_weight: 1.0,
        bm25_weight: 0.8,
        rrf_k: 60,
        candidate_limit: 32,
        final_limit: 8,
        active_filter: None,
        result_hash: "deadbeef01234567".to_string(),
        variant_count: 1,
        variant_identities: vec!["v0:test".to_string()],
        retrieved_chunks: vec![],
    };

    let mut empty_buf = Vec::new();
    empty_chunks_snapshot
        .encode(&mut empty_buf)
        .expect("encoding empty snapshot must succeed");

    let mut empty_tags = std::collections::BTreeSet::new();
    let mut empty_slice = &empty_buf[..];
    while !empty_slice.is_empty() {
        let (tag, wire_type) = prost::encoding::decode_key(&mut empty_slice)
            .expect("protobuf wire key must decode cleanly");
        empty_tags.insert(tag);
        prost::encoding::skip_field(
            wire_type,
            tag,
            &mut empty_slice,
            prost::encoding::DecodeContext::default(),
        )
        .expect("protobuf field must skip cleanly");
    }

    assert!(
        !empty_tags.contains(&12),
        "tag 12 must be absent from encoded wire when retrieved_chunks is empty"
    );

    let decoded_empty = crate::pb::lancet::v1::RetrievalSnapshot::decode(&empty_buf[..])
        .expect("decoding empty snapshot must succeed");
    assert_eq!(decoded_empty, empty_chunks_snapshot);
    assert!(decoded_empty.retrieved_chunks.is_empty());
}

#[tokio::test]
async fn retrieve_populates_retrieved_chunks_in_rank_order() {
    use crate::workflow::nodes::RetrieveHybridNode;
    use crate::workflow::ports::FakeDenseRetrievalPort;
    use crate::workflow::{Node, WorkflowContext};
    use tokio_util::sync::CancellationToken;

    let c_1 = candidate(
        "00000000-0000-4000-8000-000000000001",
        "chunk-1",
        "Short text 1",
    );
    let c_2 = candidate(
        "00000000-0000-4000-8000-000000000002",
        "chunk-2",
        "Short text 2",
    );

    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![c_1.clone(), c_2.clone()]));
    let settings = RetrievalSettings::default();
    let node = RetrieveHybridNode::new(Some(fake_dense), None, None, settings);

    let req = crate::testkit::test_query_request("test query", "sess-1");
    let mut ctx = WorkflowContext::new("sess-1".into(), "trace-1".into(), &req);
    let cancel = CancellationToken::new();
    node.run(&mut ctx, &cancel).await.unwrap();

    let snapshot = ctx.snapshot.as_ref().expect("snapshot must be present");
    let chunk_ids: Vec<String> = snapshot
        .retrieved_chunks
        .iter()
        .map(|c| c.chunk_id.clone())
        .collect();
    assert_eq!(chunk_ids, ctx.final_candidates);
    assert_eq!(snapshot.retrieved_chunks.len(), 2);
    assert_eq!(snapshot.retrieved_chunks[0].rank, 1);
    assert_eq!(snapshot.retrieved_chunks[1].rank, 2);
    assert!(snapshot.retrieved_chunks[0].rank < snapshot.retrieved_chunks[1].rank);
}

#[tokio::test]
async fn retrieve_marks_truncated_retrieved_chunk_excerpt() {
    use crate::workflow::nodes::RetrieveHybridNode;
    use crate::workflow::ports::FakeDenseRetrievalPort;
    use crate::workflow::{Node, WorkflowContext};
    use tokio_util::sync::CancellationToken;

    let long_text = "This is a long chunk content exceeding sixteen characters.";
    let short_text = "Short text.";

    let c_long = candidate(
        "00000000-0000-4000-8000-000000000001",
        "chunk-long",
        long_text,
    );
    let c_short = candidate(
        "00000000-0000-4000-8000-000000000002",
        "chunk-short",
        short_text,
    );

    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![c_long.clone(), c_short.clone()]));
    let settings = RetrievalSettings::default();
    let node = RetrieveHybridNode::new(Some(fake_dense), None, None, settings)
        .with_excerpt_max_chars(16);

    let req = crate::testkit::test_query_request("test query", "sess-1");
    let mut ctx = WorkflowContext::new("sess-1".into(), "trace-1".into(), &req);
    let cancel = CancellationToken::new();
    node.run(&mut ctx, &cancel).await.unwrap();

    let snapshot = ctx.snapshot.as_ref().expect("snapshot must be present");
    assert_eq!(snapshot.retrieved_chunks.len(), 2);

    let long_res = &snapshot.retrieved_chunks[0];
    assert_eq!(long_res.chunk_id, "chunk-long");
    assert_eq!(long_res.excerpt.chars().count(), 16);
    assert_eq!(long_res.excerpt, "This is a long c");
    assert!(long_res.is_truncated);

    let short_res = &snapshot.retrieved_chunks[1];
    assert_eq!(short_res.chunk_id, "chunk-short");
    assert_eq!(short_res.excerpt, short_text);
    assert!(!short_res.is_truncated);
}

#[tokio::test]
async fn retrieve_empty_candidates_leaves_snapshot_some_with_empty_retrieved_chunks() {
    use crate::workflow::nodes::RetrieveHybridNode;
    use crate::workflow::ports::FakeDenseRetrievalPort;
    use crate::workflow::{Node, WorkflowContext};
    use tokio_util::sync::CancellationToken;

    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![]));
    let settings = RetrievalSettings::default();
    let node = RetrieveHybridNode::new(Some(fake_dense), None, None, settings);

    let req = crate::testkit::test_query_request("test query", "sess-1");
    let mut ctx = WorkflowContext::new("sess-1".into(), "trace-1".into(), &req);
    let cancel = CancellationToken::new();
    node.run(&mut ctx, &cancel).await.unwrap();

    assert!(ctx.snapshot.is_some(), "ctx.snapshot must be Some even on zero evidence");
    let snapshot = ctx.snapshot.as_ref().unwrap();
    assert!(snapshot.retrieved_chunks.is_empty(), "retrieved_chunks must be empty");
}

// ---------------------------------------------------------------------------
// Graph-off invariance pins (06.3.4.1-15, D-76 and D-81 comparability)
//
// `testdata/graph_off_fusion.golden` was recorded by running the fusion code as it stood before
// the graph list existed (HEAD 8899b6b5), over the scenarios below. The expected text is never
// rebuilt from the code under test.
// ---------------------------------------------------------------------------

const PIN_DOC_ONE: &str = "00000000-0000-4000-8000-0000000000a1";
const PIN_DOC_TWO: &str = "00000000-0000-4000-8000-0000000000a2";
const PIN_DOC_THREE: &str = "00000000-0000-4000-8000-0000000000a3";

/// A candidate whose content names the path that produced it, so the pin shows which copy of a
/// chunk found by two paths becomes the canonical one.
fn pin_candidate(chunk: &str, source: &str, score: f64) -> Candidate {
    let (document_id, chunk_index) = match chunk {
        "c1" | "c2" | "c3" => (PIN_DOC_ONE, chunk[1..].parse::<i32>().unwrap()),
        "c4" | "c5" | "c6" => (PIN_DOC_TWO, chunk[1..].parse::<i32>().unwrap()),
        _ => (PIN_DOC_THREE, chunk[1..].parse::<i32>().unwrap()),
    };
    let mut pinned = candidate(document_id, chunk, &format!("{source} {chunk}"));
    pinned.chunk_index = chunk_index;
    pinned.score = score;
    pinned
}

fn pin_list(source: &str, chunks: &[(&str, f64)]) -> Vec<Candidate> {
    chunks
        .iter()
        .map(|(chunk, score)| pin_candidate(chunk, source, *score))
        .collect()
}

fn pin_settings() -> RetrievalSettings {
    RetrievalSettings {
        candidate_limit: 12,
        final_limit: 8,
        vector_weight: 1.0,
        bm25_weight: 0.75,
        rrf_k: 60.0,
        ..RetrievalSettings::default()
    }
}

/// Every field of every fused candidate, with each float as its exact bit pattern.
fn render_fused(list: &[super::FusedCandidate]) -> String {
    list.iter()
        .map(|fused| {
            let provenance = fused
                .variant_provenance
                .iter()
                .map(|entry| {
                    format!(
                        "{}:{}:{}:{:016x}:{:016x}",
                        entry.variant_index,
                        serde_json::to_string(&entry.source).unwrap(),
                        entry.rank,
                        entry.score.to_bits(),
                        entry.contribution.to_bits()
                    )
                })
                .collect::<Vec<_>>()
                .join(",");
            format!(
                "{}|{}|{:016x}|{:?}|{:?}|{:?}|{:?}|{}",
                fused.candidate.chunk_id,
                fused.candidate.content,
                fused.fused_score.to_bits(),
                fused.vector_rank,
                fused.bm25_rank,
                fused.vector_score.map(f64::to_bits),
                fused.bm25_score.map(f64::to_bits),
                provenance
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// The cross-variant fusion call with no graph list, so the pins read the same before and after
/// the graph list gained its parameter.
fn cross_without_graph(
    lists: Vec<Vec<super::FusedCandidate>>,
    settings: &RetrievalSettings,
) -> Vec<super::FusedCandidate> {
    fuse_cross_variant_candidates(lists, vec![], settings).unwrap()
}

/// The graph-off scenarios: one variant, three variants, exact ties, and empty inputs.
fn graph_off_pin_scenarios() -> Vec<(&'static str, String)> {
    let settings = pin_settings();
    let dense = pin_list(
        "dense",
        &[("c1", 0.9), ("c2", 0.8), ("c3", 0.7), ("c4", 0.6)],
    );
    let single_bm25 = pin_list(
        "bm25",
        &[("c3", 12.0), ("c1", 9.5), ("c5", 4.0), ("c6", 1.5)],
    );
    let single = fuse_candidates(dense.clone(), single_bm25, &settings).unwrap();
    let single_cross = cross_without_graph(vec![single.clone()], &settings);

    let v0 = fuse_candidates(
        dense,
        pin_list("bm25", &[("c2", 8.0), ("c1", 6.0), ("c7", 2.0)]),
        &settings,
    )
    .unwrap();
    let v1 = fuse_candidates(
        vec![],
        pin_list("bm25", &[("c1", 7.0), ("c5", 5.0), ("c8", 3.0)]),
        &settings,
    )
    .unwrap();
    let v2 = fuse_candidates(
        vec![],
        pin_list("bm25", &[("c5", 9.0), ("c2", 4.0), ("c9", 1.0)]),
        &settings,
    )
    .unwrap();
    let three = cross_without_graph(vec![v0, v1, v2], &settings);

    let tie_a = fuse_candidates(
        vec![],
        pin_list("bm25", &[("c4", 3.0), ("c5", 2.0)]),
        &settings,
    )
    .unwrap();
    let tie_b = fuse_candidates(
        vec![],
        pin_list("bm25", &[("c5", 3.0), ("c4", 2.0)]),
        &settings,
    )
    .unwrap();
    let tied = cross_without_graph(vec![tie_a, tie_b], &settings);

    vec![
        ("single_variant_fused", render_fused(&single)),
        ("single_variant_cross", render_fused(&single_cross)),
        ("three_variants_cross", render_fused(&three)),
        ("two_variants_exact_ties_cross", render_fused(&tied)),
        (
            "no_variants",
            render_fused(&cross_without_graph(vec![], &settings)),
        ),
        (
            "one_empty_variant",
            render_fused(&cross_without_graph(vec![vec![]], &settings)),
        ),
        (
            "two_empty_variants",
            render_fused(&cross_without_graph(vec![vec![], vec![]], &settings)),
        ),
    ]
}

#[test]
fn graph_off_fusion_is_byte_identical_to_the_recorded_pre_change_output() {
    let golden = include_str!("testdata/graph_off_fusion.golden").replace("\r\n", "\n");
    let mut current = String::new();
    for (name, rendered) in graph_off_pin_scenarios() {
        current.push_str(&format!("== {name} ==\n{rendered}\n"));
    }
    assert_eq!(
        current, golden,
        "graph-off fusion must match the output recorded before the graph list existed"
    );
}

// ---------------------------------------------------------------------------
// The graph chunk list as a third RRF list (06.3.4.1-15, D-76)
// ---------------------------------------------------------------------------

/// Chunks the graph offers, in graph rank order. A graph candidate has no source score of its own.
fn graph_list(chunks: &[&str]) -> Vec<Candidate> {
    chunks
        .iter()
        .map(|chunk| pin_candidate(chunk, "graph", 0.0))
        .collect()
}

fn with_graph_rrf_weight(weight: f64) -> RetrievalSettings {
    RetrievalSettings {
        graph_rrf_weight: weight,
        ..pin_settings()
    }
}

fn find<'a>(list: &'a [super::FusedCandidate], chunk_id: &str) -> &'a super::FusedCandidate {
    list.iter()
        .find(|fused| fused.candidate.chunk_id == chunk_id)
        .unwrap_or_else(|| panic!("{chunk_id} must be in the fused list"))
}

/// One dense list and one BM25 list for variant zero, and a BM25-only list for each extra variant.
fn variant_lists(
    extra_variants: usize,
    settings: &RetrievalSettings,
) -> Vec<Vec<super::FusedCandidate>> {
    let variant_zero = fuse_candidates(
        pin_list("dense", &[("c1", 0.9), ("c2", 0.8)]),
        pin_list("bm25", &[("c2", 5.0), ("c3", 4.0)]),
        settings,
    )
    .unwrap();
    let mut lists = vec![variant_zero];
    for extra in 0..extra_variants {
        let bm25: &[(&str, f64)] = if extra == 0 {
            &[("c3", 6.0), ("c4", 5.0)]
        } else {
            &[("c4", 7.0), ("c5", 6.0)]
        };
        lists.push(fuse_candidates(vec![], pin_list("bm25", bm25), settings).unwrap());
    }
    lists
}

fn chunk_order(list: &[super::FusedCandidate]) -> Vec<&str> {
    list.iter()
        .map(|fused| fused.candidate.chunk_id.as_str())
        .collect()
}

#[test]
fn a_graph_only_candidate_enters_with_graph_provenance_and_the_graph_weight() {
    let settings = with_graph_rrf_weight(0.5);
    let fused = fuse_cross_variant_candidates(
        variant_lists(0, &settings),
        graph_list(&["c7", "c8"]),
        &settings,
    )
    .unwrap();

    for (chunk, rank) in [("c7", 1_usize), ("c8", 2)] {
        let entry = find(&fused, chunk);
        let contribution = 0.5 / (60.0 + rank as f64);
        assert_eq!(entry.fused_score, contribution);
        assert_eq!(
            entry.variant_provenance,
            vec![super::VariantProvenance {
                variant_index: 0,
                source: VariantProvenanceSource::Graph,
                rank,
                score: 0.0,
                contribution,
            }]
        );
        assert_eq!(entry.vector_rank, None);
        assert_eq!(entry.bm25_rank, None);
        assert!(entry.graph_boosted());
    }
    assert!(!find(&fused, "c1").graph_boosted());
}

#[test]
fn a_graph_candidate_also_found_by_dense_gets_the_summed_score_and_both_provenances() {
    let settings = with_graph_rrf_weight(0.5);
    let fused =
        fuse_cross_variant_candidates(variant_lists(0, &settings), graph_list(&["c1"]), &settings)
            .unwrap();

    let entry = find(&fused, "c1");
    assert_eq!(entry.fused_score, 1.0 / 61.0 + 0.5 / 61.0);
    let sources: Vec<_> = entry.variant_provenance.iter().map(|p| p.source).collect();
    assert_eq!(
        sources,
        vec![
            VariantProvenanceSource::Vector,
            VariantProvenanceSource::Graph
        ]
    );
    assert_eq!(entry.vector_rank, Some(1));
    assert_eq!(
        entry.candidate.content, "dense c1",
        "the copy from the first path stays canonical"
    );
    assert!(entry.graph_boosted());
}

#[test]
fn a_graph_boost_can_move_a_chunk_ahead_and_a_tie_keeps_the_incoming_order() {
    let settings = with_graph_rrf_weight(1.0);
    // Dense alone: c1 (1/61) then c2 (1/62). The graph also found c2, which lifts it above c1.
    let boosted = fuse_cross_variant_candidates(
        vec![fuse_candidates(
            pin_list("dense", &[("c1", 0.9), ("c2", 0.8)]),
            vec![],
            &settings,
        )
        .unwrap()],
        graph_list(&["c2"]),
        &settings,
    )
    .unwrap();
    assert_eq!(chunk_order(&boosted), vec!["c2", "c1"]);

    // The graph-only c7 at rank 1 scores exactly what c1 scores at dense rank 1: the existing
    // chunk keeps its place and the graph-only chunk follows it.
    let tied = fuse_cross_variant_candidates(
        vec![fuse_candidates(pin_list("dense", &[("c1", 0.9)]), vec![], &settings).unwrap()],
        graph_list(&["c7"]),
        &settings,
    )
    .unwrap();
    assert_eq!(chunk_order(&tied), vec!["c1", "c7"]);
}

#[test]
fn graph_only_candidates_follow_the_graph_rank_order() {
    let settings = with_graph_rrf_weight(1.0);
    let fused =
        fuse_cross_variant_candidates(vec![], graph_list(&["c9", "c7", "c8"]), &settings).unwrap();
    assert_eq!(chunk_order(&fused), vec!["c9", "c7", "c8"]);
}

#[test]
fn a_zero_graph_weight_ignores_the_graph_list() {
    let off = with_graph_rrf_weight(0.0);
    let ignored =
        fuse_cross_variant_candidates(variant_lists(2, &off), graph_list(&["c1", "c7"]), &off)
            .unwrap();
    let without = fuse_cross_variant_candidates(variant_lists(2, &off), vec![], &off).unwrap();
    assert_eq!(render_fused(&ignored), render_fused(&without));
    assert!(ignored.iter().all(|fused| !fused.graph_boosted()));
}

#[test]
fn the_graph_contribution_does_not_scale_with_the_variant_count() {
    let settings = with_graph_rrf_weight(0.5);
    for extra_variants in [0_usize, 2] {
        let without = fuse_cross_variant_candidates(
            variant_lists(extra_variants, &settings),
            vec![],
            &settings,
        )
        .unwrap();
        let with = fuse_cross_variant_candidates(
            variant_lists(extra_variants, &settings),
            graph_list(&["c7", "c2"]),
            &settings,
        )
        .unwrap();

        // c7 is graph-only, so its whole score is the graph contribution at rank 1.
        assert_eq!(
            find(&with, "c7").fused_score,
            0.5 / 61.0,
            "{extra_variants} extra variants"
        );
        // c2 is found by dense and BM25; the graph adds the rank 2 contribution once.
        let gain = find(&with, "c2").fused_score - find(&without, "c2").fused_score;
        assert!(
            (gain - 0.5 / 62.0).abs() < 1e-15,
            "{extra_variants} extra variants: gain {gain}"
        );
        for chunk in ["c7", "c2"] {
            let graph_entries = find(&with, chunk)
                .variant_provenance
                .iter()
                .filter(|entry| entry.source == VariantProvenanceSource::Graph)
                .count();
            assert_eq!(
                graph_entries, 1,
                "{chunk} with {extra_variants} extra variants"
            );
        }
    }
}

#[test]
fn the_graph_list_is_deduplicated_and_bounded_by_the_candidate_limit() {
    let settings = RetrievalSettings {
        candidate_limit: 3,
        final_limit: 2,
        ..with_graph_rrf_weight(1.0)
    };
    let fused = fuse_cross_variant_candidates(
        vec![],
        graph_list(&["c7", "c7", "c8", "c9", "c6"]),
        &settings,
    )
    .unwrap();
    assert_eq!(
        chunk_order(&fused),
        vec!["c7", "c8", "c9"],
        "the duplicate is dropped before ranking and only candidate_limit entries are used"
    );
}

#[test]
fn a_non_finite_graph_score_is_rejected_unless_the_list_is_ignored() {
    let mut bad = graph_list(&["c7"]);
    bad[0].score = f64::NAN;
    let settings = with_graph_rrf_weight(1.0);
    let error = fuse_cross_variant_candidates(vec![], bad.clone(), &settings).unwrap_err();
    assert_eq!(error.kind, RetrievalErrorKind::NonFiniteScore);

    let off = with_graph_rrf_weight(0.0);
    assert!(fuse_cross_variant_candidates(vec![], bad, &off)
        .unwrap()
        .is_empty());
}

#[test]
fn graph_provenance_serialises_as_graph_and_a_dense_hit_is_not_a_boost() {
    assert_eq!(
        serde_json::to_string(&VariantProvenanceSource::Graph).unwrap(),
        "\"graph\""
    );
    let settings = with_graph_rrf_weight(1.0);
    let plain = fuse_candidates(pin_list("dense", &[("c1", 0.9)]), vec![], &settings).unwrap();
    assert!(
        !plain[0].graph_boosted(),
        "a dense hit is not graph-boosted"
    );
}

#[test]
fn the_prompt_packing_graph_weight_never_reaches_fusion() {
    let quiet = RetrievalSettings {
        graph_weight: 0.0,
        ..with_graph_rrf_weight(0.5)
    };
    let loud = RetrievalSettings {
        graph_weight: 9.0,
        ..with_graph_rrf_weight(0.5)
    };
    let fuse = |settings: &RetrievalSettings| {
        render_fused(
            &fuse_cross_variant_candidates(
                variant_lists(1, settings),
                graph_list(&["c2", "c7"]),
                settings,
            )
            .unwrap(),
        )
    };
    assert_eq!(fuse(&quiet), fuse(&loud));
    assert!(
        fuse(&quiet).contains("\"graph\""),
        "the graph list was applied"
    );
}

#[test]
fn graph_rrf_weight_is_validated_like_the_other_weights_and_is_not_part_of_the_nonzero_rule() {
    for invalid in [
        f64::NAN,
        f64::INFINITY,
        -0.1,
        super::MAX_SERVICE_RRF_WEIGHT + 1.0,
    ] {
        let error = with_graph_rrf_weight(invalid).validate().unwrap_err();
        assert_eq!(error.kind, RetrievalErrorKind::InvalidSettings);
        assert!(
            error.message().contains("graph_rrf_weight"),
            "{}",
            error.message()
        );
    }
    with_graph_rrf_weight(0.0)
        .validate()
        .expect("0.0 turns the graph list off and is valid");
    let only_graph = RetrievalSettings {
        vector_weight: 0.0,
        bm25_weight: 0.0,
        ..with_graph_rrf_weight(1.0)
    };
    assert!(
        only_graph.validate().is_err(),
        "a graph weight cannot stand in for the dense and BM25 weights"
    );
}
