//! Deterministic weighted Reciprocal Rank Fusion for dense and BM25 results.
//!
//! Fusion keeps one canonical candidate per `chunk_id`, retains both source
//! ranks and scores, and uses the configured full-precision RRF score for the
//! final order. Ties use the D-51 key: best source rank, document ID, chunk
//! index, then chunk ID.
//!
//! Multi-variant reformulation uses a two-pass architecture: `fuse_candidates`
//! produces per-variant fused outputs (dense + BM25 for variant 0, BM25-only for
//! variants 1..N), and `fuse_cross_variant_candidates` performs a second RRF merge
//! across those per-variant outputs with documented scoring and deterministic tie rules.

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

/// Fuses single-variant vector and BM25 candidate lists using weighted RRF.
///
/// Dense and BM25 candidates are deduplicated per-source and weighted according to
/// `settings.vector_weight` and `settings.bm25_weight`.
pub fn fuse_candidates(
    vector_candidates: Vec<Candidate>,
    bm25_candidates: Vec<Candidate>,
    settings: &RetrievalSettings,
) -> Result<Vec<FusedCandidate>, RetrievalError> {
    settings.validate()?;

    let vector_candidates = deduplicate_source_candidates(vector_candidates)?;
    let mut fused = BTreeMap::new();

    // 1. Vector candidates (associated with variant 0)
    if settings.vector_weight != 0.0 {
        for (rank, candidate) in vector_candidates
            .into_iter()
            .take(settings.candidate_limit)
            .enumerate()
        {
            add_source_candidate(
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

    // 2. BM25 candidates (associated with variant 0)
    if settings.bm25_weight != 0.0 {
        let bm25_candidates = deduplicate_source_candidates(bm25_candidates)?;
        for (rank, candidate) in bm25_candidates
            .into_iter()
            .take(settings.candidate_limit)
            .enumerate()
        {
            add_source_candidate(
                &mut fused,
                candidate,
                0,
                VariantProvenanceSource::Bm25,
                rank + 1,
                settings.bm25_weight,
                settings.rrf_k,
            )?;
        }
    }

    let mut results = fused
        .into_values()
        .map(|value| {
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

#[derive(Debug)]
struct CrossVariantAccumulator {
    candidate: Candidate,
    cross_variant_score: f64,
    best_inner_fused_score: f64,
    best_variant_rank: usize,
    first_variant_index: usize,
    selected_variant_index: usize,
    selected_per_variant_rank: usize,
    vector_rank: Option<usize>,
    bm25_rank: Option<usize>,
    vector_score: Option<f64>,
    bm25_score: Option<f64>,
    variant_provenance: Vec<VariantProvenance>,
}

/// Fuses per-variant fused candidate lists into a single ranked list using a second RRF merge pass.
///
/// For a single variant, returns the established single-variant fused candidate scores, fields,
/// re-tagged provenance, and order unchanged.
///
/// For two or more variants, computes the cross-variant score as:
/// `sum(1.0 / (settings.rrf_k + rank as f64))`
/// over each occurrence's 1-based rank in the per-variant sorted `fuse_candidates` outputs.
/// Non-finite contributions and totals are rejected.
///
/// Candidate metadata is selected from the occurrence with the highest inner `fused_score`, breaking
/// ties by lower outer variant index, lower per-variant rank, then the candidate identity sort key.
///
/// Final results are sorted by:
/// 1. `cross_variant_score` descending
/// 2. Best (lowest) per-variant rank ascending
/// 3. First outer variant index ascending
/// 4. Candidate identity sort key (`(&candidate.document_id, candidate.chunk_index, &candidate.chunk_id)`) ascending.
pub fn fuse_cross_variant_candidates(
    variant_fused_candidates: Vec<Vec<FusedCandidate>>,
    settings: &RetrievalSettings,
) -> Result<Vec<FusedCandidate>, RetrievalError> {
    settings.validate()?;

    if variant_fused_candidates.len() > 8 {
        return Err(RetrievalError::new(
            RetrievalErrorKind::InvalidSettings,
            "maximum 8 variants supported in fusion",
        ));
    }

    if variant_fused_candidates.is_empty() {
        return Ok(Vec::new());
    }

    if variant_fused_candidates.len() == 1 {
        let mut single_list = variant_fused_candidates.into_iter().next().unwrap();
        for item in &mut single_list {
            for prov in &mut item.variant_provenance {
                prov.variant_index = 0;
            }
        }
        return Ok(single_list);
    }

    let mut merged: BTreeMap<String, CrossVariantAccumulator> = BTreeMap::new();

    for (variant_index, variant_list) in variant_fused_candidates.into_iter().enumerate() {
        for (rank_idx, fused_candidate) in variant_list
            .into_iter()
            .take(settings.candidate_limit)
            .enumerate()
        {
            let rank = rank_idx + 1;
            let denominator = settings.rrf_k + rank as f64;
            let contribution = 1.0 / denominator;
            if !contribution.is_finite() {
                return Err(RetrievalError::new(
                    RetrievalErrorKind::NonFiniteScore,
                    format!(
                        "non-finite cross-variant contribution for candidate {}",
                        fused_candidate.candidate.chunk_id
                    ),
                ));
            }

            let chunk_id = fused_candidate.candidate.chunk_id.clone();
            let inner_fused_score = fused_candidate.fused_score;
            let candidate_data = fused_candidate.candidate;
            let vector_rank = fused_candidate.vector_rank;
            let bm25_rank = fused_candidate.bm25_rank;
            let vector_score = fused_candidate.vector_score;
            let bm25_score = fused_candidate.bm25_score;

            // Re-tag each inner provenance entry with the outer variant_index
            let mut retagged_provenance = fused_candidate.variant_provenance;
            for prov in &mut retagged_provenance {
                prov.variant_index = variant_index;
            }

            let entry = merged.entry(chunk_id).or_insert_with(|| CrossVariantAccumulator {
                candidate: candidate_data.clone(),
                cross_variant_score: 0.0,
                best_inner_fused_score: f64::NEG_INFINITY,
                best_variant_rank: usize::MAX,
                first_variant_index: variant_index,
                selected_variant_index: usize::MAX,
                selected_per_variant_rank: usize::MAX,
                vector_rank: None,
                bm25_rank: None,
                vector_score: None,
                bm25_score: None,
                variant_provenance: Vec::new(),
            });

            entry.cross_variant_score += contribution;
            if !entry.cross_variant_score.is_finite() {
                return Err(RetrievalError::new(
                    RetrievalErrorKind::NonFiniteScore,
                    format!(
                        "non-finite cross-variant accumulator for candidate {}",
                        entry.candidate.chunk_id
                    ),
                ));
            }

            if rank < entry.best_variant_rank {
                entry.best_variant_rank = rank;
            }

            let is_better_metadata = match inner_fused_score.total_cmp(&entry.best_inner_fused_score) {
                std::cmp::Ordering::Greater => true,
                std::cmp::Ordering::Equal => {
                    match variant_index.cmp(&entry.selected_variant_index) {
                        std::cmp::Ordering::Less => true,
                        std::cmp::Ordering::Equal => {
                            match rank.cmp(&entry.selected_per_variant_rank) {
                                std::cmp::Ordering::Less => true,
                                std::cmp::Ordering::Equal => {
                                    candidate_data.sort_key() < entry.candidate.sort_key()
                                }
                                std::cmp::Ordering::Greater => false,
                            }
                        }
                        std::cmp::Ordering::Greater => false,
                    }
                }
                std::cmp::Ordering::Less => false,
            };

            if is_better_metadata {
                entry.candidate = candidate_data;
                entry.best_inner_fused_score = inner_fused_score;
                entry.selected_variant_index = variant_index;
                entry.selected_per_variant_rank = rank;
                entry.vector_rank = vector_rank;
                entry.bm25_rank = bm25_rank;
                entry.vector_score = vector_score;
                entry.bm25_score = bm25_score;
            }

            entry.variant_provenance.extend(retagged_provenance);
        }
    }

    let mut results: Vec<(CrossVariantAccumulator, usize, usize)> = merged
        .into_values()
        .map(|value| {
            let best_rank = value.best_variant_rank;
            let first_var = value.first_variant_index;
            (value, best_rank, first_var)
        })
        .collect();

    results.sort_by(|(left, left_best_rank, left_first_var), (right, right_best_rank, right_first_var)| {
        right
            .cross_variant_score
            .total_cmp(&left.cross_variant_score)
            .then_with(|| left_best_rank.cmp(right_best_rank))
            .then_with(|| left_first_var.cmp(right_first_var))
            .then_with(|| left.candidate.sort_key().cmp(&right.candidate.sort_key()))
    });

    let final_candidates = results
        .into_iter()
        .map(|(value, _, _)| {
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
                fused_score: value.cross_variant_score,
                vector_rank,
                bm25_rank,
                vector_score,
                bm25_score,
                variant_provenance: value.variant_provenance,
            }
        })
        .collect();

    Ok(final_candidates)
}

fn add_source_candidate(
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
