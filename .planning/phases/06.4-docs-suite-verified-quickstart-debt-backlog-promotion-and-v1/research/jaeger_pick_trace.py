"""List the smallest recent single-query traces in the local Jaeger (read-only GET)."""
import json, urllib.request
def get(u): return json.load(urllib.request.urlopen(u, timeout=20))
d = get("http://127.0.0.1:16686/api/traces?service=lancet-gateway&limit=300&lookback=7d")["data"]
rows = []
for t in d:
    ops = {s["operationName"] for s in t["spans"]}
    svcs = {t["processes"][s["processID"]]["serviceName"] for s in t["spans"]}
    root = min(t["spans"], key=lambda s: s["startTime"])
    rows.append((len(t["spans"]), t["traceID"], root["operationName"], sorted(svcs), root["duration"]//1000, "rerank" in " ".join(ops).lower(), any("graph" in o for o in ops)))
rows.sort()
print("traces:", len(rows))
for r in rows[:12]: print(r)
print("with rerank-ish ops:", sum(1 for r in rows if r[5]))
