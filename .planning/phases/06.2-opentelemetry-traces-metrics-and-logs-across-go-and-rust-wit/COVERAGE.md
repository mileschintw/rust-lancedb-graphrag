# API Coverage — OpenTelemetry SDK / OTLP surface (Phase 06.2)

> Full coverage by default. Opt-outs are explicit, reasoned decisions.

**Detector note.** `node .claude/gsd-core/bin/lib/api-coverage.cjs --json` over the concatenated
`06.2-*-PLAN.md` bodies returns `detected: true` on a single weak signal — the noun `sdk` inside
one prose sentence in Plan 01's Task 1 (`"driving in-memory exporters rather than a live
Collector"` context). That is a prose false positive on its own. The matrix below is produced
anyway, and deliberately so: Phase 06.2 genuinely integrates the OpenTelemetry SDK and OTLP
protocol surface in two languages, and enumerating which OTel capabilities are built versus
skipped is exactly the hole this checkpoint exists to close. The `assumption-delta` detector,
run against this phase's ROADMAP section, returned `detected: false` and its checkpoint is
correctly skipped.

**Scope of this matrix.** The "external API" here is the OpenTelemetry signal and SDK surface
consumed by `engine/` (Rust, `opentelemetry` ~0.32) and `gateway/` (Go, `go.opentelemetry.io/otel`
v1.45.0), plus the OTLP wire protocol to the Collector. Backend services on the `observability`
profile (Jaeger, Prometheus, Loki, Grafana) are consumed as OTLP/scrape endpoints and as
file-provisioned configuration, not as programmatic APIs, so they carry rows only where this
phase writes against a real interface.

| capability | decision | reason |
|---|---|---|
| traces — SDK tracer provider, span creation, nesting | INTEGRATE | |
| traces — W3C `traceparent` propagation (extract + inject, both runtimes) | INTEGRATE | |
| traces — baggage propagation | INTEGRATE | Registered as part of the composite propagator; no baggage keys are set by this phase |
| traces — span links (many-to-one causality) | INTEGRATE | Used for the coalesced `index_rebuild` span (Plan 04) |
| traces — span status (Ok / Error) | INTEGRATE | |
| traces — span events | OPT-OUT | not needed — the existing `WorkflowEvent` SSE stream is already the per-step event record; duplicating it as span events would double the wire surface with no new consumer |
| traces — sampling (`sampler_ratio`, always-on default per D-32) | INTEGRATE | |
| metrics — counters | INTEGRATE | |
| metrics — histograms | INTEGRATE | |
| metrics — synchronous gauges | INTEGRATE | `lancet.index.corpus_generation` |
| metrics — asynchronous / observable instruments | OPT-OUT | explicitly out of scope — `telemetry::init` runs before the corpus store exists, so a callback would need a later re-bind and would hold the corpus read lock on a scrape thread (Plan 05) |
| metrics — up/down counters | OPT-OUT | not needed — no monotonically-decreasing quantity appears in the D-35 set |
| metrics — exemplars (metric→trace linking) | OPT-OUT | not needed yet — correlation for v1 is trace↔log through Grafana; exemplars would require Prometheus native-histogram configuration that D-40's no-rules local demo does not justify |
| metrics — views / custom aggregation and bucket boundaries | OPT-OUT | not needed yet — SDK default bucket boundaries are adequate for a local demo; tuning them has no on-call consumer |
| logs — logger provider + batch processor | INTEGRATE | |
| logs — `tracing` → OTel bridge (Rust, `opentelemetry-appender-tracing`) | INTEGRATE | |
| logs — zap → OTel bridge (Go, `otelzap` core teed onto the console core) | INTEGRATE | |
| logs — log-to-trace context attachment | INTEGRATE | The whole point of Plan 06; background logs deliberately carry none |
| profiles signal | OPT-OUT | explicitly out of scope — the profiles signal is not stable in either pinned SDK and OBS-01 names traces, metrics and logs only |
| resource — `service.name`, `service.version`, `deployment.environment` (D-43) | INTEGRATE | |
| resource — environment/OS/process/container auto-detectors | OPT-OUT | not needed — explicit resource attributes are the D-43 contract; auto-detected host and process attributes add cardinality with no local-demo consumer |
| OTLP exporter — gRPC transport | INTEGRATE | Both runtimes export over gRPC to `127.0.0.1:4317` |
| OTLP exporter — HTTP/protobuf transport | OPT-OUT | not needed for the services — the Collector still RECEIVES on `4318` so an external producer can use it, but neither Lancet service is built against the HTTP exporter |
| OTLP exporter — TLS / client authentication | INTEGRATE | client OTLP gRPC export honors https vs http on the already-validated otlp_endpoint (CR-04, D-84); D-06 documented-only ingress TLS is unchanged |
| OTLP exporter — retry / queue tuning | OPT-OUT | not needed — SDK batch-processor defaults suffice; D-38 requires export failure to be non-fatal and rate-bounded, which is handled by the SDK error handler rather than by retry configuration |
| Collector — OTLP receiver, batch processor, three signal pipelines | INTEGRATE | |
| Collector — sampling / filtering / transform processors | OPT-OUT | not needed — always-on sampling (D-32) and a bounded attribute set mean there is nothing to filter or scrub at the Collector |
| Grafana — file-provisioned datasources, dashboards, trace-to-log correlation | INTEGRATE | |
| Grafana — Loki derivedFields `matcherType: label` for OTLP structured metadata `trace_id` | INTEGRATE | Plan 10 (reviews): engine OTLP logs do not embed `trace_id=` in the body; Grafana ≥10.1 label matcher is the return path to Jaeger |
| Grafana / Prometheus — alert rules, recording rules, notification policies | OPT-OUT | explicitly out of scope — D-40 forbids them: there is no on-call and nowhere to route them |
