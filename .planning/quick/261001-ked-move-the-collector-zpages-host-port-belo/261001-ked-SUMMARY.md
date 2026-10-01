---
phase: 261001-ked-move-the-collector-zpages-host-port-belo
plan: 01
subsystem: infra
tags: [docker-compose, otel-collector, zpages, windows-reserved-ports]
requires: []
provides:
  - lancet-collector zPages published on 127.0.0.1:15679 (container port 55679 unchanged)
affects: [docker-compose.yml]
key-files:
  modified:
    - docker-compose.yml
decisions:
  - zPages host port 15679 (below 49152, outside the Windows boot-time dynamic reserved range); loopback bind kept
status: complete
commits: 1
plan_head_before: 35830099ebdb1f98459163a34c868318ee318fa6
actuals:
  tokens: 300
  tasks: 2
  commits: 1
completed: 2026-10-01
---

# Quick Task 261001-ked: Collector zPages host port moved below 49152

One-line change in `docker-compose.yml` moves the collector's zPages host port from 55679 to 15679 (`"127.0.0.1:15679:55679"`), so `lancet-collector` no longer collides with this boot's Windows-reserved 55641-55740 block. The collector was recreated alone and is healthy.

## Task 1 commit

- `42c458c14aa8a28898602b83a6953cd30dfe2f18` fix(261001-ked-01): move collector zPages host port below the Windows dynamic range
- numstat `1 1 docker-compose.yml`; last message line is the Co-Authored-By trailer for Claude Opus 5.5; `deploy/collector/otel-collector-config.yaml` untouched.
- The rendered compose config (`config --format json`) publishes exactly 127.0.0.1 host ports 4317, 4318, 8889, 13133 and 15679 (15679 targets 55679).

## Task 2 evidence

- Pre-check: 15679 not in any of 32 reserved ranges; no listener on 15679.
- Snapshot (Id + StartedAt) of lancet-postgres, jaeger, loki, prometheus, grafana before and after: byte-identical (SNAPSHOT-UNCHANGED). Values, both before and after:
  - lancet-postgres eaa7338347a9... started 2026-10-01T20:50:05.768306333Z
  - lancet-jaeger 6f37bfe3c1fc... 2026-10-01T20:50:23.495470607Z
  - lancet-loki 56a662f8337d... 2026-10-01T20:50:23.489365627Z
  - lancet-prometheus 6fe56d45a854... 2026-10-01T20:50:23.499475689Z
  - lancet-grafana ef0a63e9105c... 2026-10-01T20:50:23.886616577Z
- Collector Id changed: old 793d40607be9... -> new d9938898cc7d... (COLLECTOR-RECREATED).
- `docker compose --profile observability up -d --no-deps collector` output touched only the collector: `Container lancet-collector Recreate / Recreated / Starting / Started`.
- Health: curl got one `(52) Empty reply` (Docker proxy before listener ready) and retried; body `{"status":"Server available","upSince":"2026-10-01T21:52:51.288733174Z",...}`.
- zPages `http://127.0.0.1:15679/debug/tracez`: HTTP 200.
- Containers:
  - lancet-collector: Up 7 seconds, `127.0.0.1:4317-4318->4317-4318/tcp, 127.0.0.1:8889->8889/tcp, 127.0.0.1:13133->13133/tcp, 127.0.0.1:15679->55679/tcp`
  - lancet-grafana: Up About an hour
  - lancet-postgres: Up About an hour (healthy)
  - lancet-loki: Up About an hour
  - lancet-jaeger: Up About an hour
  - lancet-prometheus: Up About an hour
- Logs: startup window (17 lines) contains `2026-10-01T21:52:51.288Z info service@v0.120.0/service.go:281 Everything is ready. Begin running and processing data.` and zero error/fatal/panic/dpanic lines. Whole fresh log error-level count: 0. Broad `error|fail|panic` grep matched one line only: the health_check extension start line (config key `ExporterFailureThreshold`), not a fault.
- Identity gate: `uv run --project eval lancet-eval identity check --corpus multihop_rag` exited 0, final line `Identity gate passed.`
- `git status --porcelain` outside `.planning/`: empty.

## Deviations from Plan

None - plan executed exactly as written. (Tracer gate: Task 1 verify passed before expansion.)

## Known Stubs

None.

## Threat Flags

None. Loopback-only bind retained (T-261001-ked-01); no other container or volume touched; no engine/gateway launched; no eval write commands run.

## Self-Check: PASSED

- Commit 42c458c1 exists on main; docker-compose.yml contains `"127.0.0.1:15679:55679"`; this SUMMARY exists.
