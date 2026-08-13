use super::{NoOpReranker, Reranker};
use crate::retrieval::{Candidate, FusedCandidate};

fn fused_candidate(chunk_id: &str, score: f64) -> FusedCandidate {
    FusedCandidate {
        candidate: Candidate {
            document_id: "00000000-0000-4000-8000-000000000001".to_owned(),
            chunk_id: chunk_id.to_owned(),
            chunk_index: 2,
            char_start: 10,
            char_end: 30,
            content: "untrusted evidence".to_owned(),
            title: Some("Title".to_owned()),
            section_path: Some("Section".to_owned()),
            content_type: None,
            embedding_model: Some("model".to_owned()),
            ingested_at: Some(42),
            score,
        },
        fused_score: score / 3.0,
        vector_rank: Some(1),
        bm25_rank: Some(2),
        vector_score: Some(score),
        bm25_score: Some(score / 2.0),
        variant_provenance: Vec::new(),
    }
}

#[tokio::test]
async fn noop_reranker_preserves_candidates() {
    let input = vec![
        fused_candidate("chunk-a", 0.123456789012345),
        fused_candidate("chunk-b", 0.987654321098765),
    ];
    let implementation = NoOpReranker::new();
    let reranker: &dyn Reranker = &implementation;
    let output = reranker.rerank(input.clone()).await.unwrap();
    assert_eq!(output, input);
    assert_eq!(
        serde_json::to_vec(&output).unwrap(),
        serde_json::to_vec(&input).unwrap()
    );
}
