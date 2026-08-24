//! OpenTelemetry metrics instrumentation and recording helpers.
//!
//! Provides the global meter accessor and domain-specific metric recording functions
//! using bounded dimensions only (D-35, D-42).

use opentelemetry::KeyValue;

/// Outcome constant for successfully completed queries.
pub const OUTCOME_COMPLETED: &str = "completed";

/// Outcome constant for failed queries.
pub const OUTCOME_FAILED: &str = "failed";

/// Returns a [`Meter`] bound to the engine's instrumentation scope.
pub fn meter() -> opentelemetry::metrics::Meter {
    opentelemetry::global::meter("lancet-engine")
}

/// Records the total query duration in milliseconds with the bounded `outcome` attribute.
pub fn record_query_duration_ms(outcome: &'static str, millis: u64) {
    let histogram = meter()
        .u64_histogram("lancet.rag.query.duration")
        .with_unit("ms")
        .with_description("RAG query duration in milliseconds")
        .build();
    histogram.record(millis, &[KeyValue::new("outcome", outcome)]);
}
