---
phase: 261001-ked-move-the-collector-zpages-host-port-belo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docker-compose.yml
autonomous: true
requirements: []
estimate:
  tokens: 25000
  raw_tokens: 25000
  tasks: 2
  confidence: low
must_haves:
  truths:
    - The collector service in docker-compose.yml publishes zPages as "127.0.0.1:15679:55679" (loopback-only, host port below 49152), and its line comment says the host port is kept below 49152 because Windows reserves random TCP ranges at or above 49152 at boot
    - The collector's other four mappings (4317, 4318, 8889, 13133) are unchanged, and the rendered compose config publishes exactly host ports 4317, 4318, 8889, 13133 and 15679 for the collector, all on 127.0.0.1
    - Exactly one new commit carries the change; it touches only docker-compose.yml (1 insertion, 1 deletion) and the last line of its message is the exact Co-Authored-By trailer for Claude Opus 5.5 that the user specified
    - lancet-collector is recreated and Up; http://127.0.0.1:13133/ answers 200 with "Server available"; http://127.0.0.1:15679/debug/tracez answers 200
    - lancet-postgres, lancet-jaeger, lancet-loki, lancet-prometheus and lancet-grafana keep the same container Id and State.StartedAt before and after the recreate (db never recreated or restarted, no volume touched)
    - All six lancet-* containers show a status starting with "Up"
    - lancet-collector has a new container Id (it was really recreated, so its logs are fresh), and in docker logs lancet-collector the startup window (from container start through the first "Everything is ready" line) contains zero error, fatal, panic or dpanic level lines
    - The read-only identity gate (uv run --project eval lancet-eval identity check --corpus multihop_rag) exits 0 and prints "Identity gate passed."
    - git status shows no changes outside .planning/ after the run (no uv.lock, eval/, data/ or compose drift)
  artifacts:
    - docker-compose.yml
  key_links:
    - docker-compose.yml collector ports entry "127.0.0.1:15679:55679" -> container port 55679 -> deploy/collector/otel-collector-config.yaml zpages extension endpoint 0.0.0.0:55679 (left unchanged, so the container side must stay 55679)
    - docker compose --profile observability up -d --no-deps collector -> recreates only lancet-collector; the service-scoped up plus --no-deps is what keeps db (lancet-postgres) and its postgres_data volume out of the blast radius
---

<objective>
Stop `lancet-collector` failing to start on Windows. Windows reserves random TCP port ranges at or above 49152 at boot (`netsh interface ipv4 show excludedportrange protocol=tcp`). This boot's reserved block 55641-55740 contains the collector's zPages host port, so binding it fails. Move only the zPages host port to 15679, which is below 49152 and so outside the dynamic range. Commit that as one commit, recreate only the collector, and prove the whole observability stack and the Postgres-backed identity gate are healthy.

Purpose: Restore the collector without disturbing the live Postgres container, its volume, the LanceDB eval store, or any other service.
Output: One commit changing one line of `docker-compose.yml`. A recreated, healthy `lancet-collector` with zPages at `http://127.0.0.1:15679/debug/tracez`. Verification evidence recorded in the SUMMARY.
</objective>

<execution_context>
@D:/Repos/lancet/.claude/gsd-core/workflows/execute-plan.md
@D:/Repos/lancet/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md
@docker-compose.yml
@deploy/collector/otel-collector-config.yaml

Grounded at planning time (2026-10-01):
- `lancet-collector` is `Exited (255)`. The other five `lancet-*` containers are Up, and `lancet-postgres` is `(healthy)`.
- All six containers carry compose labels `project=lancet` and `working_dir=D:\Repos\lancet`. Running `docker compose` from the repo root therefore manages them, with no container-name conflict.
- Port 15679 is in none of the 32 reserved ranges on this boot and has no listener.
- The collector config's zPages extension listens on `0.0.0.0:55679` inside the container, and its health_check listens on `0.0.0.0:13133`.
- The collector logs to the console with tab-delimited, lowercase levels. On a good start it logs "Everything is ready. Begin running and processing data." (seen in v0.120.0).
- `identity check` (`eval/src/lancet_eval/cli.py` line 297 -> `identity.compute_identity`) only lists IDs from Postgres, LanceDB and the committed map. The only DELETE lives in the separate `identity pg-delete-extras` command, which this plan never runs.
- `docker-compose.yml` is stored as LF in the index, with `core.autocrlf=true` and a mixed-EOL working copy. The numstat gate compares index blobs, so it is immune to working-copy CRLF. Keep the file's existing line endings anyway.
- The bundled Git Bash curl is 7.85.0 and supports `--retry-all-errors`.
- `python` is on PATH.
- Docker Compose is v2.39.4 and supports `config --format json`.
</context>

<scope_lock>
- Change ONLY the collector's zPages mapping line in `docker-compose.yml`: its host port goes to 15679 and its trailing comment is rewritten. Do not touch any other line, service, port, volume, network or profile, and do not touch the OTLP, metrics or health mappings.
- Do NOT edit `deploy/collector/otel-collector-config.yaml`. The container side stays 55679.
- The code change is ONE commit containing only `docker-compose.yml`. Stage it by explicit path, never with `git add -A` or `git add .`. Do not amend, and do not fold `.planning/` docs into that commit; the quick workflow commits its SUMMARY/STATE bookkeeping separately.
- The only container operation allowed is `docker compose --profile observability up -d --no-deps collector`, run from `D:/Repos/lancet`.
  - Forbidden: `docker compose down`, `up` without a service name, `restart`, `stop`, `rm`, any `-v`/`--volumes` flag, `--force-recreate` on any other service, and `docker volume` commands.
  - Do not touch `lancet-postgres` (service `db`) or the `postgres_data` volume.
  - Use `up`, not `start`: `start` reuses the old container with the old port mapping.
- Launch no engine or gateway process.
- Never write `./data/lancedb-eval` or the live Postgres schema. The only eval command allowed is `lancet-eval identity check --corpus multihop_rag`, which is read-only. Never run `identity pg-delete-extras`.
- Use exactly the user-specified host port 15679. If the pre-`up` check (the start of Task 2's first verify block) finds 15679 reserved or already listening, HALT and report. Do not pick another port without user approval. After `up` succeeds, a `com.docker.backend.exe` listener on 15679 is expected and is not "busy".
</scope_lock>

<tasks>

<task type="tracer">
  <name>Task 1: Move the collector zPages host port to 15679 and commit it as one commit</name>
  <files>docker-compose.yml</files>
  <precondition>Nothing is staged (`git diff --cached --quiet` exits 0) and docker-compose.yml has no uncommitted edits (`git diff --quiet -- docker-compose.yml` exits 0), so the commit carries only this change.</precondition>
  <read_first>
    - `docker-compose.yml` lines 64-83 (the `collector` service). The zPages mapping is the last entry of its `ports:` list, around line 75, and currently publishes host port 55679 to container port 55679 with the trailing comment `# zPages`.
    - `deploy/collector/otel-collector-config.yaml` lines 32-36 are read-only context. The zpages extension endpoint `0.0.0.0:55679` is why the container side must stay 55679.
  </read_first>
  <action>
    In `docker-compose.yml`, edit exactly one line: the collector's zPages entry in `ports:`. Change only its host-port segment so the quoted mapping becomes `"127.0.0.1:15679:55679"`.
    - Keep the `127.0.0.1:` bind prefix (loopback-only, per threat T-261001-ked-01).
    - Keep the container port 55679.
    - Keep the existing indentation and the column alignment of the trailing comment.

    Rewrite that line's trailing comment so it still names zPages and states the reason. Suggested wording: `# zPages; host port kept below 49152 because Windows reserves random TCP ranges >= 49152 at boot`.
    - The comment must contain the literal `49152`.
    - It must NOT quote the previous mapping or say "was ...". It explains the rule, not the history.
    - It is also the place a reader learns that zPages now lives at http://127.0.0.1:15679/debug/tracez. That URL may optionally appear in the comment, but the 49152 reason is mandatory.

    Do not touch any other line. That includes the OTLP gRPC/HTTP, Prometheus exporter and health check mappings, every other service, and `deploy/collector/otel-collector-config.yaml`.

    Before committing, render the compose config. The verify block's rendered-ports assertion must pass, proving the YAML still parses. It must also show the collector publishing exactly 127.0.0.1 host ports 4317, 4318, 8889, 13133 and 15679, with 15679 targeting 55679.

    Commit with `git add docker-compose.yml` (explicit path only). Then run `git commit` with three `-m` arguments, in order:
    1. Subject: `fix(261001-ked-01): move collector zPages host port below the Windows dynamic range`. This follows the repo's quick-task code-commit convention, as in `fix(260824-ipd-01): ...`.
    2. A one-paragraph body: Windows reserves random TCP ranges at or above 49152 at boot; this boot's 55641-55740 block swallowed the zPages host port so lancet-collector could not bind; the host port moves to 15679 and the container port and the collector config are unchanged.
    3. The exact trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` as the final line, per the user's instruction.

    Do not amend and do not create a second commit for this change.
  </action>
  <verify>
    <automated>cd /d/Repos/lancet && test "$(grep -cF '"127.0.0.1:15679:55679"' docker-compose.yml)" = 1 && test "$(grep -F '"127.0.0.1:15679:55679"' docker-compose.yml | grep -cF '49152')" = 1 && CFG="$(docker compose --profile observability config --format json)" && echo "$CFG" | python -c "import json,sys; p=json.load(sys.stdin)['services']['collector']['ports']; got=sorted((x.get('host_ip'),str(x['published']),int(x['target'])) for x in p); want=sorted([('127.0.0.1','4317',4317),('127.0.0.1','4318',4318),('127.0.0.1','8889',8889),('127.0.0.1','13133',13133),('127.0.0.1','15679',55679)]); assert got==want, got; print('rendered collector ports OK')" && COMMIT="$(git rev-parse --verify HEAD)" && NUMSTAT="$(git show --numstat --format= "$COMMIT")" && test "$(echo "$NUMSTAT" | grep -v '^$')" = "$(printf '1\t1\tdocker-compose.yml')" && MSG="$(git log -1 --format=%B "$COMMIT")" && test "$(echo "$MSG" | grep -v '^[[:space:]]*$' | tail -1)" = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git diff --quiet "$COMMIT" -- docker-compose.yml deploy/collector/otel-collector-config.yaml && echo "commit $COMMIT" && echo TASK1-OK</automated>
  </verify>
  <done>
    - `docker-compose.yml` has exactly one `"127.0.0.1:15679:55679"` line, and its comment contains `49152`.
    - The rendered config publishes exactly 127.0.0.1 host ports 4317, 4318, 8889, 13133 and 15679 for the collector, with 15679 targeting 55679.
    - HEAD is a single new commit whose numstat is exactly `1 1 docker-compose.yml`. Its last message line is the exact Co-Authored-By trailer.
    - `deploy/collector/otel-collector-config.yaml` is unchanged in that commit.
    - `docker-compose.yml` has no leftover uncommitted edits.
  </done>
</task>

<task type="auto">
  <name>Task 2: Recreate only lancet-collector and verify the stack and identity gate end to end</name>
  <files>(no repository files; runtime state of the lancet-collector container only)</files>
  <precondition>Task 1's commit is HEAD, Docker Desktop is running, and `lancet-postgres` shows `Up ... (healthy)` in `docker ps`.</precondition>
  <read_first>
    - `docker-compose.yml` lines 64-83: the collector's `depends_on` is jaeger, loki and prometheus, not db. `--no-deps` stops `up` from touching even those.
    - `eval/src/lancet_eval/cli.py` lines 297-319: `identity check` prints "Identity gate passed." and exits 0 on success, and exits 1 on failure.
  </read_first>
  <action>
    Run every step from `D:/Repos/lancet` in Git Bash.

    Execute steps 1-4 by running Task 2's FIRST `<automated>` block verbatim, in ONE Bash invocation, exactly once.
    - That block is both the execution and its own evidence. Shell variables do not persist between calls, and the before/after snapshot comparison depends on them.
    - It is SINGLE-SHOT: never re-run it, and do not hand-run a separate `up` before it. After a successful `up`, Docker Desktop's `com.docker.backend.exe` legitimately LISTENs on 127.0.0.1:15679 (it already does so for 5432 and 16686), and a second `up` no longer changes the collector Id. A re-run would therefore fail its pre-check and its recreate check even though the change succeeded.
    - If the block fails after its `up` line succeeded, diagnose using only the SECOND `<automated>` block, which is the re-runnable post-condition check.
    - Its output prints both snapshots for the SUMMARY. Write no snapshot files inside the repo.

    1. **Port pre-check.** Run the locale-safe reserved-range check from the verify block: pipe netsh's output into python, decode it as ASCII with errors ignored, parse every two-integer range line, and assert that at least one range parsed and none contains 15679. Then confirm `netstat -ano` shows no listener on 15679. This is a pre-`up` check only. If either check fails at this point, before `up` has run, HALT per the scope lock. Do not choose another port.
    2. **Before-snapshot.** Store `docker inspect -f '{{.Name}} {{.Id}} {{.State.StartedAt}}'` for lancet-postgres, lancet-jaeger, lancet-loki, lancet-prometheus and lancet-grafana in a shell variable. Also store the current (Exited) lancet-collector container Id.
    3. **Recreate the collector only.** Run `docker compose --profile observability up -d --no-deps collector`, per the user's instruction.
       - `up` is required rather than `start` because the port mapping changed, and compose sees a new config hash and recreates the container.
       - `--no-deps` keeps compose from acting on jaeger, loki or prometheus. db is not in the collector's dependency chain at all.
       - Do not add `--force-recreate`, `--renew-anon-volumes`, `-V` or any volume flag.
       - If `up` fails, capture its full error output and HALT. Do not retry with other flags and do not touch other services.
    4. **Health poll, then after-snapshot.**
       - Poll the health endpoint with curl: `--fail`, `--retry 30`, `--retry-all-errors`, `--retry-delay 1` and `--max-time 5` against http://127.0.0.1:13133/. Do not use a foreground sleep.
       - Use `--retry-all-errors` rather than `--retry-connrefused`. Docker Desktop's port proxy can accept the connection and then drop it before the collector listens (curl exit 52/56), and the health extension returns 503 until ready. Neither is a "connection refused", so a refused-only retry would not cover them.
       - Require HTTP 200 and a body containing "Server available".
       - Then take the after-snapshot with the same `docker inspect` format and assert it is byte-identical to the before-snapshot.
       - Assert that the lancet-collector Id now differs from the stored one. That proves compose really recreated the collector rather than restarting the old container. It matters for the log check: the old container dates from 2026-08-26, and its accumulated log holds about 7300 historical runtime `error` lines (exporter "Exporting failed. Rejecting/Dropping data", 2026-08-29 to 2026-09-26) that a mere restart would carry over.
    5. **Remaining checks.** Only after health is green, run the verify block's remaining checks:
       - zPages at http://127.0.0.1:15679/debug/tracez returns 200.
       - Exactly six `lancet-*` rows appear in `docker ps -a`, every status starts with `Up` (postgres shows `Up ... (healthy)`, so match the `Up ` prefix), and the collector's port column shows `127.0.0.1:15679->55679/tcp`.
       - Take the startup window of `docker logs lancet-collector 2>&1`: every line from container start through the first "Everything is ready" line, inclusive. The window must contain "Everything is ready" and zero tab-delimited `error`, `fatal`, `panic` or `dpanic` level lines.
         - This is the user's "no startup errors" criterion, scoped to startup because the collector's runtime exporter errors are a different concern.
         - For the SUMMARY, also report the error-level count for the whole fresh log, plus a broad case-insensitive `error|fail|panic` grep, for human review. A nonzero post-startup count is recorded, not a failure. With no engine or gateway running, no telemetry flows, so none is expected.
       - `uv run --project eval lancet-eval identity check --corpus multihop_rag` exits 0 and prints "Identity gate passed.". It is read-only and needs Postgres; run it from the repo root.
       - `git status --porcelain` shows nothing outside `.planning/`. `uv run` can rewrite a stale `uv.lock`; if anything outside `.planning/` is dirty, report it and do not commit it.
    6. **Record the evidence in the SUMMARY:**
       - both snapshots and their equality result;
       - the `up` output, which must show only the collector being recreated or started;
       - the health body;
       - the tracez status code;
       - the six-row container table;
       - the "Everything is ready" log line and the broad error-grep result;
       - the identity check's final line;
       - the commit hash from Task 1.
  </action>
  <verify>
    <automated>cd /d/Repos/lancet && netsh interface ipv4 show excludedportrange protocol=tcp | python -c "import re,sys; t=sys.stdin.buffer.read().decode('ascii','ignore'); r=[(int(a),int(b)) for a,b in re.findall(r'(?m)^\s*(\d+)\s+(\d+)',t)]; bad=[x for x in r if x[0]<=15679<=x[1]]; assert r, 'no ranges parsed'; assert not bad, bad; print('15679 not reserved;', len(r), 'ranges')" && NETSTAT="$(netstat -ano)" && test "$(echo "$NETSTAT" | grep -cE '[:.]15679[[:space:]]')" -eq 0 && SNAP='lancet-postgres lancet-jaeger lancet-loki lancet-prometheus lancet-grafana' && BEFORE="$(docker inspect -f '{{.Name}} {{.Id}} {{.State.StartedAt}}' $SNAP)" && OLDCOL="$(docker inspect -f '{{.Id}}' lancet-collector 2>/dev/null || echo none)" && echo "BEFORE:" && echo "$BEFORE" && echo "old collector: $OLDCOL" && docker compose --profile observability up -d --no-deps collector && HB="$(curl -sS --fail --retry 30 --retry-all-errors --retry-delay 1 --max-time 5 http://127.0.0.1:13133/)" && echo "health: $HB" && echo "$HB" | grep -qF 'Server available' && AFTER="$(docker inspect -f '{{.Name}} {{.Id}} {{.State.StartedAt}}' $SNAP)" && echo "AFTER:" && echo "$AFTER" && test "$BEFORE" = "$AFTER" && echo SNAPSHOT-UNCHANGED && NEWCOL="$(docker inspect -f '{{.Id}}' lancet-collector)" && echo "new collector: $NEWCOL" && test "$NEWCOL" != "$OLDCOL" && echo COLLECTOR-RECREATED</automated>
    <automated>cd /d/Repos/lancet && test "$(curl -sS --retry 10 --retry-all-errors --retry-delay 1 --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:15679/debug/tracez)" = 200 && echo "tracez 200" && ALLPS="$(docker ps -a --format '{{.Names}}|{{.Status}}|{{.Ports}}')" && ROWS="$(echo "$ALLPS" | grep '^lancet-')" && echo "$ROWS" && test "$(echo "$ROWS" | wc -l)" -eq 6 && test "$(echo "$ROWS" | cut -d'|' -f2 | grep -vc '^Up ')" -eq 0 && test "$(echo "$ROWS" | grep '^lancet-collector|' | grep -cF '127.0.0.1:15679->55679/tcp')" -eq 1 && LOGS="$(docker logs lancet-collector 2>&1)" && STARTUP="$(echo "$LOGS" | sed '/Everything is ready/q')" && test "$(echo "$STARTUP" | grep -c 'Everything is ready')" -eq 1 && test "$(echo "$STARTUP" | grep -cE "$(printf '\t')(error|fatal|panic|dpanic)$(printf '\t')")" -eq 0 && echo "startup window clean ($(echo "$STARTUP" | wc -l) lines); whole-log error-level count: $(echo "$LOGS" | grep -cE "$(printf '\t')(error|fatal|panic|dpanic)$(printf '\t')")" && echo "broad error grep (review):" && (echo "$LOGS" | grep -iE 'error|fail|panic' || echo "none") && OUT="$(uv run --project eval lancet-eval identity check --corpus multihop_rag 2>&1)"; RC=$?; echo "$OUT" | tail -3; test $RC -eq 0 && test "$(echo "$OUT" | grep -cF 'Identity gate passed.')" -ge 1 && GS="$(git status --porcelain -- . ':!.planning')" && test -z "$GS" && echo TASK2-OK</automated>
  </verify>
  <done>
    - `up --no-deps collector` recreated only `lancet-collector`, which now has a new container Id.
    - The Id and StartedAt of the five other `lancet-*` containers are byte-identical before and after.
    - The health endpoint returns 200 with "Server available", and http://127.0.0.1:15679/debug/tracez returns 200.
    - All six `lancet-*` containers are Up, and the collector maps `127.0.0.1:15679->55679/tcp`.
    - The fresh collector log's startup window, through "Everything is ready", has zero error, fatal, panic or dpanic level lines. The whole-log count is recorded in the SUMMARY.
    - `identity check --corpus multihop_rag` exits 0 and prints "Identity gate passed.".
    - The working tree is clean outside `.planning/`.
    - The SUMMARY records all of this evidence plus the Task 1 commit hash.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| host network -> collector zPages | zPages exposes in-process trace/span and pipeline debug pages with no authentication; only the loopback bind keeps it off the LAN |
| compose CLI -> live Docker state | a mis-scoped compose command can recreate or restart lancet-postgres or drop named volumes holding live data |
| eval CLI -> Postgres / LanceDB | the eval CLI has both a read-only `identity check` and a destructive `identity pg-delete-extras` |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-261001-ked-01 | Information disclosure | docker-compose.yml collector zPages mapping | medium | mitigate | Task 1 keeps the `127.0.0.1:` prefix. Its verify asserts the exact quoted `"127.0.0.1:15679:55679"` line and that the rendered config's `host_ip` is 127.0.0.1 for all five collector ports. Task 2's verify asserts the live port column shows `127.0.0.1:15679->55679/tcp`. |
| T-261001-ked-02 | Tampering / Denial of service | `docker compose up` against lancet-postgres and the postgres_data volume | high | mitigate | The service-scoped `up -d --no-deps collector` is the only container command allowed. down, restart, stop, rm, volume flags and `--force-recreate` on other services are forbidden by the scope lock. A before/after `docker inspect` snapshot of Id and StartedAt for the five other containers must be byte-identical. |
| T-261001-ked-03 | Denial of service | collector host port collides with a Windows reserved range again | low | mitigate | 15679 is below 49152, so it is outside the dynamic range Windows reserves at boot. A locale-safe netsh parse plus a netstat listener check run before `up`, and the plan halts rather than picking an unapproved port. |
| T-261001-ked-04 | Tampering | eval CLI against the live Postgres schema and ./data/lancedb-eval | medium | mitigate | Only `identity check --corpus multihop_rag` may run. Source shows `compute_identity` only lists IDs, while the DELETE lives solely in `identity pg-delete-extras`, which the scope lock forbids. A clean git status outside .planning/ catches incidental writes such as uv.lock. |
| T-261001-ked-05 | Repudiation | commit provenance | low | accept | The commit message ends with the exact user-specified Co-Authored-By trailer and is checked by Task 1's verify. No further control is needed for a one-line local config change. |
</threat_model>

<verification>
- Task 1 verify prints `TASK1-OK`: one-line change, rendered ports exact, single commit `1 1 docker-compose.yml`, trailer last, collector config untouched.
- Task 2's first verify block is single-shot because it contains the `up`. Run it once and never re-run it; the second block is the re-runnable post-condition check. Together they print `SNAPSHOT-UNCHANGED` and `COLLECTOR-RECREATED`, then `TASK2-OK`: collector recreated alone with a new Id, health and zPages up, six containers Up, clean startup window in logs, identity gate passed, tree clean outside .planning/.
</verification>

<success_criteria>
- `lancet-collector` starts and stays Up, binding `127.0.0.1:15679` for zPages, and no longer collides with Windows' boot-time reserved ranges at or above 49152.
- The change is exactly one commit touching one line of `docker-compose.yml`, ending with the Co-Authored-By trailer.
- lancet-postgres and every other non-collector container are provably untouched (same Id and StartedAt), with no volume touched and no engine or gateway launched.
- The health check, zPages and logs are clean, and `lancet-eval identity check --corpus multihop_rag` still prints "Identity gate passed.".
</success_criteria>

<output>
Create `.planning/quick/261001-ked-move-the-collector-zpages-host-port-belo/261001-ked-SUMMARY.md` when done, recording the Task 1 commit hash and the Task 2 evidence listed in step 6 of its action.
</output>
