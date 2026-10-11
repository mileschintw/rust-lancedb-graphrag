# Verified facts for Phase 06.4 (ground truth for research, planning and plan checking)

The orchestrator read every fact below from source at HEAD `d209331a` on 2026-10-11, or observed it on this host
the same day. Treat these facts as ground truth.

**Rules for using this file:**
- Cite `path:line` when you use a fact.
- Mark anything the phase adds as **PROPOSED**.
- Where a fact here and your own reading of the code disagree, say so explicitly. Do not silently pick one.
- Put any script you run in this `research/` directory (never the scratchpad). `*.out` is gitignored
  (`.gitignore:94`), so a cited output needs `git add -f`.
- Governing decisions: `06.4-CONTEXT.md` (D-198..D-226) AND `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md`
  (inherited D-01..D-86). Read both.

---

## A. Wire contract (`proto/lancet/v1/lancet.proto`)

- **A1. `QueryRAGRequest` uses tags 1-8** (`lancet.proto:83-110`). The next free tag is **9**.
  - `allow_model_only = 4` is `optional bool`, the D-12 presence pattern: absent = configured default, false =
    explicitly off (`:88-91`). This is the template D-207 names.
  - `disable_graph_context = 5` is already `optional bool` (`:96`). Its comment (`:93-95`) says "`graph-on` is the
    absent/false state". D-207 rewrites this comment.
  - `levers = 8` is `repeated Lever`; empty == absent == today's request (`:107-109`).
- **A2. `NoticeCode` highest value is 24** (`NOTICE_CODE_DEFAULT_LEVER_UNAVAILABLE`, `:151`). Tag 17 is `reserved`
  (`:135`). Values 6-9 are unused and NOT reserved. The next free value after the highest is **25**.
  `NOTICE_CODE_GRAPH_ABLATION = 18` (`:136`).
- **A3. `Lever` enum is 0-4** (`:70-81`): RERANK 1, EVIDENCE_METADATA 2, BINARY_ANSWER_FORMAT 3, GRAPH_V2 4.
- **A4. `RetrievalSnapshot` has tags 1-15 and no graph-state field** (`:204-224`). `levers = 15` is the canonical
  echo of the admitted levers. There is no echo of the effective graph state, so graph state can only be inferred
  from notices (`GRAPH_ABLATION`, the new D-207 code) and `WorkflowMetadata` graph counters
  (`graph_node_count` 6, `graph_seed_count` 12, `graph_path_found` 13, `:309-330`).

## B. Engine admission and the graph flag

- **B1. The graph flag is resolved in TWO places, both as `unwrap_or(false)`:**
  - `engine/src/service.rs:1244-1245`: `// Resolved once at admission; Phase 6 adds no configuration key for this flag.`
    then `let disable_graph_context = req.disable_graph_context.unwrap_or(false);`
  - `engine/src/workflow/mod.rs:165` (in `WorkflowContext::new`): `disable_graph_context: request.disable_graph_context.unwrap_or(false),`
  - The D-12 analog for overriding a context default with a configured one: `WorkflowContext::new` sets
    `allow_model_only: request.allow_model_only.unwrap_or(false)` (`workflow/mod.rs:171`), and the service then
    overrides it: `ctx.allow_model_only = req.allow_model_only.unwrap_or(wf.allow_model_only_answers);` (`service.rs:1389`,
    just before `ctx.levers = levers;`). D-207 needs the same shape for the graph flag.
- **B2. Lever admission** (`service.rs:1262-1330`):
  - `LeverSet::try_from_wire(&req.levers)` refuses bad levers with `invalid_levers` (`:1262-1270`).
  - `let levers = if requested.is_empty() { self.effective_settings.default_levers } else { requested };` (`:1276-1281`).
    This is where D-198's opt-out adds a branch.
  - `if levers.contains(v1::Lever::GraphV2) && disable_graph_context` → `invalid_lever_combination` (`:1284-1294`).
    Today it fires only on an explicit `true`. D-207 says a request naming `graph_v2` while the graph state
    *resolves* to off must fail closed.
  - Availability: an unavailable configured default is dropped (`dropped_defaults`), an unavailable named lever is
    refused `lever_unavailable` (`:1296-1330`). The dropped defaults become `DEFAULT_LEVER_UNAVAILABLE` notices at
    `Warning` severity (`service.rs:1391-1401`).
- **B3. Graph node** (`engine/src/workflow/nodes/graph_context.rs`):
  - `:108` `let needs_query_embedding = ctx.runs_dense() || !ctx.disable_graph_context;` (D-125: a BM25-only
    graph-off request takes no embedding call).
  - `:150-159` the early return emits `NoticeCode::GraphAblation`, message `"Graph context disabled by caller request"`,
    `NoticeSeverity::Info`. A config-off graph must emit the new D-207 code here instead, so the context has to carry
    WHY the graph is off (PROPOSED: an enum, not a bool).
- **B4. `derive_degraded_mode` is an exhaustive `match`** (`engine/src/workflow/mod.rs:323-361`). The excluded arm is
  `Unspecified | NoEvidence | ModelNotice | ModelWarning | CitationRepaired | GraphAblation` (`:351-356`). A new
  `NoticeCode` variant will not compile until it is placed in an arm. D-207 puts the new code in the excluded arm.

## C. Configuration

- **C1. `[engine.graph]`** is at `config/config.toml:111-136` and `config/config.example.toml:136-161`
  (`seed_match_min_score`, `max_hop_cap`, `max_seeds`, `mention_vector_top_k`, `degree_cap`, `max_path_facts`,
  `max_graph_chunk_candidates`, `graph_v2_chunk_precision`). `GraphConfigSettings` is `engine/src/config.rs:247-280`.
  There is no graph-default key today. D-207's key belongs here (name is Claude's discretion).
- **C2. `[engine.levers] defaults = ["rerank", "evidence_metadata"]`** (`config/config.toml:138-155`, with the
  derivation comment). `LeversConfigSettings` is `config.rs:692`. The env override `LANCET_ENGINE__LEVERS__DEFAULTS`
  is parsed at `config.rs:1224` (blank = no default lever). The compiled-in default is empty and a unit test pins the
  list in both committed config files (comment at `config.toml:153-154`).
- **C3. D-12 analog:** `[engine.workflow] allow_model_only_answers = false # D-10/D-12` (`config/config.toml:85`),
  default fn `config.rs:427`, field `:501-502`, env override parsed at `config.rs:1165`.
- **C4. The overlays `config/config.eval.toml` and `config/config.verify.toml` have no `[engine.graph]` or
  `[engine.levers]` section.** Research must confirm how an overlay merges with `config.toml` before planning where
  the D-207 key is read in each environment.
- **C5. `LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION`** is read at `config.rs:1208`. The comment at `:1207` and
  `:1222` says the rehearsal and drive launchers refuse `LANCET_ENGINE__GRAPH__*`. Those launchers are the
  gitignored per-session `data/oi02-evidence/*/launch.ps1` (06.4-DISCUSSION-LOG). D-199 moves the refusal into
  committed harness code.

## D. Engine startup order (`engine/src/main.rs`, WR-01 / D-202)

- Boot metadata coverage WARN: `:80-92` (logged once, at boot only).
- Lever reranker built `:112-122`; D-194 default-lever availability WARN loop `:123-136`.
- Extraction generator `:137-152`.
- **Worker spawned `:161-171`** (`spawn_worker_with_concurrency`); debounce task `:173-182`.
- **Staged jobs replayed `:184-193`.**
- AFTER the replay, still fallible with `?`: generation config + generator `:195-208`;
  `settings.engine.grpc_addr.parse()?` `:224`; tokenizer warm-up `:228-236`;
  `Server::builder()...serve_with_shutdown(addr, ...)` `:245-251` (the port bind happens inside serve).
- The source-order pin to extend: `fn main_runs_the_default_lever_check_before_the_workers_and_the_replay`
  at `engine/src/tests/levers_pins.rs:1962`.

## E. Rebuild-swap logging (WR-02 / D-203)

- `log_doc_meta_availability_change` (`engine/src/ingest.rs:1969-1991`) logs only an emptiness transition
  (non-empty → empty WARN; empty → non-empty INFO). Unchanged emptiness logs nothing; partial coverage after a
  rebuild is never logged. Its text asserts "a configured default is dropped" regardless of configuration (IN-01).

## F. Gateway (`gateway/main.go`)

- Request body struct: `AllowModelOnly *bool` `:589`, `DisableGraphContext *bool` `:590`, `RetrievalMode *string`
  `:593`, `IncludePreTruncationRanking *bool` `:595`, `Levers *[]string` `:599`. `maxRequestLevers = 4` `:604`.
- Forwarding: `DisableGraphContext: body.DisableGraphContext,` `:805` (pointer passed through, so absent / false / true
  are already distinct), `Levers: levers` `:808`.
- Ingest metadata form fields: `doc_title` `:396`, `source` `:397`, `published_date` `:398` (layout const `:67`, a bare
  calendar date).
- `gateway/go.mod:3`: `go 1.25.0`.

## G. Evaluation harness request path

- **G1. `run_query`** (`eval/src/lancet_eval/client.py:249-278`) takes `disable_graph_context: bool = False` and sends
  the field ONLY when it is `True` (`:271-272`). It sends `levers` only when non-empty (`:277-278`). It has no way to
  send `disable_graph_context: false` or a lever opt-out.
- **G2. Arm registry** (`eval/src/lancet_eval/arms.py:100-158`): `dense-only`, `bm25-only`, `hybrid` (alias
  `graph-off`), `hybrid+graph` (alias `graph-on`), `hybrid+rerank`, `hybrid+metadata`, `hybrid+answer-format`,
  `hybrid+graph-v2` (only when `graph_v2` is declared), `hybrid+all`. All three lever arms set
  `disable_graph_context=True` (`:123-140`). `hybrid+graph`, `hybrid+graph-v2` and `hybrid+all` (with graph_v2
  declared) leave it `False`, so they send no field.
- **G3. `request_fields`** (`arms.py:227-253`): legacy labels return exactly the bodies drives 1, 1b and 2 sent
  (`:245-246`); canonical labels add `retrieval_mode`, `include_pre_truncation_ranking=True`, and `levers` only for
  lever arms (`:247-253`).
- **G4. Provenance clauses that D-198/D-207 interact with:**
  - clause (h) `lever_echo_failures` (`arms.py:280-304`): an arm with no levers must see an EMPTY echo. Under the
    committed defaults, a control arm that names no lever gets `[rerank, evidence_metadata]` echoed, so (h) fails today.
  - clause (e) `ablation_failures` (`arms.py:307-344`): a graph-off arm must carry `GRAPH_ABLATION` and not
    `GRAPH_UNAVAILABLE`; a graph-on arm must not carry `GRAPH_ABLATION`.
- **G5. Every `run_query` caller** (each must be reviewed against D-198 and D-207):
  - `eval/src/lancet_eval/run.py:410` (drives);
  - `eval/src/lancet_eval/preflight.py:866` and `:1203` (the arm-mode canaries, `run_query(**request_fields(arm))`,
    documented at `:1111`);
  - `eval/src/lancet_eval/cli.py:1205` (`probe`);
  - `eval/src/lancet_eval/measure.py:388`. **`measure` drives the LEGACY labels** `MEASUREMENT_ARMS = ("graph-off",
    "graph-on")` (`measure.py:50`), with `disable_graph_context = arm == "graph-off"` (`:385`). Under D-207 its
    "graph-on" arm would silently run graph-off, and under the committed defaults both arms run the default levers.
  - `eval/scripts/drive_measurement_pass.py:132` and `:245` (deleted by D-211).

## H. `lancet-eval measure` (D-211)

- **H1. The command is `lancet-eval measure`, not `measure-latency`.** `@app.command("measure")` at
  `eval/src/lancet_eval/cli.py:1349`; the Python function is `measure_latency` (`:1350`). CONTEXT, ROADMAP and the
  06.3.6 SECURITY file say `measure-latency`; plans must use the real command name.
- **H2. Its `--cheap-model` option is accepted and never used** (`cli.py:1377-1383`; not passed to
  `run_measurement_pass`, `:1416-1423`).
- **H3. It is already identity-gated:** `run_measurement_pass` calls `require_index_identity(settings, corpus_name)`
  first (`eval/src/lancet_eval/measure.py:633`; definition `eval/src/lancet_eval/identity.py:234`). There is NO
  split-role or pre-registration check (confirmed: 06.3.6-SECURITY.md:175).
- **H4. The analog for a split-role guard** is `_enforce_split_role` (`eval/src/lancet_eval/run.py:289-330`). Split
  roles are `{"heldout", "rehearsal", "dev"}` (`eval/src/lancet_eval/corpus.py:107`); `CorpusConfig.split_role` is
  `None` when the corpus TOML has no `[split]` (`corpus.py:168-182`).
- **H5. Deleting `eval/scripts/drive_measurement_pass.py` breaks a test:** `eval/tests/test_wire_capture.py:353-369`
  (`test_every_wire_metadata_field_is_mapped_at_each_drive_site`) lists the script as one of three drive sites and
  reads it from disk. The deletion must edit that test in the same commit.

## I. `score` / `report` write paths (D-200, D-201)

- `score` (`cli.py:642-765`) calls `score_run`; the writes are in `eval/src/lancet_eval/score.py:3315-3326`:
  `report.json` (and `judged-result.json` when judged) into the run directory, only when the run is not partial.
  `cli.py:761` only prints the path. (CONTEXT cites `cli.py:762`; the write itself is `score.py:3324-3326`.)
- `report` (`cli.py:894-972`) writes `report.md` (`:956-958`), `report.json` (`:960-961`) and `metadata.json`
  (`:963-964`) into `--run`. Neither command has an output-directory option.
- `metadata.commit_sha` = `GIT_COMMIT_SHA` env, else `get_commit_sha()` (`score.py:3288`), which runs
  `git rev-parse HEAD` with `cwd=repo_root()` (`eval/src/lancet_eval/config.py:24-36`), and `repo_root()` is
  `Path(__file__).resolve().parents[3]` (`config.py:19-21`), i.e. package-relative. So a run directory copied outside
  the repo still stamps the repo HEAD.
- `result_hash = compute_result_hash(dimensions)` (`score.py:3214`): it covers the scored dimensions, not metadata.
- `score_run` refuses a `[split]` corpus journal unless the pre-registration commits are git ancestors of HEAD and
  older than the journal header (`score.py:1724-1727` docstring; `git_repo=None` means the live repo). **A shallow
  clone may fail this check.** Research must test it, because the quickstart starts from `git clone`.

## J. Review-finding inventory (D-204, D-212)

- **J1. The full 06.3.6 review is only in git:** `git show c73dbe3c:.planning/phases/06.3.6-quality-levers-measured-as-arms-reranker-graph-repair-by-dia/06.3.6-REVIEW.md`
  (924 lines; 0 critical, 17 warning, 22 info). A copy is NOT committed; extract it into this `research/` folder if you
  need it on disk. Finding headings: A-WR-01..06 (`:178-282`), A-IN-01..07 (`:306-373`), B-WR-01..05 (`:437-530`),
  B-IN-01..08 (`:548-632`), C-WR-01..06 (`:689-829`), C-IN-01..07 (`:844-908`).
- **J2. The current `06.3.6-REVIEW.md` is the plan-23 re-review** (2 warning, 5 info): WR-01 (`:79`), WR-02 (`:102`),
  IN-01 (`:131`), IN-02 (`:142`), IN-03 (`:151`), IN-04 (`:162`), IN-05 "A test pins a 400 for a default that the new
  semantics would drop" (`:173`).
- **J3. `06.3.6-REVIEW-DISPOSITION.md` holds 46 rows: 3 fixed (A-WR-01..03), 3 deferred, 40 open.** Open: A-WR-05,
  A-WR-06, A-IN-01..07, B-WR-01..05, B-IN-02..08, C-WR-02..06, C-IN-01..07, and the re-review's WR-01, WR-02,
  IN-01..IN-05. **Count correction:** D-204 says "13 warnings (A-WR-05/06, B-WR-01..05, C-WR-02..06)"; those IDs are
  12. With the re-review's WR-01/WR-02 the open warnings are 14. Open info rows are 21 from c73dbe3c plus 5 from the
  re-review.
- **J4. D-212's "IN-05" and "IN-06" are 06.3.5 review findings, not 06.3.6 ones:**
  - IN-05 = `06.3.5-REVIEW.md:175`: `eval/scripts/gen_paper_golden.py:56-62` (`load_official` runs
    `spec.loader.exec_module`) and `:243-247` (the sha256 is recorded only after execution). Pinned constants
    `OFFICIAL_REPO`/`OFFICIAL_COMMIT`/`OFFICIAL_FILE` are at `:40-42`.
  - IN-06 = `06.3.5-REVIEW.md:181`: hand-rolled `sha256_hex` at `engine/src/bin/inspect_lancedb.rs:1306-1371`.
    `sha2` 0.10.9 and 0.11.0 are already in `engine/Cargo.lock` (`:8745`, `:8756`) as transitive dependencies, but not
    in `engine/Cargo.toml`. Adding a direct dependency changes `Cargo.lock`, so `cargo test --locked` fails until the
    lock is updated and committed.
- **J5. Other v1 ledgers with open rows, not covered by any 06.4 D-ID:**
  - `06.3.5-REVIEW-DISPOSITION.md`: open IN-01..IN-06. IN-05/IN-06 are covered by D-212; IN-01..IN-04 are not.
  - `06.3.4.1-REVIEW-DISPOSITION.md`: open WR-05..WR-13 and IN-01..IN-09 (18 rows). WR-10 is
    `drive_measurement_pass.py` (D-211). The other 17 are not covered by any D-ID.
  - STATE.md "Known Issues & Debt" lists residual debt IDs that are not among the 18 of 06-CONTEXT D-03:
    DEBT-P6-WR-01..03 (06-REVIEW) and DEBT-P6.2-WR-01..06, DEBT-P6.2-IN-01 (06.2-REVIEW).
  - Ledger parser caveat: A-/B-/C- prefixed rows are dropped by the ledger parser; merge by hand (memory).

## K. Stale facts in today's README and docs

- `README.md:105-125` ("Running locally"): `docker compose up -d` "Starts PostgreSQL, Jaeger, Prometheus, Loki, the
  OTel Collector and Grafana". **False:** jaeger, prometheus, loki, collector and grafana are under
  `profiles: [observability]` (`docker-compose.yml:29,45,59,80,102`); only `db` starts without
  `--profile observability`.
- The same section says "copy `config/config.example.toml` to `config/config.toml`". **`config/config.toml` is
  tracked** (it carries the shipped defaults); copying the example over it would replace them.
- `README.md:76-103`: the graph cost line "+1.2 to +1.6 s, +210 prompt tokens" is the 06.3.4.1 figure that D-210 says
  must be reconciled, not repeated.
- `README.md:154-203`: the per-phase roadmap still shows 06.3.5/06.3.6 as planned and 6.4 as parked (D-215
  condenses it).
- `docs/` holds one file today: `docs/evaluation-fidelity-and-graph-yield.md`.
- ADRs: `.discussion/decisions/phases/02/` ADR-02-001..004 and `.../03/` ADR-03-001..003 (7 ADRs); plus
  `.discussion/final_implementation_decision_document.md`, `implementation_plan.md`, `lightweight_state_machine_plan.md`,
  `rag_side_project_brainstorming_document.md`. There are no ADR files for the LangGraph / LanceDB / chunking / Go+Rust
  choices D-67 names; research must find where those were decided.

## L. Environment on this host (observed 2026-10-11)

- **Windows host:** Docker 28.4 (`C:\Program Files\Docker\...`), Atlas (`C:\Users\user3\go\bin\atlas.exe`), uv, cargo,
  go, protoc 35.1 (winget), Chrome (`C:\Program Files\Google\Chrome\Application\chrome.exe`), Edge.
- **WSL:** distro `Ubuntu`, WSL2, 12 cores, 15 GB RAM, 904 GB free. Present: cargo/rustc 1.95.0, uv 0.12.23, docker
  28.4 (Docker Desktop integration), git 2.43, gcc 13.3. **MISSING: go, atlas, protoc, pkg-config.**
- **protoc is a build prerequisite:** `lance`, `lance-datafusion`, `lance-encoding`, `lance-file`, `lance-index` and
  `lance-table` depend on `prost-build` (`engine/Cargo.lock`), and no `protobuf-src` / `protoc-bin-vendored` is in the
  lock. The engine has no `build.rs`; its own bindings are committed under `engine/src/pb/`.
- **The dev compose stack is running now** (`lancet-postgres`, `lancet-jaeger`, `lancet-grafana`, `lancet-loki`,
  `lancet-prometheus`, `lancet-collector`, up 31 h). The compose file pins `container_name` (e.g. `docker-compose.yml:87`
  `lancet-grafana`) and binds fixed loopback ports (e.g. `127.0.0.1:16686`, `127.0.0.1:3000`, `127.0.0.1:9090`). A
  fresh clone's `docker compose up` collides with the running stack. WSL uses the same Docker Desktop engine.
- **Grafana has no anonymous access:** `GF_SECURITY_ADMIN_USER/PASSWORD: admin` and `GF_USERS_ALLOW_SIGN_UP: "false"`
  (`docker-compose.yml:88-91`). A headless screenshot of a dashboard needs a login.
- **No `.env` loader exists** in engine, gateway or eval source (no dotenv). `OPENROUTER_API_KEY` is read from the
  process environment (`engine/src/main.rs:96-100`). `.env` is gitignored (`.gitignore:38`). D-220's "only `.env`
  supplied" therefore means the shell must export it.
- **Agent harness limits that shape plans (from memory, confirmed in 06.3.5/06.3.6):** `gsd-executor` has no Agent
  tool, no Monitor, no browser, and a 10-minute Bash cap per call; processes it launches live in its job object and die
  when it exits. `/gsd-code-review` spawns a subagent, so it is orchestrator-run, never an executor task.

## M. Decision-coverage gate (step 13a) behaviour on this phase

- `check.decision-coverage-plan <phase_dir> 06.4-CONTEXT.md` counts **29 trackable decisions: D-198..D-226**, one per
  `- **D-NNN:**` bullet. The inherited 06-CONTEXT rows in the table at the top and the cited 06.3.6 IDs are NOT counted.
- It scans only: frontmatter `must_haves` / `truths` / `objective`; bodies of `## must_haves|truths|tasks|objective`
  headings; and the bodies of `<objective>`, `<tasks>`, `<task>`, `<action>`, `<read_first>`, `<behavior>`, `<verify>`,
  `<acceptance_criteria>`, `<done>`. Prose and tables outside those regions do not count. A range like "D-198..D-205"
  counts only its endpoints, so every ID must be written out.
- D-206 (a recorded finding), D-225 (a finding) and D-226 (a ROADMAP amendment, already applied in `347001fa`) must
  still each be cited inside a scanned region, or the gate fails.
- The inherited 06-CONTEXT IDs in the table (D-02, D-03, D-04, D-06, D-09, D-17, D-32, D-45, D-66, D-67, D-68, D-69,
  D-70, D-71, D-72, D-73, D-76, D-85, D-86) are asserted by hand.

## N. v1 phase status inventory (for milestone closure)

| Phase | VERIFICATION status | Note |
|---|---|---|
| 01 | none (UAT complete, SECURITY secured) | predates VERIFICATION files |
| 02 | `complete_with_debt` | ADR-02-004 force-close |
| 03 | `gaps_found` | ADR-03-003 force-close |
| 04, 04.1, 05, 06 | `passed` | 06-UAT.md frontmatter still `status: diagnosed` although its gaps are resolved |
| 06.1 | `passed` (re-verified after gap plan 06.1-04) | STATE still lists GAP-06.1-SC2-SC3 / -SC4 as open blockers |
| 06.2 | `passed` (re-verified after 06.2-10..12; score 5/8, 3 routed to human) | STATE still lists GAP-06.2-* as open |
| 06.3 | `passed` (third pass; flagged human sign-off items) | STATE still lists GAP-06.3-* as open |
| 06.3.1, 06.3.2, 06.3.3 | `passed` | |
| 06.3.4 | `gaps_found` (7/8, 1 via override) | receives the D-208 override |
| 06.3.4.1, 06.3.5, 06.3.6 | `passed` | |

- STATE.md "Completed Phases" (`.planning/STATE.md:331-344`) omits 04.1, 6.1, 6.2, 6.3 and 06.3.1.
- REQUIREMENTS.md unchecked v1 IDs: RAG-06, DATA-01, DATA-02, DATA-03, DATA-06, DATA-07, DATA-08, DATA-09, OBS-03
  (matches D-223).

## O. Other code facts

- Goldens that render the default request (review against D-207): `engine/src/retrieval/testdata/retrieve_node_default.golden`,
  `engine/src/retrieval/testdata/graph_off_fusion.golden`, `engine/src/generation/testdata/provider_messages_default.golden`.
- **Chart analog for D-218:** `render_chart_svg` (`eval/src/lancet_eval/comparison.py:2309-2332`) renders a
  deterministic SVG 1.1 chart from chart JSON through a Jinja2 template (`chart.svg.j2`), with no plotting library.
  06.3.5's `chart.svg` was produced this way (`eval/runs/2026-10-07-heldout-multihop_rag_heldout/chart.svg`).
- Run-of-record directories (all tracked): `eval/runs/2026-10-06-drive2-multihop_rag_diag/` (report.json, report.md,
  metadata.json, gates-drive2.json, journal.jsonl, raw_events/), `eval/runs/2026-10-07-heldout-multihop_rag_heldout/`
  (+ comparison.json, chart.json, chart.svg, judged-result.json, gates-heldout.json),
  `eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/` (+ lever-comparison.json, gates-heldout.json,
  readings-status.json, report.json, report.md, metadata.json).
- `docs/` deep-dive must quote, never re-derive, numbers from these JSON files.

## P. Questions this file deliberately does NOT answer (research must)

1. Does `score --no-judge` + `report` on a temp copy of the 06.3.6 run reproduce `report.json`'s dimension values
   exactly? Which fields differ (`commit_sha`, `generated_at`, `dependency_lock_hash`, notes)? Does a shallow clone
   break the D-73 git check? Run it and keep the script and output in `research/`.
2. How long does a cold `cargo build --release` of the engine take on each platform from an empty `target/`? Can it
   run inside a 10-minute Bash call, or does it need the A / orchestrator-wait / B split?
3. Can headless Chrome or Edge capture the Jaeger trace view and the Grafana dashboard into a committed PNG from Bash
   (Grafana needs a login)? If not, which screenshots need an owner or orchestrator capture step?
4. How should the fresh-clone runs avoid the running dev stack's container names and ports (stop it and restart it,
   or a compose project override)? This changes the owner's running environment.
5. Who installs go, atlas and protoc in WSL, and how, without a system-wide change the owner has not approved?
6. Sample documents for D-221: license-clean, with `doc_title` / `source` / `published_date`.
7. The D-210 obligations grep across every phase directory, and the reconciliation of the graph-latency figures.
8. Each of the 40 open 06.3.6 ledger rows routed per D-204, plus an inventory of the J5 rows from other ledgers.

---

## Q. Corrections after research (2026-10-11)

`06.4-RESEARCH.md` "Corrections to verified-facts" lists 15 items. The orchestrator re-checked the ones marked
**re-checked** against source; the rest are taken from the research with its cited evidence.

1. **§G5 (re-checked).** `preflight.py:866` is the legacy `check_canary_floors` (graph-on/graph-off canaries), not the
   arm-mode canaries; only `:1203` is the arm-mode call. Two more direct `/rag/query` posters exist:
   `preflight.py:321` (`check_corpus_generation`, already sends `"disable_graph_context": False`) and `seed.py:317`
   (sends only the query). Both need the D-198 opt-out.
2. **§L (WSL).** `uv` lives at `~/.local/bin/uv` and is not on a non-login `bash script.sh` PATH. `libssl-dev` is needed
   with `pkg-config` (Linux `openssl-sys` via `native-tls` <- `hyper-tls` <- `reqwest` <- lance crates). `cmake` and
   `node` are also absent. The protoc need is real (`lance-table-1.0.4/build.rs:9-25`).
3. **§C4 answered.** `config.<LANCET_ENV>.toml` is a later source over `config.toml` (`engine/src/config.rs:1082-1105`);
   neither overlay defines `[engine.graph]` / `[engine.levers]`, so one key in `config.toml` covers every environment.
4. **§I (shallow clone).** Confirmed by a run: a depth-1 clone fails `score` with the D-73 message
   (`gitcheck.py:108,308`). Full clone only.
5. **§I (`metadata.json`).** The expected re-score differences are `commit_sha` and `run_date`, plus
   `dependency_lock_hash` on a CRLF (Windows `core.autocrlf=true`) checkout. `dimensions` and `result_hash` are equal.
6. **§J4.** Adding `sha2` as a direct dependency requires updating and committing `engine/Cargo.lock` in the same commit.
7. **§K.** Also stale: `go run ./gateway` fails from the repo root (`gateway/` is its own module; use
   `cd gateway && go run .`); `eval/README.md:11-15` states the pre-D-207 graph semantics; scripted
   `atlas schema apply --env local` needs `--auto-approve`; there is no `.env` or `.env.example`.
8. **§N / D-68.** `.planning/WINDOWS.md` is the "Broken Windows Ledger" (`open_count: 9`), a defect register.
9. **§N (re-checked in part).** STATE's `GAP-06.2-SC5-SC6` (Prometheus double prefix) and `GAP-06.2-SC6-EXE`
   (committed `dashboard_gen.exe`) are stale: the series are single-prefixed and no `.exe` is tracked.
10. **CONTEXT D-210 latency row (re-checked).** `06.3.6-RUN-OF-RECORD.md:169-170`: `hybrid` 8301 ms total, 96.4 ms
    RetrieveHybrid, 2255 prompt tokens; `hybrid+graph` 8407 / 108.7 / 2431. The CONTEXT's +106 ms / +12 ms / +176 tokens
    are these unpaired arm-mean differences. Paired readings: research Finding 10.
11. **CONTEXT D-217 / SC-1 (re-checked).** No `info_span!`, `#[instrument]` or other span macro exists in
    `engine/src/rerank/` or `engine/src/workflow/nodes/retrieve.rs`. Resolved by D-227.
12. **CONTEXT D-03 label.** `DEBT-CR-04-EXT` is not a literal string; its record is
    `03-hybrid-retrieval-basic-rag-path/deferred-items.md:157`.
13. **New, re-checked: gateway rejects unknown JSON fields.** `dec.DisallowUnknownFields()` at `gateway/main.go:757`, so
    the D-198 field must be added to the gateway body struct or a client sending it gets HTTP 400.
14. **New, re-checked: `score` scans every record with `provenance_failures`.** `_provenance_scan`
    (`eval/src/lancet_eval/score.py:613-633`) tallies `dict.fromkeys("abcdefghij", 0)` and refuses on any code in
    `ZERO_TOLERANCE_CODES = frozenset("abcdfhj")` (`provenance.py:71`). New per-arm checks (code 24, graph state) must
    live outside that path, or the frozen runs of record could stop scoring; a new clause letter would also raise
    `KeyError` in the tally.
15. **New, re-checked: tonic nodelay.** tonic 0.14.6's own `bind_incoming` sets `.with_nodelay(Some(self.tcp_nodelay))`
    with the builder default `tcp_nodelay: true` (`tonic-0.14.6/src/transport/server/mod.rs:132,653-660`).
    `serve_with_incoming_shutdown` bypasses it, so the D-202 reorder must call `.with_nodelay(Some(true))` itself.
16. **New, re-checked: cold build time.** A cold `cargo build --release --locked` of the engine in a fresh Windows clone
    finished in 20 m 58 s (`research/cold_cargo_build.out:28`). It cannot run inside one 10-minute executor Bash call.

---

## R. After planning (2026-10-11)

- The planning-time facts above now live in the plans (`06.4-01..17-PLAN.md`); where a plan and this file differ, the
  plan's later, re-verified line wins.
- §M's trackable count is now **36** (D-198..D-233): the owner answers at plan-phase added D-227..D-233. The gate passed
  36/36 at `3dc62412`.
- Two further facts found at plan-check time: the engine's plain `tracing_subscriber::fmt::layer()`
  (`engine/src/telemetry/mod.rs:287`) prints the message and fields but never an event's `name:`, so any log token a
  consumer greps must be in the message text (D-203); `scripts/oi02-replay.ps1:487,496` call `lancet-eval run` on the
  legacy-label `multihop_rag` corpus (retired for live use by plan 06.4-03).
