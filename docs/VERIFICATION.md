# Verification Report

Maps every acceptance criterion of SPEC §37 to automated tests
(`file::test_name`) or an explicit manual-validation note. Test suites:

- **Backend** — `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
  (163 collected: 162 passed + 1 skipped; the skip is
  `test_ocr_adapter.py::test_detect_real_binary`, which runs only when a real
  `ocr` binary is installed)
- **Frontend** — `cd frontend && npm run build` (tsc strict) and `npm test`
  (15 vitest cases across 4 files)
- **Live smoke** — `backend/.venv/Scripts/python.exe scripts/smoke.py`
  (30 checks against a real server + built frontend + fake OCR executable;
  verified 2026-07-24, all 30 passing)

## SPEC §37 criteria

| # | Criterion | Verification |
|---|---|---|
| 1 | Add a parent folder and discover multiple Git projects | `test_git_service.py::test_scan_folder_finds_nested_repos`, `::test_scan_folder_respects_depth`, `::test_scan_folder_marks_registered`; `test_api.py::test_full_happy_path`; smoke "B: folder scan finds 2 projects" |
| 2 | Add an individual Git repository | `test_git_service.py::test_validate_repo_success` (+ rejection variants); `test_api.py::test_full_happy_path`; smoke "B: project add" |
| 3 | Local and remote branches retrieved and searchable | `test_git_service.py::test_refresh_branches_kinds_and_current`, `::test_parse_for_each_ref_unit`; frontend `branch-selector.test.ts` (grouping + filtering, 5 cases) |
| 4 | Branches fetched/refreshed without restarting | `test_git_service.py::test_failed_fetch_keeps_local_refs`; `test_api.py::test_full_happy_path` (refresh-branches); smoke "B: branch refresh" |
| 5 | Providers and arbitrary custom endpoints configurable | `test_api.py::test_provider_crud_and_queue_controls`, `test_full_happy_path` (custom provider); smoke "B: provider create" |
| 6 | Models discovered or entered manually | `test_api.py::test_full_happy_path` (manual model); provider discovery covered at service level in `test_queue_runner.py` fixtures and MCP tests; manual: Providers page "Discover models" against a live endpoint (requires network — not automated) |
| 7 | Provider credentials stored securely | `test_secrets.py` (all 7: keyring/env/in-memory stores, redaction); `test_api.py::test_full_happy_path` asserts the credential never appears in any payload; smoke "B: provider payload has no secret" |
| 8 | Provider connectivity can be tested | `test_api.py::test_system_endpoints` (OCR reprobe); provider test via `ocr llm test` exercised through the fake binary in `test_queue_runner.py` environment; frontend ProvidersPage test-connection flow (manual with real OCR) |
| 9 | Reusable review profiles configure OCR behavior | `test_api.py::test_provider_crud_and_queue_controls` (create/duplicate), `::test_profile_template_path_roundtrip`; `test_queue_runner.py::test_snapshot_is_immutable_after_profile_edits` |
| 10 | Every supported OCR review flag represented or deliberately controlled | `test_ocr_adapter.py::test_build_range_command`, `::test_build_commit_command`, `::test_build_workspace_command`, `::test_additional_arguments_appended_before_forced`; profile schema covers all SPEC §8 controls; `format=json`/`audience=agent` are runner-forced |
| 11 | Planning controls reflect installed OCR capabilities | `test_ocr_adapter.py::test_capabilities_from_stock_help`, `::test_capabilities_from_patched_help`, `::test_patched_help_fixture_matches_planning_patch`, `::test_plan_flags_unsupported_on_stock`, `::test_plan_flags_emitted_when_patched`; UI disables controls when unsupported (ProfilesPage) |
| 12 | Branch and commit jobs run in isolated worktrees | `test_git_service.py::test_worktree_lifecycle`; `test_queue_runner.py::test_commit_job_completes_end_to_end`; `test_recovery.py::test_orphan_worktree_cleanup` |
| 13 | Workspace jobs preserve uncommitted changes | `test_queue_runner.py::test_workspace_jobs_serialize_on_project_lock` (per-project lock, no worktree, real path) |
| 14 | Jobs stored in a durable queue | `test_queue_service.py::test_queue_position`, `::test_clear_completed`; `test_recovery.py::test_interrupted_recovery_marks_active_jobs` (queue survives restart) |
| 15 | Queue jobs reordered, paused, cancelled, retried, resumed | `test_queue_service.py::test_move_top_up_down_is_transactional`, `::test_move_rejects_non_queued`, `::test_pause_job_and_queue`, `::test_cancel_queued_job`; `test_queue_runner.py::test_cancel_running_job_kills_process_tree`, `::test_retry_links_to_original_and_copies_snapshot`, `::test_resume_creates_session_linked_job`, `::test_resume_rejected_without_session`; frontend `queue-reorder.test.tsx` |
| 16 | Multiple jobs with different providers, no shared-config races | per-job HOME/config isolation: `test_ocr_adapter.py::test_build_job_environment`, `::test_write_job_config_excludes_secrets`, `::test_build_job_environment_strips_inherited` |
| 17 | Live progress without page refresh | `test_api.py::test_sse_resume_by_last_event_id` (SSE replay + resume); `test_queue_service.py::test_state_machine_valid_path_emits_events`; smoke "B: job events recorded" |
| 18 | OCR JSON results parsed into structured findings | `test_ocr_adapter.py::test_parse_result_json`, `::test_parse_result_json_severity_passthrough`, `::test_parse_result_json_malformed`; `test_queue_runner.py::test_commit_job_completes_end_to_end`; smoke "B: findings parsed" |
| 19 | OCR JSONL sessions can be inspected | `test_ocr_adapter.py::test_parse_session_jsonl_full`, `::test_parse_session_jsonl_incremental_partial_line`, `::test_parse_session_jsonl_missing_file`, `::test_parse_session_jsonl_skips_bad_lines`, `::test_locate_session_file`; `test_api.py::test_session_inspector_server_side_filters`; smoke "B: session q/task_type filter" |
| 20 | Findings copied individually | frontend `copy-button.test.tsx` (2 cases); finding PATCH/triage in `test_api.py::test_full_happy_path` |
| 21 | Entire reports copied and exported | `test_api.py::test_full_happy_path` (all 7 export formats); `test_queue_runner.py::test_exports_never_leak_credentials_or_reasoning`; smoke "B: export markdown" |
| 22 | MCP client lists projects and branches | `test_mcp.py::test_submit_get_findings_flow`, `::test_profiles_and_preview_tools` |
| 23 | MCP client submits a review, receives job id immediately | `test_mcp.py::test_submit_get_findings_flow` |
| 24 | MCP client retrieves status and findings | `test_mcp.py::test_submit_get_findings_flow`, `::test_cancel_and_retry_via_tools`, `::test_reorder_tool` |
| 25 | Signed webhook delivered on terminal state | `test_webhooks.py::test_delivery_success_signs_and_completes`, `::test_sign_payload_known_vector`, `::test_verify_signature_constant_time`, `::test_event_filtering_and_replay` |
| 26 | Failed webhook deliveries visible and replayable | `test_webhooks.py::test_delivery_no_retry_statuses`, `::test_delivery_retry_respects_retry_after`, `::test_delivery_network_error_schedules_retry`, `::test_next_retry_delay_schedule_and_exhaustion`, `::test_classify_status_policy`, `::test_parse_retry_after_seconds_and_http_date`, `::test_event_filtering_and_replay` |
| 27 | UI supports light and dark mode | design tokens switch via `data-theme` (frontend/src/styles); manual: toggle in Settings → Appearance renders both themes (no automated visual diff — see "Not fully verifiable" below) |
| 28 | UI is keyboard accessible | Radix primitives + semantic controls throughout; manual: keyboard walkthrough of main flows (Tab order, Enter/Space activation, focus-visible rings). Not automated |
| 29 | Interface does not look like a generic admin template | custom design system (tokens §22, CSS Modules, no component library); subjective — manual review |
| 30 | No credentials in logs, exports, previews, or browser payloads | `test_secrets.py::test_combined_store_gets_redacted_from_logs`, `::test_redact_text_key_value_pattern`; `test_security.py::test_redact_environment`; `test_queue_runner.py::test_exports_never_leak_credentials_or_reasoning`; `test_api.py::test_full_happy_path` + `::test_diagnostics_bundle`; smoke "B: export/bundle has no secret" |
| 31 | Tests cover the primary workflows | this document; 163 backend + 15 frontend cases + 30 smoke checks |
| 32 | Application runs with a single documented command | `scripts/start.sh` / `scripts/start.ps1` (README "Quickstart"); verified end-to-end by `scripts/smoke.py` which starts the real app the same way (`python -m app`) |

## Honest limitations

1. **No real `ocr` binary available** in the development/CI environment. All
   job execution is verified against a faithful fake executable (argv-driven,
   emits the real result/session JSON shapes per upstream source). The OCR
   compatibility probe, command generation, result parsing, and session
   parsing are grounded in the upstream source layout (shallow clone,
   2026-07-23, `3355baea`).
   `test_ocr_adapter.py::test_detect_real_binary` auto-runs when a real
   binary is present (skipped here). Live end-to-end **review quality** (real
   LLM output usefulness) is inherently not verifiable without a real
   provider and is out of scope.
2. **Planning-controls patch not compile-tested** — no Go toolchain in this
   environment. The patch is verified `git apply`-clean against a fresh
   upstream clone and hand-reviewed against the touched call sites; the
   adapter-side contract (help-text → capability flip) is covered by
   `test_patched_help_fixture_matches_planning_patch`.
3. **Playwright visual-regression/e2e tests are not included** (SPEC §31
   "Visual Regression" unmet). The pytest + vitest + live smoke suites cover
   functional behavior; screenshot tests for the 10 listed states remain
   future work.
4. **Model discovery and provider connection test against real endpoints**
   are exercised through fakes; a live check needs network + real provider
   credentials (manual: Providers page).
5. **Keyboard accessibility and dark mode** are verified by construction
   (Radix primitives, token-driven theming) plus manual inspection, not by
   automated a11y/visual tests.
6. **Former flaky runner test, fixed.** `test_queue_runner.py::test_commit_job_completes_end_to_end`
   intermittently missed `job.file_started`/`job.file_completed` events under
   full-suite timing. Root cause: the session tailer could be cancelled
   between advancing the parse offset and emitting the events. Fixed in
   `queue/runner.py` (the tailer is now stopped gracefully; an in-flight
   drain always completes). Two consecutive full-suite runs verified green
   after the fix.
7. **Screenshots** of major pages (SPEC §39) are not captured; the README
   has a placeholder section for them.
