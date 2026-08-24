//! OpenTelemetry W3C propagation extractor for gRPC metadata.
//!
//! Provides an extractor adapter over `tonic::metadata::MetadataMap` so incoming
//! W3C `traceparent` and `tracestate` headers are extracted into an `opentelemetry::Context`
//! without hand-rolled parsing.

use tonic::metadata::MetadataMap;

/// Extractor adapter over tonic's [`MetadataMap`].
pub struct MetadataExtractor<'a>(pub &'a MetadataMap);

impl<'a> opentelemetry::propagation::Extractor for MetadataExtractor<'a> {
    fn get(&self, key: &str) -> Option<&str> {
        self.0.get(key).and_then(|v| v.to_str().ok())
    }

    fn keys(&self) -> Vec<&str> {
        self.0
            .keys()
            .map(|k| match k {
                tonic::metadata::KeyRef::Ascii(a) => a.as_str(),
                tonic::metadata::KeyRef::Binary(b) => b.as_str(),
            })
            .collect()
    }
}

/// Extract parent trace context from incoming tonic gRPC metadata map.
///
/// Uses the globally registered text map propagator. If metadata contains no valid
/// trace context, returns an empty context (which becomes a local root when parented).
pub fn extract_parent_context(metadata: &MetadataMap) -> opentelemetry::Context {
    let extractor = MetadataExtractor(metadata);
    opentelemetry::global::get_text_map_propagator(|propagator| propagator.extract(&extractor))
}

/// Injects the given OpenTelemetry context into a W3C `traceparent` string.
pub fn inject_trace_parent(cx: &opentelemetry::Context) -> Option<String> {
    let mut carrier = std::collections::HashMap::new();
    opentelemetry::global::get_text_map_propagator(|propagator| {
        propagator.inject_context(cx, &mut carrier);
    });
    carrier.remove("traceparent")
}

/// Extracts an OpenTelemetry context from a W3C `traceparent` string.
pub fn extract_context_from_trace_parent(trace_parent: &str) -> opentelemetry::Context {
    let mut carrier = std::collections::HashMap::new();
    carrier.insert("traceparent".to_string(), trace_parent.to_string());
    opentelemetry::global::get_text_map_propagator(|propagator| propagator.extract(&carrier))
}
