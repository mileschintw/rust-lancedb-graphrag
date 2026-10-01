//! Engine-rendered final `Answer:` line (D-95).
//!
//! The engine, not the model, writes the last line of the answer text. The strict
//! `model_output` schema carries a required `final_answer` field holding the shortest
//! answer (yes, no, an entity name or a short phrase). After grounding validation the
//! engine appends `Answer: <final_answer>` on its own line, so the line the committed
//! extractor reads no longer depends on a provider keeping the model's line breaks.
//!
//! [`render_final_answer_line`] runs only after validation: validation always sees the
//! model's own answer, and the rendered line is never validated. The rendered line adds no
//! citation marker, so it cannot raise the citation rejection rate.
//!
//! When a line renders, a model-written `Answer:` segment on the prose's last line (at the
//! line start or inline) is stripped first, so the visible text carries one final Answer
//! line. The strip is narrow: the segment must start the line or follow whitespace, must
//! contain no square bracket (removing a bracketed segment could drop a marker that the
//! citation set counts), and must leave some prose behind. Otherwise the segment is kept,
//! and the rendered line is still the last line-start `Answer:` match.

use crate::generation::MAX_ANSWER_CHARS;

/// Upper bound, in characters, of the `final_answer` field.
///
/// The D-71/D-95 short answer is at most about ten tokens (yes, no, an entity name or a
/// short phrase); 256 characters leaves room for long entity names. It is the `maxLength`
/// of the strict schema property and the renderer's field limit. It is never a validation
/// rule, so an over-long field cannot reject a generation. Lowering it shortens long
/// entity names in the rendered line; raising it also raises the schema bound the
/// provider enforces.
pub const MAX_FINAL_ANSWER_CHARS: usize = 256;

/// The text between the prose and the field: a line feed, so the line starts a line, then
/// the label `Answer: ` that the committed extractor's line-start rule reads.
///
/// It is 9 characters, counted into the `MAX_ANSWER_CHARS` fit check. The extractor in
/// `eval/src/lancet_eval/metrics.py` matches this label case-insensitively at a line start,
/// so changing it would change what the SC-3 metric can read.
const RENDERED_LINE_PREFIX: &str = "\nAnswer: ";

/// The label a model writes on its own `Answer:` line (D-71), matched case-sensitively
/// because the D-71 policy prescribes exactly this literal.
const MODEL_ANSWER_LABEL: &str = "Answer:";

/// The label word without its colon, matched case-insensitively when removing a label
/// from the `final_answer` field.
const ANSWER_LABEL_WORD: &str = "answer";

/// Appends `Answer: <final_answer>` as a new last line of `answer`.
///
/// Callers use this only after validation, so the rendered line never reaches grounding
/// or citation validation. The rules, each with its reason:
///
/// - The field is sanitised first: `[n]` markers and every square bracket are removed, so
///   the line adds no citation marker and D-69's rate cannot move; control characters and
///   whitespace runs collapse, so the line stays one line; a leading `Answer:` label is
///   removed, so the label is not doubled; the field is cut to
///   [`MAX_FINAL_ANSWER_CHARS`] characters.
/// - A model-written trailing `Answer:` segment is stripped, under the narrow conditions in
///   the module docs, so the visible text carries one final Answer line.
/// - A field that does not fit whole within `MAX_ANSWER_CHARS` renders no line, so a partial
///   short answer is never scored.
/// - A `None` field, or one that sanitises to empty, leaves `answer` byte-identical, so the
///   committed extractor scores it exactly as before D-95.
pub fn render_final_answer_line(answer: &str, final_answer: Option<&str>) -> String {
    let Some(field) = final_answer.and_then(sanitize_final_answer) else {
        return answer.to_owned();
    };
    let prose = strip_trailing_model_answer(answer);
    let rendered_chars =
        prose.chars().count() + RENDERED_LINE_PREFIX.chars().count() + field.chars().count();
    if rendered_chars > MAX_ANSWER_CHARS {
        return answer.to_owned();
    }
    format!("{prose}{RENDERED_LINE_PREFIX}{field}")
}

/// Reduces a raw `final_answer` to one bracket-free line, or `None` when nothing is left.
fn sanitize_final_answer(raw: &str) -> Option<String> {
    let without_markers = remove_numeric_markers(raw);
    let without_brackets: String = without_markers
        .chars()
        .filter(|c| !matches!(c, '[' | ']'))
        .collect();
    let spaced: String = without_brackets
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    let collapsed = spaced.split_whitespace().collect::<Vec<_>>().join(" ");
    let unlabeled = strip_leading_answer_label(&collapsed);
    let truncated: String = unlabeled.chars().take(MAX_FINAL_ANSWER_CHARS).collect();
    let sanitised = truncated.trim_end();
    (!sanitised.is_empty()).then(|| sanitised.to_owned())
}

/// Removes every `[<digits>]` marker, the shape grounding validation reads.
fn remove_numeric_markers(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut copied = 0;
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'[' {
            let mut j = i + 1;
            while j < bytes.len() && bytes[j].is_ascii_digit() {
                j += 1;
            }
            if j > i + 1 && j < bytes.len() && bytes[j] == b']' {
                out.push_str(&text[copied..i]);
                copied = j + 1;
                i = j + 1;
                continue;
            }
        }
        i += 1;
    }
    out.push_str(&text[copied..]);
    out
}

/// Removes one leading answer label, optionally wrapped in `*` or `_` emphasis.
fn strip_leading_answer_label(text: &str) -> &str {
    let is_emphasis = |c: char| c == '*' || c == '_';
    let rest = text.trim_start_matches(is_emphasis);
    let Some(head) = rest.get(..ANSWER_LABEL_WORD.len()) else {
        return text;
    };
    if !head.eq_ignore_ascii_case(ANSWER_LABEL_WORD) {
        return text;
    }
    let after_word =
        rest[ANSWER_LABEL_WORD.len()..].trim_start_matches(|c| is_emphasis(c) || c == ' ');
    match after_word.strip_prefix(':') {
        Some(after_colon) => after_colon.trim_start_matches(is_emphasis).trim(),
        None => text,
    }
}

/// Returns the prose without the model's own trailing `Answer:` segment, when the strip's
/// narrow conditions hold, and otherwise the answer with trailing whitespace trimmed.
fn strip_trailing_model_answer(answer: &str) -> &str {
    let trimmed = answer.trim_end();
    let line_start = trimmed.rfind('\n').map_or(0, |idx| idx + 1);
    let last_line = &trimmed[line_start..];
    let Some(label_at) = last_line.rfind(MODEL_ANSWER_LABEL) else {
        return trimmed;
    };
    // Extend the segment backwards over `*` and `_` emphasis; both are ASCII, so the byte
    // walk stays on char boundaries.
    let mut segment_start = label_at;
    while segment_start > 0 && matches!(last_line.as_bytes()[segment_start - 1], b'*' | b'_') {
        segment_start -= 1;
    }
    let before = &last_line[..segment_start];
    let begins_line = before.chars().all(|c| matches!(c, ' ' | '\t' | '>' | '-'));
    let follows_whitespace = before.chars().next_back().is_some_and(char::is_whitespace);
    if !(begins_line || follows_whitespace) {
        return trimmed;
    }
    if last_line[segment_start..].contains(['[', ']']) {
        return trimmed;
    }
    let remaining = trimmed[..line_start + segment_start].trim_end();
    if remaining.is_empty() {
        trimmed
    } else {
        remaining
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::generation::MAX_ANSWER_CHARS;

    fn rendered(answer: &str, field: &str) -> String {
        render_final_answer_line(answer, Some(field))
    }

    #[test]
    fn d95_markers_and_brackets_are_stripped_from_the_field() {
        assert_eq!(
            rendered("Prose.", "ChatGPT [1][2]"),
            "Prose.\nAnswer: ChatGPT"
        );
        assert_eq!(rendered("Prose.", "[ChatGPT]"), "Prose.\nAnswer: ChatGPT");
        // A field that is only a marker leaves nothing: no line, answer byte-identical.
        assert_eq!(rendered("Prose.  \n", "[1]"), "Prose.  \n");
    }

    #[test]
    fn d95_a_leading_answer_label_in_the_field_is_removed() {
        for field in [
            "Answer: Yes",
            "**Answer:** Yes",
            "answer: Yes",
            "**Answer**: Yes",
        ] {
            assert_eq!(
                rendered("Prose.", field),
                "Prose.\nAnswer: Yes",
                "field {field:?} renders exactly one Answer label"
            );
        }
    }

    #[test]
    fn d95_line_breaks_and_runs_of_whitespace_in_the_field_collapse() {
        assert_eq!(
            rendered("Prose.", "Yes,\n it\tdoes"),
            "Prose.\nAnswer: Yes, it does"
        );
        assert_eq!(
            rendered("Prose.", "Yes\r\n\r\n  no"),
            "Prose.\nAnswer: Yes no"
        );
    }

    #[test]
    fn d95_field_is_truncated_to_max_final_answer_chars_on_a_char_boundary() {
        for field in ["x".repeat(1000), "é".repeat(300)] {
            let out = rendered("Prose.", &field);
            let line = out
                .strip_prefix("Prose.\nAnswer: ")
                .expect("a truncated field still renders");
            assert_eq!(line.chars().count(), MAX_FINAL_ANSWER_CHARS);
        }
    }

    #[test]
    fn d95_a_field_that_does_not_fit_whole_renders_no_line() {
        // The line-feed-plus-`Answer: ` prefix is 9 chars and `ChatGPT` is 7.
        let fits = "x".repeat(MAX_ANSWER_CHARS - 16);
        let out = rendered(&fits, "ChatGPT");
        assert_eq!(out.chars().count(), MAX_ANSWER_CHARS);
        assert!(out.ends_with("\nAnswer: ChatGPT"));

        let too_long = "x".repeat(MAX_ANSWER_CHARS - 15);
        assert_eq!(rendered(&too_long, "ChatGPT"), too_long);

        for len in (MAX_ANSWER_CHARS - 40)..=MAX_ANSWER_CHARS {
            let prose = "x".repeat(len);
            assert!(
                rendered(&prose, "ChatGPT").chars().count() <= MAX_ANSWER_CHARS,
                "a prose of {len} chars must never render past the bound"
            );
        }
    }

    #[test]
    fn d95_trailing_model_answer_segment_is_stripped_when_a_line_renders() {
        assert_eq!(
            rendered("Prose [1].\nAnswer: Yes", "Yes"),
            "Prose [1].\nAnswer: Yes"
        );
        assert_eq!(
            rendered("Prose [1]. Answer: ChatGPT", "ChatGPT"),
            "Prose [1].\nAnswer: ChatGPT"
        );
        assert_eq!(
            rendered("Prose [1].\n**Answer:** Yes", "Yes"),
            "Prose [1].\nAnswer: Yes"
        );
    }

    #[test]
    fn d95_a_bracketed_or_non_final_model_answer_is_kept() {
        assert_eq!(
            rendered("Prose. Answer: ChatGPT [1]", "ChatGPT"),
            "Prose. Answer: ChatGPT [1]\nAnswer: ChatGPT"
        );
        assert_eq!(
            rendered("Answer: Yes\nMore prose [1].", "Yes"),
            "Answer: Yes\nMore prose [1].\nAnswer: Yes"
        );
        // Stripping would leave no prose at all.
        assert_eq!(rendered("Answer: Yes", "Yes"), "Answer: Yes\nAnswer: Yes");
        // With an empty field nothing is rendered and nothing is stripped.
        assert_eq!(
            render_final_answer_line("Prose. Answer: X", Some("")),
            "Prose. Answer: X"
        );
        assert_eq!(
            render_final_answer_line("Prose. Answer: X", None),
            "Prose. Answer: X"
        );
    }

    #[test]
    fn d95_the_rendered_line_is_the_last_line_start_answer_line() {
        let cases = [
            ("Prose [1].", "ChatGPT", "ChatGPT"),
            ("Prose [1].\nAnswer: Yes", "Yes", "Yes"),
            ("Prose [1]. Answer: ChatGPT", "ChatGPT", "ChatGPT"),
            ("Prose [1].\n**Answer:** Yes", "Yes", "Yes"),
            ("Prose. Answer: ChatGPT [1]", "ChatGPT", "ChatGPT"),
            ("Answer: Yes\nMore prose [1].", "Yes", "Yes"),
            ("Answer: Yes", "Yes", "Yes"),
            ("Prose.", "**Answer:** Y [3]", "Y"),
        ];
        for (answer, field, expected) in cases {
            let out = rendered(answer, field);
            assert_eq!(
                out.lines().last(),
                Some(format!("Answer: {expected}").as_str()),
                "answer {answer:?} with field {field:?} renders {out:?}"
            );
        }
    }
}
