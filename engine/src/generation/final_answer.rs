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
