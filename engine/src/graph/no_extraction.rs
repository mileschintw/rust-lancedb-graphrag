//! The extraction generator of a store built without a graph (#149).
//!
//! Kept out of `extraction.rs`, whose git blob S3's writer pre-registration pins (#145).

use super::extraction::{ExtractionGenerator, ExtractionOutput, ExtractionRequest};
use crate::generation::{BoxFuture, GenerationError};

/// Used when `[engine.graph] ingest_extraction = false`: every chunk yields no entity and
/// no relation, and no provider is called.
pub struct NoExtractionGenerator;

impl ExtractionGenerator for NoExtractionGenerator {
    fn extract<'a>(
        &'a self,
        _request: ExtractionRequest,
    ) -> BoxFuture<'a, Result<ExtractionOutput, GenerationError>> {
        Box::pin(async {
            Ok(ExtractionOutput {
                entities: Vec::new(),
                relations: Vec::new(),
            })
        })
    }
}
