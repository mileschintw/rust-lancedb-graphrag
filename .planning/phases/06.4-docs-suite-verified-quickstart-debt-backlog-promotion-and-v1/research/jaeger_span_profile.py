"""Profile the span names of one local Jaeger trace (read-only GET)."""
import json, urllib.request, collections, sys
tid = sys.argv[1]
t = json.load(urllib.request.urlopen(f"http://127.0.0.1:16686/api/traces/{tid}", timeout=20))["data"][0]
c = collections.Counter(s["operationName"] for s in t["spans"])
for k, v in c.most_common(15): print(v, k)
print("total", len(t["spans"]))
root = min(t["spans"], key=lambda s: s["startTime"])
tags = {x["key"]: x["value"] for x in root["tags"]}
print({k: tags[k] for k in tags if k.startswith("lancet") or k in ("graph_augmentation",)})
