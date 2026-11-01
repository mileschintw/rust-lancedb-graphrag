//! Extraction answers recorded elsewhere, served in place of live extraction (#148).
//!
//! Kept out of `extraction.rs`, whose git blob S3's writer pre-registration pins (#145).

use std::collections::HashMap;

use super::extraction::{
    validate_extraction_output, ExtractionGenerator, ExtractionOutput, ExtractionRequest,
};
use crate::generation::{BoxFuture, GenerationError, GenerationErrorKind};

/// Extraction answers recorded elsewhere (another writer's, #148), served by chunk text.
///
/// Each answer is parsed and validated as the OpenRouter adapter parses a live one, so an
/// answer the engine would refuse is refused here too. A chunk with no recorded answer fails
/// as a live extraction failure does, and the ingest path drops it.
#[derive(Debug, Default)]
pub struct RecordedExtractions {
    answers: HashMap<String, String>,
}

impl RecordedExtractions {
    /// Builds the set from `(chunk text, answer content)` pairs. A repeated chunk text keeps its
    /// first answer: its request was the same.
    pub fn new(pairs: impl IntoIterator<Item = (String, String)>) -> Self {
        let mut answers = HashMap::new();
        for (text, content) in pairs {
            answers.entry(text).or_insert(content);
        }
        Self { answers }
    }

    /// How many distinct chunk texts have an answer.
    pub fn len(&self) -> usize {
        self.answers.len()
    }

    /// Whether no chunk text has an answer.
    pub fn is_empty(&self) -> bool {
        self.answers.is_empty()
    }

    /// Whether `chunk_text` has a recorded answer.
    pub fn contains(&self, chunk_text: &str) -> bool {
        self.answers.contains_key(chunk_text)
    }

    /// The recorded answer for `chunk_text`, parsed and validated.
    ///
    /// # Errors
    /// `SchemaValidation` if no answer is recorded, or the answer is not an `ExtractionOutput`
    /// the engine accepts.
    pub fn answer(&self, chunk_text: &str) -> Result<ExtractionOutput, GenerationError> {
        let content = self.answers.get(chunk_text).ok_or_else(|| {
            GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                "no recorded extraction for this chunk",
            )
        })?;
        let output: ExtractionOutput = serde_json::from_str(content).map_err(|err| {
            GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!("recorded extraction is not valid: {err}"),
            )
        })?;
        validate_extraction_output(&output)
            .map_err(|reason| GenerationError::new(GenerationErrorKind::SchemaValidation, reason))?;
        Ok(output)
    }
}

impl ExtractionGenerator for RecordedExtractions {
    fn extract<'a>(
        &'a self,
        request: ExtractionRequest,
    ) -> BoxFuture<'a, Result<ExtractionOutput, GenerationError>> {
        Box::pin(async move { self.answer(&request.chunk_text) })
    }
}
