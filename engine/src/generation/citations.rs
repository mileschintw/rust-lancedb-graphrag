//! Deterministic, network-free citation-marker normalization and resolution (D-14).
//!
//! This module implements the normalize-then-strip half of DEBT-RAG-03's citation repair:
//! it locates numbered citation markers in an answer, decides which packed evidence
//! identifier (if any) each one means, and reports the outcome. It performs no input or
//! output of its own and makes no request of any kind — repair is one local, synchronous
//! pass.
//!
//! # Extraction grammar
//! Markers are located with a widened form of the digit-only `[<digits>]` scan used
//! elsewhere in generation: an opening `[`, optional ASCII whitespace, one or more ASCII
//! digits, optional ASCII whitespace, and a closing `]`. The **original span** for a match
//! is the inclusive slice from that opening `[` through that closing `]`, including any
//! interior whitespace — for example `[ 7 ]` is one marker whose original span is the full
//! four-character-wider substring, not the digit-only token `[7]`. Extraction never looks
//! past the answer text itself and never consults a marker's would-be resolution.
//!
//! # Normalization
//! A marker and an evidence identifier are compared by applying the same normalization
//! function to both sides, in order: Unicode compatibility composition (NFKC), full
//! Unicode case folding, ASCII whitespace trimming with internal-whitespace collapse, then
//! stripping of surrounding marker syntax (`[`, `]`, `(`, `)`, and any whitespace they
//! enclosed). Applying the identical function to both sides is what makes the comparison
//! symmetric: normalizing only the marker would make resolution depend on how the evidence
//! identifiers happen to be spelled.
//!
//! # Resolution and the tie rule
//! A marker **resolves** when its normalized form equals the normalized form of exactly
//! one evidence identifier. Zero matches is a **drop**. Two or more matches is also a
//! **drop** — the ambiguous case is never assigned to the first or best candidate, because
//! a plausible-looking wrong citation is worse than a disclosed missing one. A marker whose
//! raw text already equals the resolved identifier exactly, before normalization, is
//! reported **unchanged** rather than **repaired**, so a client can distinguish "nothing
//! changed" from "this citation was fixed."

use unicode_casefold::UnicodeCaseFold;
use unicode_normalization::UnicodeNormalization;

/// The byte-offset range of a marker's original span within the answer text.
///
/// `end` is exclusive, matching Rust's slice-range convention.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MarkerSpan {
    pub start: usize,
    pub end: usize,
}

/// One marker as located by [`extract_markers`]: its original text and byte-offset span.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExtractedMarker {
    /// The inclusive `[` through `]` slice exactly as it appears in the answer.
    pub original: String,
    pub span: MarkerSpan,
}

/// The outcome of resolving a single marker against the packed evidence set.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Resolution {
    /// The marker already equalled this evidence identifier exactly; nothing changed.
    Unchanged(String),
    /// The marker normalized onto exactly this evidence identifier.
    Repaired(String),
    /// The marker matched zero or more than one evidence identifier.
    Dropped,
}

/// A marker paired with its resolution outcome.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MarkerOutcome {
    pub original: String,
    pub span: MarkerSpan,
    pub resolution: Resolution,
}

/// Extracts widened `[` + optional ASCII whitespace + digits + optional ASCII whitespace +
/// `]` marker spans from `answer`, left to right.
///
/// This is the same left-to-right byte scan the digit-only extractor elsewhere in
/// generation uses, widened only to tolerate ASCII whitespace immediately inside the
/// brackets. A match's original span is the inclusive slice from the opening `[` through
/// the closing `]`, including any interior whitespace.
pub fn extract_markers(answer: &str) -> Vec<ExtractedMarker> {
    let bytes = answer.as_bytes();
    let mut markers = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'[' {
            let start = i;
            let mut j = i + 1;
            while j < bytes.len() && bytes[j].is_ascii_whitespace() {
                j += 1;
            }
            let digits_start = j;
            while j < bytes.len() && bytes[j].is_ascii_digit() {
                j += 1;
            }
            if j > digits_start {
                let mut k = j;
                while k < bytes.len() && bytes[k].is_ascii_whitespace() {
                    k += 1;
                }
                if k < bytes.len() && bytes[k] == b']' {
                    let end = k + 1;
                    markers.push(ExtractedMarker {
                        original: answer[start..end].to_string(),
                        span: MarkerSpan { start, end },
                    });
                    i = end;
                    continue;
                }
            }
            i = start + 1;
        } else {
            i += 1;
        }
    }
    markers
}

/// Normalizes a marker or evidence identifier into its comparison form.
///
/// Applies, in order: Unicode compatibility composition (NFKC), full Unicode case
/// folding, ASCII whitespace trimming with internal-whitespace collapse, then stripping
/// of surrounding marker syntax (`[`, `]`, `(`, `)`, and any whitespace they enclosed).
/// Running the identical function on both sides of a comparison is what makes resolution
/// symmetric rather than dependent on which side happens to be spelled which way.
pub fn normalize(value: &str) -> String {
    let composed: String = value.nfkc().collect();
    let folded: String = composed.case_fold().collect();
    let collapsed = collapse_whitespace(folded.trim());
    strip_marker_syntax(&collapsed)
}

fn collapse_whitespace(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    let mut last_was_space = false;
    for ch in value.chars() {
        if ch.is_whitespace() {
            if !last_was_space {
                out.push(' ');
            }
            last_was_space = true;
        } else {
            out.push(ch);
            last_was_space = false;
        }
    }
    out
}

fn strip_marker_syntax(value: &str) -> String {
    value
        .trim_matches(|c: char| matches!(c, '[' | ']' | '(' | ')'))
        .trim()
        .to_string()
}

/// Resolves each already-extracted marker against `evidence_ids`.
///
/// Resolution is order-independent: each marker is decided solely against
/// `evidence_ids`, never against its neighbors, so supplying the same markers in a
/// different order produces the same per-marker outcomes. The returned list preserves
/// the order of `markers` (which, for markers produced by [`extract_markers`], is the
/// order they appeared in the answer).
///
/// A marker resolves when its normalized form equals the normalized form of exactly one
/// entry in `evidence_ids`. Zero matches or two-or-more matches both drop the marker —
/// ties are never assigned to a candidate. An empty `markers` list returns an empty
/// outcome list; a non-empty `markers` list against an empty `evidence_ids` reports every
/// marker dropped.
pub fn resolve_markers(markers: &[ExtractedMarker], evidence_ids: &[&str]) -> Vec<MarkerOutcome> {
    markers
        .iter()
        .map(|marker| {
            let normalized_marker = normalize(&marker.original);
            let mut candidates = evidence_ids
                .iter()
                .filter(|id| normalize(id) == normalized_marker);
            let resolution = match candidates.next() {
                None => Resolution::Dropped,
                Some(candidate) => {
                    if candidates.next().is_some() {
                        Resolution::Dropped
                    } else if *candidate == marker.original {
                        Resolution::Unchanged((*candidate).to_string())
                    } else {
                        Resolution::Repaired((*candidate).to_string())
                    }
                }
            };
            MarkerOutcome {
                original: marker.original.clone(),
                span: marker.span,
                resolution,
            }
        })
        .collect()
}

/// Extracts markers from `answer` and resolves each against `evidence_ids` in one call.
///
/// Convenience composition of [`extract_markers`] and [`resolve_markers`] for callers
/// that only have the answer text.
pub fn resolve_answer_markers(answer: &str, evidence_ids: &[&str]) -> Vec<MarkerOutcome> {
    resolve_markers(&extract_markers(answer), evidence_ids)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn marker(original: &str) -> ExtractedMarker {
        let len = original.len();
        ExtractedMarker {
            original: original.to_string(),
            span: MarkerSpan { start: 0, end: len },
        }
    }

    /// Behavior: a marker whose normalized form equals exactly one packed evidence
    /// identifier's normalized form resolves to that identifier (picked correctly among
    /// several candidates, not merely reported as some non-drop outcome).
    #[test]
    fn marker_resolves_to_sole_matching_identifier() {
        let outcomes = resolve_markers(&[marker("[5]")], &["[3]", "[5]", "[9]"]);
        assert_eq!(outcomes.len(), 1);
        match &outcomes[0].resolution {
            Resolution::Unchanged(id) | Resolution::Repaired(id) => assert_eq!(id, "[5]"),
            Resolution::Dropped => panic!("expected a resolution, got Dropped"),
        }
    }

    /// Behavior: a marker that already equalled an evidence identifier exactly, before
    /// normalization, resolves to it and is reported unchanged rather than repaired.
    #[test]
    fn already_exact_marker_reports_unchanged_not_repaired() {
        let outcomes = resolve_markers(&[marker("[7]")], &["[7]"]);
        assert_eq!(outcomes[0].resolution, Resolution::Unchanged("[7]".into()));
    }

    /// Behavior: a marker differing from exactly one identifier only by letter case
    /// resolves to it and is reported as repaired.
    #[test]
    fn case_only_difference_reports_repaired() {
        let outcomes = resolve_markers(&[marker("[abc]")], &["[ABC]"]);
        assert_eq!(outcomes[0].resolution, Resolution::Repaired("[ABC]".into()));
    }

    /// Behavior: a marker differing only by leading, trailing or internal whitespace
    /// resolves to it and is reported as repaired.
    #[test]
    fn whitespace_only_difference_reports_repaired() {
        let outcomes = resolve_markers(&[marker("[7]  ")], &["[7]"]);
        assert_eq!(outcomes[0].resolution, Resolution::Repaired("[7]".into()));
    }

    /// Behavior: a marker differing only by surrounding marker syntax resolves to it and
    /// is reported as repaired (the "index-vs-id confusion" case, e.g. parens instead of
    /// brackets).
    #[test]
    fn marker_syntax_only_difference_reports_repaired() {
        let outcomes = resolve_markers(&[marker("(7)")], &["[7]"]);
        assert_eq!(outcomes[0].resolution, Resolution::Repaired("[7]".into()));
    }

    /// Behavior: an answer containing `[ 7 ]` (ASCII spaces inside the brackets) yields
    /// one original span equal to that full substring — a match the digit-only extractor
    /// would miss — and that span resolves against evidence identifier `[7]`.
    #[test]
    fn widened_extraction_locates_internal_whitespace_span_and_repairs_it() {
        let answer = "Cite it here [ 7 ] please.";
        let markers = extract_markers(answer);
        assert_eq!(markers.len(), 1);
        assert_eq!(markers[0].original, "[ 7 ]");
        let outcomes = resolve_markers(&markers, &["[7]"]);
        assert_eq!(outcomes[0].original, "[ 7 ]");
        assert_eq!(outcomes[0].resolution, Resolution::Repaired("[7]".into()));
    }

    /// Behavior: a marker whose normalized form matches no identifier is reported dropped.
    #[test]
    fn unmatched_marker_reports_dropped() {
        let outcomes = resolve_markers(&[marker("[9999]")], &["[1]", "[2]"]);
        assert_eq!(outcomes[0].resolution, Resolution::Dropped);
    }

    /// Behavior: a marker whose normalized form matches two or more identifiers is
    /// dropped, not assigned to either candidate — the exact-tie case.
    #[test]
    fn tie_reports_dropped_not_assigned() {
        // "[7]" and "(7)" both normalize to "7": a deliberately contrived tie.
        let outcomes = resolve_markers(&[marker("[7]")], &["[7]", "(7)"]);
        assert_eq!(outcomes[0].resolution, Resolution::Dropped);
    }

    /// Behavior: resolution is order-independent — the same marker set against the same
    /// evidence set produces the same per-marker outcomes regardless of supply order —
    /// and the outcome list preserves the order markers were supplied in.
    #[test]
    fn resolution_is_order_independent_and_preserves_supplied_order() {
        let evidence = ["[1]", "[2]"];
        let forward = resolve_markers(&[marker("[1]"), marker("[2]")], &evidence);
        let backward = resolve_markers(&[marker("[2]"), marker("[1]")], &evidence);

        assert_eq!(forward[0].original, "[1]");
        assert_eq!(forward[1].original, "[2]");
        assert_eq!(backward[0].original, "[2]");
        assert_eq!(backward[1].original, "[1]");

        assert_eq!(forward[0].resolution, Resolution::Unchanged("[1]".into()));
        assert_eq!(forward[1].resolution, Resolution::Unchanged("[2]".into()));
        assert_eq!(backward[0].resolution, Resolution::Unchanged("[2]".into()));
        assert_eq!(backward[1].resolution, Resolution::Unchanged("[1]".into()));
    }

    /// Behavior: an empty marker set against any evidence set returns an empty outcome
    /// list.
    #[test]
    fn empty_markers_produce_empty_outcomes() {
        let outcomes = resolve_markers(&[], &["[1]"]);
        assert!(outcomes.is_empty());
    }

    /// Behavior: a non-empty marker set against an empty evidence set reports every
    /// marker dropped.
    #[test]
    fn non_empty_markers_against_empty_evidence_all_dropped() {
        let outcomes = resolve_markers(&[marker("[1]"), marker("[2]")], &[]);
        assert_eq!(outcomes.len(), 2);
        assert!(outcomes.iter().all(|o| o.resolution == Resolution::Dropped));
    }
}
