"""06.3.4.1-18 Task 3: per-canary transcript of the one live preflight.

Read-only. Joins Jaeger's `query_rag` traces for the preflight window with the
`lancet_eval.workflow_checkpoints` rows (SELECT only, read through `docker exec psql` on a
read-only session) by correlation ID, and maps each query to its canary row by question
text and arm. Usage: python preflight_transcript.py <out_json>
"""
import datetime
import json
import subprocess
import sys
import urllib.parse
import urllib.request

START = datetime.datetime(2026, 10, 6, 8, 44, 40, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 10, 6, 8, 47, 0, tzinfo=datetime.timezone.utc)
BUDGETS = {"query_embedding": 2000, "graph_operation": 2424, "graph_node": 12500, "retrieve": 2500, "prompt": 120}


def tags(span):
    return {t["key"]: t["value"] for t in span["tags"]}


def sql(query):
    out = subprocess.run(
        ["docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on", "lancet-postgres",
         "psql", "-U", "postgres", "-d", "lancet", "-At", "-c", query],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def main(out_path):
    q = urllib.parse.urlencode({
        "service": "lancet-engine", "operation": "query_rag", "limit": 50,
        "start": int(START.timestamp() * 1e6), "end": int(END.timestamp() * 1e6)})
    traces = json.load(urllib.request.urlopen("http://127.0.0.1:16686/api/traces?" + q, timeout=30))["data"]
    manifest = [json.loads(line) for line in open("eval/corpora/multihop_rag/canary.jsonl", encoding="utf-8")]
    by_text = {}
    for row in manifest:
        by_text.setdefault(row["question"], []).append(row)
    checkpoints = {r["trace"]: r for r in sql(
        "select jsonb_build_object('trace', trace_id, 'q', context_snapshot->>'original_query', "
        "'notices', context_snapshot->'notices', 'blocks', jsonb_array_length(context_snapshot->'evidence_blocks'), "
        "'final', jsonb_array_length(context_snapshot->'final_candidates'))::text "
        "from lancet_eval.workflow_checkpoints where created_at > '2026-10-06 01:44:40' and created_at < '2026-10-06 01:47:00' "
        "and node_name = 'post_assembleprompt'")}
    rows = []
    for trace in traces:
        spans = {}
        for s in trace["spans"]:
            spans.setdefault(s["operationName"], s)
        qr = tags(spans["query_rag"])
        corr = qr["correlation_id"]
        cp = checkpoints.get(corr)
        text = cp["q"] if cp else None
        codes = sorted({n.get("code") for n in (cp["notices"] if cp else [])})
        candidates = by_text.get(text, [])
        arm = "graph-off" if "GRAPH_ABLATION" in codes else "graph-on"
        match = [c for c in candidates if c["graph_arm"] == arm]
        ms = lambda name: round(spans[name]["duration"] / 1000.0, 1) if name in spans else None
        rows.append({
            "start_us": spans["query_rag"]["startTime"],
            "correlation_id": corr,
            "canary": (match[0]["question_id"] + ":" + arm) if match else ("probe-or-unmapped:" + arm),
            "floors": {k: match[0].get(k) for k in ("min_retrieved_chunks", "require_graph_node", "require_retrieval_completed_only", "require_ablation_notice", "require_seed_path")} if match else None,
            "retrieved_chunks_final": cp["final"] if cp else None,
            "evidence_blocks_in_prompt": cp["blocks"] if cp else None,
            "graph_node_count": qr.get("lancet.workflow.graph_node_count"),
            "graph_edge_count": qr.get("lancet.workflow.graph_edge_count"),
            "graph_seed_count": qr.get("lancet.workflow.graph_seed_count"),
            "graph_path_found": qr.get("lancet.workflow.graph_path_found"),
            "graph_prompt_fact_count": qr.get("lancet.workflow.graph_prompt_fact_count"),
            "notice_codes": codes,
            "node_ms_vs_budget": {
                "embedding_request": [ms("embedding_request"), BUDGETS["query_embedding"]],
                "graph_traversal (graph operation)": [ms("graph_traversal"), BUDGETS["graph_operation"]],
                "graph_context_extraction (ExtractGraphContext)": [ms("graph_context_extraction"), BUDGETS["graph_node"]],
                "hybrid_retrieval (RetrieveHybrid)": [ms("hybrid_retrieval"), BUDGETS["retrieve"]],
                "prompt_assembly (AssemblePrompt)": [ms("prompt_assembly"), BUDGETS["prompt"]],
            },
            "answer_basis": None,
        })
    rows.sort(key=lambda r: r["start_us"])
    json.dump(rows, open(out_path, "w", encoding="utf-8"), indent=1, default=str)
    for i, r in enumerate(rows, 1):
        n = r["node_ms_vs_budget"]
        print(i, r["canary"], "chunks", r["retrieved_chunks_final"], "gnodes", r["graph_node_count"], "path", r["graph_path_found"],
              "facts", r["graph_prompt_fact_count"], "seeds", r["graph_seed_count"], r["notice_codes"],
              {k.split(" ")[0]: v[0] for k, v in n.items()})


main(sys.argv[1])
