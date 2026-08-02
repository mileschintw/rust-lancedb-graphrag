use uuid::Uuid;

use super::bm25::analyze;
use super::{Bm25Config, Bm25Index, Candidate, QueryFilters, QueryRequest, RetrievalSettings};

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
