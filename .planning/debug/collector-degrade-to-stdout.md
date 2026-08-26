---
status: diagnosed
trigger: "Investigate issue G-06.2-4: Stopping Collector produces unbounded OTLP exporter-error stream instead of bounding/silencing exporter errors when degrading to stdout."
created: 2026-08-26T12:12:00.000Z
updated: 2026-08-26T12:12:00.000Z
---

## Current Focus

hypothesis: "Neither the Go gateway (`telemetry.go`) nor the Rust engine (`telemetry/mod.rs`) configures an OpenTelemetry SDK global error handler (via `otel.SetErrorHandler` in Go and `opentelemetry::global::set_error_handler` in Rust). When the OTLP Collector is down or stopped mid-run, background PeriodicReaders (5s interval) and BatchProcessors (logs and traces) continuously attempt exports and fail. Without custom error handlers to rate-limit or silence export failures, the SDKs fall back to their default error handlers which print `eprintln!` and `log.Printf` error lines directly to stderr on every background tick and batch flush indefinitely."
test: "Inspect error handling, background exporter routines, and default error handlers in Go OTel SDK and Rust OTel SDK in `gateway/internal/telemetry/telemetry.go` and `engine/src/telemetry/mod.rs`."
expecting: "Zero calls to `otel.SetErrorHandler` or `opentelemetry::global::set_error_handler` exist in either codebase, leaving background exporter failures unhandled and writing unbounded error logs to stderr."
next_action: "Document root cause, evidence, and suggested fix direction."

## Symptoms

expected: "Stop the collector container, issue a query, confirm both services keep logging to stdout/console, the request still completes, and no unbounded export-error stream appears. (VALIDATION.md Manual-Only item d, OBS-01/D-38 — also the runtime half of roadmap SC7.)"
actual: "Stopping the Collector did not crash the services, and the gateway opened the RAG query stream, but the required bounded degrade-to-stdout behavior was not met. The engine emitted repeated `BatchLogProcessor.ExportError` and metrics export connection-refused failures at roughly 3-second intervals. The gateway repeatedly emitted `failed to upload metrics: exporter export timeout` at roughly 10-second intervals, plus a trace export failure. Both services therefore produced an unbounded OTLP exporter-error stream while the Collector was unavailable, rather than degrading silently to normal stdout/console logging with at most a bounded warning."
errors: "Engine emitted repeated BatchLogProcessor.ExportError and metrics export connection-refused; Gateway emitted repeated failed to upload metrics: exporter export timeout and trace export failures."
reproduction: "Test 4 in 06.2-UAT.md"
started: "Phase 06.2 UAT / Test 4"

## Evidence

- timestamp: 2026-08-26T12:12:00.000Z
  checked: "gateway/internal/telemetry/telemetry.go:90-226"
  found: |
    - `telemetry.Init()` registers the trace/metric/log providers, but never calls `otel.SetErrorHandler()`.
    - Go's OpenTelemetry SDK uses `defaultErrorHandler`, which calls `log.Printf("otel: %s: %v", ...)` (writing to `os.Stderr`) for every error passed to `otel.Handle(err)`.
    - `sdkmetric.NewPeriodicReader(metricExp, sdkmetric.WithInterval(5*time.Second))` and `sdktrace.WithBatcher(spanExporter)` / `sdklog.NewBatchProcessor(logExp)` run continuously in background goroutines.
    - When the Collector is stopped, every 5s periodic metric tick times out (~10s) and calls `otel.Handle(err)`, resulting in `failed to upload metrics: exporter export timeout` repeatedly written to stderr. Span and log flushes also trigger `otel.Handle(err)`.
  implication: "Go gateway has no error handler installed to suppress or rate-limit background OTLP export failures."

- timestamp: 2026-08-26T12:12:00.000Z
  checked: "engine/src/telemetry/mod.rs:77-190"
  found: |
    - `build_providers_and_layers()` configures `SdkTracerProvider`, `SdkMeterProvider` (with `PeriodicReader` 5s), and `SdkLoggerProvider` (with `BatchLogProcessor`), but never calls `opentelemetry::global::set_error_handler()`.
    - In the Rust OpenTelemetry SDK (`opentelemetry` ~0.32), `handle_error` defaults to `eprintln!("OpenTelemetry error occurred. {}", err)`.
    - Tonic gRPC channel creation is lazy and non-blocking, so builder calls succeed at startup. During runtime, `PeriodicReader` (5s interval) and `BatchLogProcessor` background workers attempt export, receive `Tonic error: transport error` / `Connection refused`, and invoke `opentelemetry::global::handle_error()`.
    - Without a custom error handler, `eprintln!` writes `BatchLogProcessor.ExportError` and metric export connection-refused messages to stderr on every background tick and log flush indefinitely.
  implication: "Rust engine has no global error handler installed to suppress or rate-limit background OTLP export failures."

- timestamp: 2026-08-26T12:12:00.000Z
  checked: "gateway/internal/telemetry/telemetry_test.go:227-263 (`TestCollectorUnavailable`)"
  found: |
    - Existing test `TestCollectorUnavailable` only asserts that `Init()` does not return nil when endpoint is down and that a zap log reaches the observer core.
    - It does not test asynchronous exporter retry cycles or verify that background export failures do not spam stderr.
  implication: "Unit tests validated non-crashing initialization and stdout logging, but did not test background error handler bounding or suppression."

## Resolution

root_cause: "Neither the Go gateway (`gateway/internal/telemetry/telemetry.go`) nor the Rust engine (`engine/src/telemetry/mod.rs`) installs a custom OpenTelemetry error handler (via `otel.SetErrorHandler` in Go and `opentelemetry::global::set_error_handler` in Rust). When the OTLP Collector is unavailable or stopped mid-run, background threads/goroutines (`PeriodicReader` on 5s intervals, `BatchSpanProcessor`, and `BatchLogProcessor`) repeatedly attempt export and fail. Because both OpenTelemetry SDKs default to unconditionally printing every error to stderr (`log.Printf` in Go, `eprintln!` in Rust), an unbounded stream of exporter errors (`BatchLogProcessor.ExportError`, `connection-refused`, `exporter export timeout`) is emitted indefinitely instead of being silenced or bounded as required by D-38 and SC7."

fix: |
  1. In `gateway/internal/telemetry/telemetry.go`:
     - Register a custom `otel.ErrorHandler` using `otel.SetErrorHandler(...)` during telemetry initialization / propagator setup.
     - The error handler should bound/silence repetitive OTLP exporter background errors (e.g. logging at most once / rate-limiting or ignoring transient export errors so console logging remains clean during degrade-to-stdout).
  2. In `engine/src/telemetry/mod.rs`:
     - Register a custom global error handler using `opentelemetry::global::set_error_handler(...)` in `ensure_propagators()` or `build_providers_and_layers()`.
     - The error handler should suppress or rate-limit repeated background `ExportError` / transport connection failures so stderr is not spammed.
  3. Add regression tests in both `gateway/internal/telemetry/telemetry_test.go` and Rust telemetry tests verifying that exporter failures do not produce unbounded error logging to stderr.

verification: "Run unit tests in Go and Rust, then verify UAT Test 4 by stopping the Collector container, issuing a query, and confirming stdout logging continues without continuous exporter error logs on stderr."
files_changed:
  - "gateway/internal/telemetry/telemetry.go"
  - "engine/src/telemetry/mod.rs"
  - "gateway/internal/telemetry/telemetry_test.go"
  - "engine/src/tests/telemetry_metrics.rs" (or new/updated telemetry test file)
