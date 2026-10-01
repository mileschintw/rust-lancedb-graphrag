//! Engine-rendered final `Answer:` line (D-95).
//!
//! The engine, not the model, writes the last line of the answer text. The strict
//! `model_output` schema carries a required `final_answer` field holding the shortest
//! answer (yes, no, an entity name or a short phrase). After grounding validation the
//! engine appends `Answer: <final_answer>` on its own line, so the line the committed
//! extractor reads no longer depends on a provider keeping the model's line breaks.
//!
//! [`render_final_answer_line`] runs only after validation: validation always sees the
//! model's own answer, and the rendered line is never validated.

/// Upper bound, in characters, of the `final_answer` field.
///
/// The D-71/D-95 short answer is at most about ten tokens (yes, no, an entity name or a
/// short phrase); 256 characters leaves room for long entity names. It is the `maxLength`
/// of the strict schema property and the renderer's field limit. It is never a validation
/// rule, so an over-long field cannot reject a generation. Lowering it shortens long
/// entity names in the rendered line; raising it also raises the schema bound the
/// provider enforces.
pub const MAX_FINAL_ANSWER_CHARS: usize = 256;

/// Appends `Answer: <final_answer>` as a new last line of `answer`.
///
/// Callers use this only after validation, so the rendered line never reaches grounding
/// or citation validation. When `final_answer` is `None` or trims to empty, the result is
/// `answer` byte-identical, so the committed extractor scores it exactly as before D-95.
/// Otherwise the result is `answer` with trailing whitespace trimmed, a line feed, then
/// `Answer: ` and the trimmed field.
pub fn render_final_answer_line(answer: &str, final_answer: Option<&str>) -> String {
    let Some(field) = final_answer.map(str::trim).filter(|field| !field.is_empty()) else {
        return answer.to_owned();
    };
    format!("{}\nAnswer: {field}", answer.trim_end())
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
        assert_eq!(rendered("Prose.", "ChatGPT [1][2]"), "Prose.\nAnswer: ChatGPT");
        assert_eq!(rendered("Prose.", "[ChatGPT]"), "Prose.\nAnswer: ChatGPT");
        // A field that is only a marker leaves nothing: no line, answer byte-identical.
        assert_eq!(rendered("Prose.  \n", "[1]"), "Prose.  \n");
    }

    #[test]
    fn d95_a_leading_answer_label_in_the_field_is_removed() {
        for field in ["Answer: Yes", "**Answer:** Yes", "answer: Yes", "**Answer**: Yes"] {
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
        assert_eq!(rendered("Prose.", "Yes\r\n\r\n  no"), "Prose.\nAnswer: Yes no");
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
