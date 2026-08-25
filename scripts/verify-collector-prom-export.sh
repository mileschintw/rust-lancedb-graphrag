#!/bin/sh
# scripts/verify-collector-prom-export.sh
#
# Asserts end-to-end Collector Prometheus exposition matches every operations-dashboard
# PromQL metric stem, including histogram unit suffixes (D-34, D-35, D-40).
#
# Requirements:
# 1. Enforce a single wall-clock budget of 30 seconds for connect plus poll (Nyquist 8b).
# 2. Parse metric stems directly from deploy/grafana/dashboards/lancet-rag-operations.json expr fields.
# 3. Push synthetic OTLP HTTP metrics for all ten D-35 instruments to http://127.0.0.1:4318/v1/metrics.
# 4. Scrape http://127.0.0.1:8889/metrics and verify all stems are present without doubled prefixes.
# 5. Output observed exported lines for duration histograms.

set -e

DASHBOARD_JSON="deploy/grafana/dashboards/lancet-rag-operations.json"
OTLP_ENDPOINT="http://127.0.0.1:4318/v1/metrics"
PROM_ENDPOINT="http://127.0.0.1:8889/metrics"
MAX_TIME_SECONDS=30

if [ ! -f "$DASHBOARD_JSON" ]; then
  echo "ERROR: Dashboard JSON not found at $DASHBOARD_JSON" >&2
  exit 1
fi

# Ensure curl is available
if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl is required to run verification" >&2
  exit 1
fi

START_TIME=$(date +%s)
DEADLINE=$(( START_TIME + MAX_TIME_SECONDS ))

# (1) Verify reachability of Prometheus exposition endpoint within budget
echo "Checking Prometheus endpoint reachability at $PROM_ENDPOINT..."
REACHABLE=0
while [ "$(date +%s)" -le "$DEADLINE" ]; do
  if curl -s --connect-timeout 2 --max-time 5 "$PROM_ENDPOINT" >/dev/null 2>&1; then
    REACHABLE=1
    break
  fi
  sleep 1
done

if [ "$REACHABLE" -ne 1 ]; then
  echo "ERROR: Prometheus exposition endpoint at $PROM_ENDPOINT unreachable within ${MAX_TIME_SECONDS}s budget." >&2
  exit 1
fi

# (2) Parse PromQL metric stems from dashboard JSON expr fields
# Extracts tokens matching lancet_[a-zA-Z0-9_]+ and strips _count, _bucket, _sum, _total
STEMS=$(awk '
/"expr":/ {
  line = $0
  while (match(line, /lancet_[a-zA-Z0-9_]+/)) {
    token = substr(line, RSTART, RLENGTH)
    # Strip standard Prometheus suffixes
    sub(/_(count|bucket|sum|total)$/, "", token)
    print token
    line = substr(line, RSTART + RLENGTH)
  }
}
' "$DASHBOARD_JSON" | sort -u)

if [ -z "$STEMS" ]; then
  echo "ERROR: Failed to extract any metric stems from $DASHBOARD_JSON" >&2
  exit 1
fi

echo "Parsed metric stems from dashboard JSON:"
echo "$STEMS" | sed 's/^/  - /'

# (3) POST synthetic OTLP HTTP metrics payload with all 10 D-35 instruments
OTLP_PAYLOAD='{
  "resourceMetrics": [
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "lancet-test-verifier" } }
        ]
      },
      "scopeMetrics": [
        {
          "scope": { "name": "lancet" },
          "metrics": [
            {
              "name": "lancet.rag.query.duration",
              "unit": "ms",
              "histogram": {
                "aggregationTemporality": 2,
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "count": "1",
                    "sum": 123.0,
                    "bucketCounts": ["0", "1", "0"],
                    "explicitBounds": [100.0, 500.0],
                    "attributes": [{ "key": "outcome", "value": { "stringValue": "success" } }]
                  }
                ]
              }
            },
            {
              "name": "lancet.rag.retrieval.path_failures",
              "sum": {
                "aggregationTemporality": 2,
                "isMonotonic": true,
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "asInt": "1",
                    "attributes": [
                      { "key": "path", "value": { "stringValue": "vector" } },
                      { "key": "kind", "value": { "stringValue": "timeout" } }
                    ]
                  }
                ]
              }
            },
            {
              "name": "lancet.rag.answer.degraded",
              "sum": {
                "aggregationTemporality": 2,
                "isMonotonic": true,
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "asInt": "1",
                    "attributes": [{ "key": "answer_basis", "value": { "stringValue": "retrieval" } }]
                  }
                ]
              }
            },
            {
              "name": "lancet.rag.citation.repairs",
              "sum": {
                "aggregationTemporality": 2,
                "isMonotonic": true,
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "asInt": "1",
                    "attributes": [{ "key": "action", "value": { "stringValue": "pruned" } }]
                  }
                ]
              }
            },
            {
              "name": "lancet.rag.generation.retries",
              "sum": {
                "aggregationTemporality": 2,
                "isMonotonic": true,
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "asInt": "1",
                    "attributes": [{ "key": "outcome", "value": { "stringValue": "recovered" } }]
                  }
                ]
              }
            },
            {
              "name": "lancet.rag.evidence.set_size",
              "histogram": {
                "aggregationTemporality": 2,
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "count": "1",
                    "sum": 5.0,
                    "bucketCounts": ["0", "1", "0"],
                    "explicitBounds": [1.0, 10.0]
                  }
                ]
              }
            },
            {
              "name": "lancet.ingest.documents",
              "sum": {
                "aggregationTemporality": 2,
                "isMonotonic": true,
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "asInt": "1",
                    "attributes": [{ "key": "outcome", "value": { "stringValue": "success" } }]
                  }
                ]
              }
            },
            {
              "name": "lancet.ingest.chunks",
              "sum": {
                "aggregationTemporality": 2,
                "isMonotonic": true,
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "asInt": "1"
                  }
                ]
              }
            },
            {
              "name": "lancet.index.rebuild.duration",
              "unit": "ms",
              "histogram": {
                "aggregationTemporality": 2,
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "count": "1",
                    "sum": 450.0,
                    "bucketCounts": ["0", "1", "0"],
                    "explicitBounds": [100.0, 1000.0],
                    "attributes": [{ "key": "outcome", "value": { "stringValue": "success" } }]
                  }
                ]
              }
            },
            {
              "name": "lancet.index.corpus_generation",
              "gauge": {
                "dataPoints": [
                  {
                    "startTimeUnixNano": "1700000000000000000",
                    "timeUnixNano": "1700000001000000000",
                    "asInt": "1"
                  }
                ]
              }
            }
          ]
        }
      ]
    }
  ]
}'

echo "Posting synthetic OTLP HTTP metrics to $OTLP_ENDPOINT..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  --connect-timeout 5 --max-time 10 \
  -H "Content-Type: application/json" \
  -d "$OTLP_PAYLOAD" \
  "$OTLP_ENDPOINT")

if [ "$HTTP_CODE" -ne 200 ] && [ "$HTTP_CODE" -ne 202 ]; then
  echo "ERROR: OTLP metrics push failed with HTTP status $HTTP_CODE" >&2
  exit 1
fi

# (4) Poll :8889/metrics until all stems are matched or 30s budget expires
echo "Polling Prometheus exposition at $PROM_ENDPOINT..."
ALL_FOUND=0
SCRAPE_BODY=""

while [ "$(date +%s)" -le "$DEADLINE" ]; do
  SCRAPE_BODY=$(curl -s --connect-timeout 2 --max-time 5 "$PROM_ENDPOINT" || true)

  MISSING=""
  for stem in $STEMS; do
    if ! printf '%s' "$SCRAPE_BODY" | grep -q "$stem"; then
      MISSING="$MISSING $stem"
    fi
  done

  if [ -z "$MISSING" ]; then
    ALL_FOUND=1
    break
  fi

  sleep 1
done

if [ "$ALL_FOUND" -ne 1 ]; then
  echo "ERROR: Timed out waiting for metric stems in Prometheus scrape within ${MAX_TIME_SECONDS}s budget." >&2
  echo "Missing stems:$MISSING" >&2
  exit 1
fi

# (5) Check for doubled prefix anomalies (e.g. lancet_lancet_)
DOUBLED=$(printf '%s\n' "$SCRAPE_BODY" | grep -E '^# (HELP|TYPE) lancet_lancet_|^lancet_lancet_' || true)
if [ -n "$DOUBLED" ]; then
  echo "ERROR: Doubled prefix detected in Prometheus scrape:" >&2
  echo "$DOUBLED" >&2
  exit 1
fi

echo "Observed exported lines for duration histograms:"
printf '%s\n' "$SCRAPE_BODY" | grep -E 'lancet_rag_query_duration_|lancet_index_rebuild_duration_' | head -20

echo "SUCCESS: All dashboard metric stems verified in live Prometheus exposition with correct prefixes and unit suffixes."
exit 0
