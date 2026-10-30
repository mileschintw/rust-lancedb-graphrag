# Lane 44：低價值測試刪除候選清單（供使用者審閱）

依使用者 2026-10-30 的指示（「列清單給我審」）整理。**清單上的測試一個都沒有刪。**你核准的刪除會由 coordinator
轉成後續 commit 或 issue。

- **範圍：**不是重複、但看起來價值低的測試，例如只釘實作細節、套套邏輯的 assert、或只要改名就壞但背後沒有行為的測試。
- **刻意不列：**v1.0 re-score 的 byte-identity 檢查，以及 fail-closed 拒絕測試。
- **如何找到：**先用 grep 啟發式搜尋，再由 subagent 逐一開檔確認（`hasattr`、`inspect.getsource`、讀原始碼字串再比對、
  `ast.parse`、只有三行以下且不呼叫產品程式的測試；Rust 的 `include_str!` 與 `assert_eq!(CONST, 字面值)`）。
- **守護來源：**守護的 D-ID 或 issue 取自 docstring，沒有寫的就用 `git blame` / `git log -S` 追引入的 commit。
- **抽查：**我（lane 44）抽查了其中 5 列，與原始碼相符（`test_the_stage_label_is_heldout`、
  `test_dropped_node_timings_stamped_on_measurement_record`、`test_resolve_raises_the_gitcheck_error_type`、
  `the_attempt_count_is_one_try_plus_one_retry`、`test_privacy_node_is_absent_from_verification`）。
- **覆蓋程度：**Rust 只跑了啟發式搜尋，沒有逐一看行為測試，所以 Rust 的覆蓋比 Python 薄。

## 建議刪除（19）

| 測試 ID | 為何價值低 | 會失去的守護 | 建議 |
|---|---|---|---|
| `eval/tests/test_score_judged_store_arms.py::test_the_unused_arm_slug_table_is_gone` | 只斷言私有符號不存在（`not hasattr(cmp_mod, "_ARM_SLUGS")`），沒有行為依賴它。（本 lane 已把它從 `test_compare_store_arms.py` 搬過來，內容未改。） | #34（commit 5001e24d） | 刪除 |
| `eval/tests/test_dev_reads.py::test_the_module_names_the_three_command_words` | 只用 `inspect.getsource` 檢查三個字串出現在模組原始碼；下一個測試已經實際驅動 CLI。 | D-152（06.3.6-10, fc207fff） | 刪除 |
| `eval/tests/test_stack_preflight.py::test_d200_stack_preflight_docstring_states_the_request_count` | 斷言函式 docstring 含「27」與「nine arms」，是文件文字，不是行為。 | D-200（06.4-04, 1275c695） | 刪除 |
| `eval/tests/test_run_arms.py::test_d198_direct_drive_still_accepts_legacy_labels_for_offline_callers` | 斷言某個 helper 名稱不出現在 `drive()` 原始碼；改名或包一層就會誤判。 | D-198（06.4-03, 7dbf42ca） | 刪除，或改成用舊標籤實際呼叫 `drive()` |
| `eval/tests/test_measure.py::test_run_measurement_pass_summary_keeps_existing_keys` | 在 `run_measurement_pass` 原始碼裡比對帶引號的 key 名稱，而不是檢查它回傳的 summary。 | 查無（06.3.3-05, 396eb833） | 刪除，或改寫成檢查回傳的 summary |
| `eval/tests/test_measure.py::test_run_measurement_pass_calibration_note_matches_derivation_contract` | 用原始碼文字比對釘住一段給人讀的說明文字。 | 查無（06.3.3 WR-03 review fix, 7ec805bd） | 刪除 |
| `eval/tests/test_measure.py::test_dropped_node_timings_stamped_on_measurement_record` | 建一個 `dropped_node_timings=3` 的 pydantic model 再讀回 3，只測到 pydantic。 | 查無（06.3.3-01, c4607150） | 刪除 |
| `eval/tests/test_path_health.py::test_shared_retrieval_percentile_pair_in_one_place` | 數 `score.py` 原始碼裡 `percentile(` 出現幾次並檢查參數名；改名或別名就壞。 | 查無（06.3.2-02, e8195088） | 刪除 |
| `eval/tests/test_score_deterministic.py::test_score_module_no_longer_hardcodes_the_two_legacy_arms` | 檢查已移除的字面值不在原始碼中，另含套套邏輯的 `ast.parse(source)`；同檔已有 registry 分組的行為測試。 | 查無（06.3.5-06, ac531c40） | 刪除 |
| `eval/tests/test_dimensions.py::test_in02_graph_yield_investigation_floor_relocated` | 釘住常數搬家後的 re-export（`G.X is T.X`）；0.20 這個值已由 `test_gate.py::test_graph_yield_investigation_floor_is_not_amended_by_drive_2` 釘住。 | 查無（06.3.4-09, 37f1c5aa） | 刪除 |
| `eval/tests/test_comparison.py::test_the_fwer_statement_and_the_approximation_label_are_planned` | 第二個 assert 拿常數比對測試檔裡手抄的同一字串；第一個是固定常數的子字串檢查。 | commit 提到 D-121/D-122/D-124（06.3.5-13, 5799b818），但測試沒有實際檢驗它們 | 刪除 |
| `eval/tests/test_comparison.py::test_the_sidecar_list_names_all_four_files` | 釘住私有 4-tuple 的字面值；`test_score_judged_store_arms.py` 的拒絕測試已檢查磁碟上真正的四個檔名。 | 查無（06.3.5-13, 4d98f68c） | 刪除 |
| `eval/tests/test_heldout_gates.py::test_the_stage_label_is_heldout` | 斷言 `HELDOUT_STAGE == "heldout"`，等於把賦值再寫一次。 | 查無（06.3.5-09, 1074890e） | 刪除 |
| `eval/tests/test_preregistration.py::test_resolve_raises_the_gitcheck_error_type` | 只斷言 re-export 別名（`PreregistrationError is gitcheck.PreregistrationError`）；名稱寫 resolve，卻沒呼叫任何 `resolve`。 | 查無（06.3.6-07, ab9e41ec） | 刪除 |
| `eval/tests/test_preflight_canary.py::test_canary_manifest_counts_are_named_constants` | `hasattr` 加上 8 與 7 的字面值；拒絕測試與 committed 檔案測試（`len(rows) == 8`、7 個不同 ID）已強制這些數量。 | D-80（docstring）、D-94（commit 5fabaf53） | 刪除 |
| `eval/tests/test_quickstart_script.py::test_d221_script_imports_run_query_from_the_harness_client` | 在腳本原始碼裡比對一行 import 和「traceparent」這個字。 | D-221（06.4-05, 633d6b99） | 刪除；若 quickstart 沒有其他 traceparent 的行為測試則保留 |
| `scripts/test_phase02_live_evidence.py::Phase02LiveEvidenceTests::test_privacy_node_is_absent_from_verification` | 測的對象已經不存在：斷言一個已刪除的 `.cjs` 檔仍不存在，以及 `verify-live-evidence.sh` 沒提到「node」。 | 查無（02-21, 7efdb7e7） | 刪除 |
| `engine/src/tests/telemetry_metrics.rs::telemetry_metrics_query_duration_outcome_set_is_exactly_two` | 對兩個元素的陣列字面值做 `len() == 2` 是套套邏輯；其餘只是釘兩個字串常數。 | 查無（06.2-05, 21fc04c6） | 刪除，或把兩個字面值 assert 併入 exporter 測試 |
| `engine/src/tests/query_embedding_retry.rs::the_attempt_count_is_one_try_plus_one_retry` | 釘住 `QUERY_EMBEDDING_ATTEMPTS == 2`；`two_timeouts_fail_the_node_with_the_existing_timeout_error` 已斷言剛好兩次呼叫。 | D-152（06.3.6-06, 35c2ab0a） | 刪除 |

其中 4 列寫的是「刪除，或改寫／保留」，由你決定。

## 建議保留但修整（4）

| 測試 ID | 問題 | 守護 | 建議 |
|---|---|---|---|
| `eval/tests/test_measure.py::test_workflow_node_order_constant_and_runner_verification` | 只釘 node 順序 tuple 的字面值；docstring 說它檢查 `runner.rs`，實際沒讀。 | 查無（06.3.3-01） | 保留；這個順序是跨語言契約，最好改寫成與 `runner.rs` 比對 |
| `eval/tests/test_lever_comparison.py::test_a_pairwise_population_comes_from_build_p4` | 有一行套套邏輯的 `assert p4_mod.build_p4`，其餘檢查真正的配對輸出。 | D-73（06.3.6-10, ef11a541） | 保留，刪掉那一行 |
| `eval/tests/test_preregistration.py::test_the_v1_0_constants_declare_no_external_pipeline` | `assert not hasattr(pre, "external_pipelines")` 只釘屬性不存在；`external_pipelines_of(...) == {}` 才是真正的檢查。 | D-247/D-250、#12（3dac24c7） | 保留，刪掉 `hasattr` 那一行 |
| `engine/src/tests/ingest_metadata.rs::the_rebuild_path_attaches_a_freshly_scanned_map` | 原始碼順序檢查以一行註解（`// Swap under a short write lock`）為錨點，改註解就壞。 | 查無（06.3.6-14, 305ec472） | 保留；順序不變式是真的，但錨點應改成程式碼 |

## 刻意不列入的類別

- **屬於拒絕、隔離或「絕不做 X」守護的原始碼掃描：**
  - AST 檢查模組絕不 import 某物（`test_metrics`、`test_retro_*`、`test_compare_rescore`、`test_comparison`、
    `test_judge_stage`、`test_paper_text_crosscheck`）；
  - `test_unpark_gates`、`test_heldout_gates` 的舊字面值 AST 檢查；
  - `test_lever_comparison` 的 judged-result 檔名守護；
  - `test_arms::test_no_deferred_d116_label_in_the_harness_source`；
  - `test_journal::test_no_pydantic_exclusion_flags_in_journal`（保護 journal 的 byte-identity）；
  - Rust 的「絕不呼叫 / 絕不 spawn」檢查。
- **與 re-score 相鄰：**`test_drive_environment::test_d199_explicit_field_checks_stay_out_of_the_score_path`。
- **跨語言一致性檢查：**比對 Python 與 Rust 原始碼或 config，能抓到真正的漂移。
- **預先登錄的門檻字面值**（`test_gate.py` 的 `*_committed*` 等）：釘住它們本來就是目的。
- **沒有其他地方釘住的 wire 或序列化值。**

## 不在本清單：已處理的重複

真正的重複屬於 issue #44 的第 3 項，已在本 lane 合併，列在 PR body 的對照表：

- `TestCollectorUnavailableKeepsConsole`：只是呼叫 `TestCollectorUnavailable`，已移除，telemetry floor 12 → 11。
- drive2 re-score：兩個測試合併成一個。
- #34 的 compare 測試：併入 #30 的 fixture。

另外 `test_score_calibration_agreement::test_gate_constants_parity` 的 `CALIBRATION_SIZE == 12` 與
`test_preregistration` 中的一個 assert 重複。它只是單一 assert，不是整個測試，沒有處理。
