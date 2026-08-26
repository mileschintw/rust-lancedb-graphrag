---
status: diagnosed
trigger: "Investigate issue G-06.2-1: Grafana trace<->log<->metric correlation click-through: Grafana does not render the Logs for this span trace-to-logs action."
created: 2026-08-26T12:10:00.000Z
updated: 2026-08-26T12:10:00.000Z
---

## Current Focus

hypothesis: "deploy/grafana/provisioning/datasources/datasources.yaml configures tracesToLogsV2.tags with key: trace_id, value: trace_id. Because trace ID is intrinsic OpenTelemetry span context rather than a span/resource tag/attribute, Grafana cannot resolve the required tag and suppresses the 'Logs for this span' action in the UI. Retaining filterByTraceID: true without the unresolved tags mapping resolves the issue."
test: "Inspect deploy/grafana/provisioning/datasources/datasources.yaml and cross-reference Grafana tracesToLogsV2 configuration specifications."
expecting: "Grafana tracesToLogsV2 requires tags only for span attributes (e.g. service.name); intrinsic trace ID filtering is handled exclusively by filterByTraceID: true. Supplying an unresolvable span tag trace_id causes Grafana to hide the trace-to-logs action."
next_action: "Report root cause and suggest fix direction for plan-phase --gaps."

## Symptoms

expected: "Open Grafana, run one query, follow the Jaeger trace's trace-to-logs link into Loki, then follow a Loki log line's derived TraceID field back to Jaeger; the same trace_id appears in all three panes, and a non-empty Prometheus series exists over the same window."
actual: "Jaeger traces exist and display gateway/engine spans, but Grafana does not render the Logs for this span trace-to-logs action."
errors: "Grafana suppresses the trace-to-logs action because configured tag variable trace_id is unresolved."
reproduction: "Test 1 in UAT (Phase 06.2)"
started: "Discovered during Phase 06.2 UAT"

## Evidence

- timestamp: 2026-08-26T12:10:00.000Z
  checked: "deploy/grafana/provisioning/datasources/datasources.yaml:18-26"
  found: |
    jsonData:
      tracesToLogsV2:
        datasourceUid: loki-datasource
        tags:
          - key: trace_id
            value: trace_id
        filterByTraceID: true
        filterBySpanID: false
  implication: "The Jaeger datasource explicitly configures a required tag mapping for `trace_id`."

- timestamp: 2026-08-26T12:10:00.000Z
  checked: "OpenTelemetry span structure and Grafana tracesToLogsV2 mechanics"
  found: "Trace ID is intrinsic span context (SpanContext.trace_id) emitted in trace headers/payloads, not a span tag/attribute (like `service.name` or custom span attributes). Grafana's `tags` configuration defines required span tag mappings; when configured tags are missing on a span, Grafana suppresses the 'Logs for this span' action button because tag variables cannot be interpolated."
  implication: "`filterByTraceID: true` is the built-in mechanism to query Loki by trace ID without requiring any entry in `tags`. Configuring `key: trace_id` in `tags` guarantees resolution failure on standard OpenTelemetry spans."

## Resolution

root_cause: "In deploy/grafana/provisioning/datasources/datasources.yaml (lines 21-23), `tracesToLogsV2` defines a tag mapping with `key: trace_id` and `value: trace_id`. In OpenTelemetry / Jaeger spans, trace ID is intrinsic span context rather than a span/resource tag or attribute. Grafana evaluates configured `tags` against span attributes; because no span attribute named `trace_id` exists, Grafana considers the tag variable unresolved and suppresses the 'Logs for this span' trace-to-logs link in the trace viewer."
fix: "Remove the `tags` list (or configure it with valid span/resource attributes like `service.name` if desired, or omit `tags` entirely) from `tracesToLogsV2` in `deploy/grafana/provisioning/datasources/datasources.yaml` while retaining `filterByTraceID: true`. Reprovision Grafana datasource configuration so the 'Logs for this span' action renders and filters Loki logs by trace ID."
verification: "Reprovision Grafana container with the updated datasource config, generate a trace/query, and verify that clicking a span in Jaeger displays 'Logs for this span' linking directly to the corresponding Loki log stream."
files_changed:
  - "deploy/grafana/provisioning/datasources/datasources.yaml"
