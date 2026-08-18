//! Deterministic weighted Reciprocal Rank Fusion for dense and BM25 results.
//!
//! Fusion keeps one canonical candidate per `chunk_id`, retains both source
//! ranks and scores, and uses the configured full-precision RRF score for the
//! final order. Ties use the D-51 key: best source rank, document ID, chunk
//! index, then chunk ID.

use std::collections::BTreeMap;

use serde::Serialize;

use super::{Candidate, RetrievalError, RetrievalErrorKind, RetrievalSettings};

/// Identifies the retrieval path that contributed a provenance entry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum VariantProvenanceSource {
    #[serde(rename = "vector")]
    Vector,
    #[serde(rename = "bm25")]
    Bm25,
}

/// Provenance contribution entry for a variant/source candidate.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct VariantProvenance {
    pub variant_index: usize,
    pub source: VariantProvenanceSource,
    pub rank: usize,
    pub score: f64,
    pub contribution: f64,
}

/// A deduplicated candidate with source provenance and its full-precision RRF score.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct FusedCandidate {
    pub candidate: Candidate,
    pub fused_score: f64,
    pub vector_rank: Option<usize>,
    pub bm25_rank: Option<usize>,
    pub vector_score: Option<f64>,
    pub bm25_score: Option<f64>,
    pub variant_provenance: Vec<VariantProvenance>,
}

#[derive(Debug)]
struct Accumulator {
    candidate: Candidate,
    fused_score: f64,
    vector_rank: Option<usize>,
    bm25_rank: Option<usize>,
    vector_score: Option<f64>,
    bm25_score: Option<f64>,
    variant_provenance: Vec<VariantProvenance>,
}

fn deduplicate_source_candidates(
    candidates: Vec<Candidate>,
) -> Result<Vec<Candidate>, RetrievalError> {
    let mut seen = std::collections::HashSet::with_capacity(candidates.len());
    let mut deduplicated = Vec::with_capacity(candidates.len());
    for candidate in candidates {
        if !candidate.score.is_finite() {
            return Err(RetrievalError::new(
                RetrievalErrorKind::NonFiniteScore,
                format!(
                    "candidate {} has a non-finite source score",
                    candidate.chunk_id
                ),
            ));
        }
        if seen.insert(candidate.chunk_id.clone()) {
            deduplicated.push(candidate);
        }
    }
    Ok(deduplicated)
}

/// Fuses single-variant vector and BM25 candidate lists.
pub fn fuse_candidates(
    vector_candidates: Vec<Candidate>,
    bm25_candidates: Vec<Candidate>,
    settings: &RetrievalSettings,
) -> Result<Vec<FusedCandidate>, RetrievalError> {
    fuse_variant_candidates(vector_candidates, vec![bm25_candidates], settings)
}

/// Fuses variant 0 vector candidates with per-variant BM25 candidate lists across up to 8 variants.
pub fn fuse_variant_candidates(
    vector_candidates: Vec<Candidate>,
    bm25_candidates_per_variant: Vec<Vec<Candidate>>,
    settings: &RetrievalSettings,
) -> Result<Vec<FusedCandidate>, RetrievalError> {
    settings.validate()?;

    if bm25_candidates_per_variant.len() > 8 {
        return Err(RetrievalError::new(
            RetrievalErrorKind::InvalidSettings,
            "maximum 8 variants supported in fusion",
        ));
    }

    let vector_candidates = deduplicate_source_candidates(vector_candidates)?;
    let mut fused = BTreeMap::new();

    // 1. Vector candidates (associated with variant 0)
    if settings.vector_weight != 0.0 {
        for (rank, candidate) in vector_candidates
            .into_iter()
            .take(settings.candidate_limit)
            .enumerate()
        {
            add_variant_candidate(
                &mut fused,
                candidate,
                0,
                VariantProvenanceSource::Vector,
                rank + 1,
                settings.vector_weight,
                settings.rrf_k,
            )?;
        }
    }

    // 2. BM25 candidates per variant
    if settings.bm25_weight != 0.0 {
        for (variant_idx, bm25_candidates) in bm25_candidates_per_variant.into_iter().enumerate() {
            let bm25_candidates = deduplicate_source_candidates(bm25_candidates)?;
            for (rank, candidate) in bm25_candidates
                .into_iter()
                .take(settings.candidate_limit)
                .enumerate()
            {
                add_variant_candidate(
                    &mut fused,
                    candidate,
                    variant_idx,
                    VariantProvenanceSource::Bm25,
                    rank + 1,
                    settings.bm25_weight,
                    settings.rrf_k,
                )?;
            }
        }
    }

    let mut results = fused
        .into_values()
        .map(|value| {
            // Public vector/bm25 rank and score fields use the highest-scoring contribution with lowest variant-index tie-break.
            let (vector_rank, vector_score) = value
                .variant_provenance
                .iter()
                .filter(|p| p.source == VariantProvenanceSource::Vector)
                .min_by(|a, b| {
                    b.score
                        .total_cmp(&a.score)
                        .then_with(|| a.variant_index.cmp(&b.variant_index))
                })
                .map(|p| (Some(p.rank), Some(p.score)))
                .unwrap_or((value.vector_rank, value.vector_score));

            let (bm25_rank, bm25_score) = value
                .variant_provenance
                .iter()
                .filter(|p| p.source == VariantProvenanceSource::Bm25)
                .min_by(|a, b| {
                    b.score
                        .total_cmp(&a.score)
                        .then_with(|| a.variant_index.cmp(&b.variant_index))
                })
                .map(|p| (Some(p.rank), Some(p.score)))
                .unwrap_or((value.bm25_rank, value.bm25_score));

            FusedCandidate {
                candidate: value.candidate,
                fused_score: value.fused_score,
                vector_rank,
                bm25_rank,
                vector_score,
                bm25_score,
                variant_provenance: value.variant_provenance,
            }
        })
        .collect::<Vec<_>>();

    results.sort_by(|left, right| {
        right
            .fused_score
            .total_cmp(&left.fused_score)
            .then_with(|| best_rank(left).cmp(&best_rank(right)))
            .then_with(|| left.candidate.sort_key().cmp(&right.candidate.sort_key()))
    });
    Ok(results)
}

fn add_variant_candidate(
    fused: &mut BTreeMap<String, Accumulator>,
    candidate: Candidate,
    variant_index: usize,
    source: VariantProvenanceSource,
    rank: usize,
    weight: f64,
    rrf_k: f64,
) -> Result<(), RetrievalError> {
    if weight == 0.0 {
        return Ok(());
    }
    if !candidate.score.is_finite() {
        return Err(RetrievalError::new(
            RetrievalErrorKind::NonFiniteScore,
            format!(
                "candidate {} has a non-finite source score",
                candidate.chunk_id
            ),
        ));
    }
    if !weight.is_finite() || !rrf_k.is_finite() {
        return Err(RetrievalError::new(
            RetrievalErrorKind::NonFiniteScore,
            "non-finite weight or rrf_k",
        ));
    }
    let source_score = candidate.score;
    let chunk_id = candidate.chunk_id.clone();
    let denominator = rrf_k + rank as f64;
    let contribution = weight / denominator;
    if !contribution.is_finite() {
        return Err(RetrievalError::new(
            RetrievalErrorKind::NonFiniteScore,
            format!(
                "non-finite contribution for candidate {}",
                candidate.chunk_id
            ),
        ));
    }

    let prov = VariantProvenance {
        variant_index,
        source,
        rank,
        score: source_score,
        contribution,
    };

    let entry = fused.entry(chunk_id).or_insert_with(|| Accumulator {
        candidate: candidate.clone(),
        fused_score: 0.0,
        vector_rank: None,
        bm25_rank: None,
        vector_score: None,
        bm25_score: None,
        variant_provenance: Vec::new(),
    });

    entry.fused_score += contribution;
    if !entry.fused_score.is_finite() {
        return Err(RetrievalError::new(
            RetrievalErrorKind::NonFiniteScore,
            format!(
                "non-finite accumulator for candidate {}",
                candidate.chunk_id
            ),
        ));
    }

    entry.variant_provenance.push(prov);

    match source {
        VariantProvenanceSource::Vector => {
            if entry.vector_rank.is_none() {
                entry.vector_rank = Some(rank);
                entry.vector_score = Some(source_score);
                if entry.bm25_rank.is_some() {
                    entry.candidate = candidate;
                }
            }
        }
        VariantProvenanceSource::Bm25 => {
            if entry.bm25_rank.is_none() {
                entry.bm25_rank = Some(rank);
                entry.bm25_score = Some(source_score);
                if entry.vector_rank.is_none() {
                    entry.candidate = candidate;
                }
            }
        }
    }
    Ok(())
}

fn best_rank(candidate: &FusedCandidate) -> usize {
    candidate
        .vector_rank
        .into_iter()
        .chain(candidate.bm25_rank)
        .min()
        .unwrap_or(usize::MAX)
}
