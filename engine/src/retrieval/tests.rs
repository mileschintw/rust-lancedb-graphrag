use std::sync::Arc;

use arrow_array::{
    new_null_array, types::Float32Type, FixedSizeListArray, Int32Array, Int64Array, RecordBatch,
    StringArray,
};
use engine::db::DatabaseManager;
use uuid::Uuid;

use super::bm25::analyze;
use super::{
    fuse_candidates, Bm25Config, Bm25Index, Candidate, DenseRetriever, QueryFilters, QueryRequest,
    RetrievalSettings,
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
            nullable("community_ids"),
            nullable("summary"),
            nullable("summary_vector"),
            nullable("unsummarized_refs"),
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
        candidate_limit: i32::MAX as usize,
        final_limit: i32::MAX as usize,
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
