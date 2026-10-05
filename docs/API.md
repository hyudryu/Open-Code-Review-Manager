# REST API

Base URL: `http://127.0.0.1:8372/api/v1` (port configurable via `OCR_CC_PORT`).
All requests/responses are JSON unless noted. Interactive docs: `/api/docs`
(Swagger UI) and `/openapi.json`. (`/docs` belongs to the in-app documentation
page.)

**Conventions**

- State-changing requests (POST/PATCH/DELETE) require the CSRF double-submit:
  read the `ocrcc_csrf` cookie set by any safe response and echo it in the
  `X-OCR-CSRF` header. Missing/mismatched → `403 csrf_failed`.
- List endpoints return `{"items": [...], "total": n, "limit": n, "offset": n}`
  and accept `limit`/`offset`.
- Errors share one envelope:

```json
{
  "error": {
    "code": "validation_failed",
    "message": "target_ref 'does-not-exist' is not a valid ref.",
    "detail": "...",
    "next_action": "Pick an existing branch or tag."
  }
}
```

Common codes: `not_found` (404), `validation_failed` (422), `conflict`
(409), `csrf_failed` (403), `unsupported_feature` (422).

## Folders

```text
GET    /folders                          list folders
POST   /folders                          {"display_name"?, "absolute_path", "scan_depth"?, "auto_discover"?} → 201 Folder
GET    /folders/{id}                     folder detail
PATCH  /folders/{id}                     partial update
DELETE /folders/{id}                     remove (projects stay)
POST   /folders/{id}/scan                discover git repos → {"repos": [{"path","name","already_registered",...}]}
POST   /folders/{id}/register            register discovered repos as projects
```

## Projects

```text
GET    /projects                         list projects
POST   /projects                         {"absolute_path", "display_name"?, "folder_id"?} → 201 Project
GET    /projects/{id}                    detail (includes branch cache freshness)
PATCH  /projects/{id}                    partial update
DELETE /projects/{id}
POST   /projects/{id}/refresh-branches   re-read local+remote refs (no restart needed)
POST   /projects/{id}/fetch              git fetch --prune, then refresh
GET    /projects/{id}/branches           [{"name","kind":"local|remote","current","sha","last_commit_at"}]
GET    /projects/{id}/pull-requests      open PRs → {"prs":[{number,title,head_ref,head_sha,
                                         base_ref,base_sha,author,updated_at,source}],
                                         "source":"api|git|none","warning"?}
                                         GitHub remotes use the REST API (optional
                                         OCR_CC_GITHUB_TOKEN env); everything else falls
                                         back to `git ls-remote refs/pull/*/head`
                                         (number + head_sha only — base chosen manually)
GET    /projects/{id}/jobs               jobs for this project (paged)
```

## Providers and models

```text
GET    /providers                        list (never includes credential material)
POST   /providers                        → 201; body below
GET    /providers/{id}
PATCH  /providers/{id}                   {"credential": null} clears the stored credential
DELETE /providers/{id}
POST   /providers/{id}/test              direct minimal ping ("Reply with exactly: hi") against the
                                         endpoint — requires ?model_id=… → {"ok","reply","elapsed_ms",
                                         "http_status","message","detail","next_action"}
POST   /providers/{id}/discover-models   query the endpoint's model list → discovered models upserted
GET    /providers/{id}/models            list models for the provider
POST   /providers/{id}/models            manual model {"model_id"} → 201
DELETE /providers/{id}/models/{model_pk}
```

```json
// POST /providers
{
  "name": "Anthropic",
  "protocol": "anthropic",              // anthropic | openai | openai-responses
  "base_url": "https://api.anthropic.com",
  "credential": "sk-…" | "env:VAR_NAME", // stored in OS keyring / resolved from env
  "auth_header": null,                   // custom auth header name
  "extra_headers": {}, "extra_body": {},
  "http_timeout_seconds": 60
}
```

Responses carry `has_credential: true|false` — never the credential or its
reference.

## Review profiles

```text
GET    /review-profiles
POST   /review-profiles                  → 201; body below
GET    /review-profiles/{id}
PATCH  /review-profiles/{id}
DELETE /review-profiles/{id}
POST   /review-profiles/{id}/duplicate   → 201 "<name> copy"
```

A profile bundles: `provider_profile_id`, `model_id`, `language`,
`concurrency`, `per_file_timeout_minutes`, `llm_http_timeout_seconds`,
`max_tools`, `max_git_processes`, `plan_mode` (`auto|always|never`),
`plan_threshold_lines`, `max_tokens`, `exclude_patterns`, `rule_file_path`,
`tools_file_path`, `background_template`, and expert `additional_arguments`.
Planning controls are validated against detected OCR capabilities at job
creation; jobs on a stock binary fall back to `auto` and are marked
accordingly.

## Jobs

```text
GET    /jobs                             filters: status, project_id, source, provider_id
POST   /jobs                             → 201 Job (status "queued"); body below
GET    /jobs/{id}                        detail incl. snapshot, generated command, findings_count
                                       ?wait_for_terminal=true&timeout_seconds=300 (1–600) blocks
                                       server-side until a terminal status or the timeout, then
                                       returns the latest detail (status may be non-terminal on timeout)
PATCH  /jobs/{id}                        {"priority"} (queued jobs only)
DELETE /jobs/{id}                        204 (running jobs must be cancelled first)
POST   /jobs/preview                     same body as create minus queue options → preview JSON
POST   /jobs/{id}/cancel                 running → cancelling → cancelled; queued → cancelled
POST   /jobs/{id}/retry                  → 201 new job linked via retry_of_job_id
POST   /jobs/{id}/resume                 → 201 new job resuming the OCR session
POST   /jobs/{id}/duplicate              → 201 copy with same inputs
POST   /jobs/{id}/move                   {"action":"top|up|down"} manual queue ordering
POST   /jobs/{id}/pause                  pause a queued job
POST   /jobs/{id}/resume-paused          unpause
GET    /jobs/{id}/events                 SSE stream (see below)
GET    /jobs/{id}/events/history         persisted events (?limit&offset)
GET    /jobs/{id}/findings               paged; filters: user_state, path, include_reasoning
GET    /jobs/{id}/findings/{finding_id}  single finding; ?include_reasoning=true for thinking
PATCH  /jobs/{id}/findings/{finding_id}  {"user_state","user_note"} (response never includes thinking)
GET    /jobs/{id}/warnings               warnings array from the OCR result
GET    /jobs/{id}/logs                   ?stream=stdout|stderr&tail_bytes=64000 (redacted)
GET    /jobs/{id}/session                raw session records; filters below
GET    /jobs/{id}/export                 ?format=md|json|csv|jsonl|txt|agent-prompt|github-summary
                                         &include_reasoning=false → file download
```

```json
// POST /jobs
{
  "project_id": "…",
  "mode": "range",                       // range | commit | workspace | pr | scan
  "base_ref": "main", "target_ref": "feature/x",   // range
  "commit_ref": "HEAD",                                 // commit
  "pr_number": 7,                                       // pr (base_ref optional —
                                         // required only when the PR base cannot be
                                         // resolved automatically; base/target SHAs
                                         // are captured immutably at queue time and
                                         // the job runs as a range review in a
                                         // detached worktree)
  "profile_id": "…",                      // optional; defaults used otherwise
  "background": "…", "background_file": "…",
  "exclude_patterns": ["dist/**"],
  "priority": 50,
  "webhook_endpoint_id": "…"              // or inline webhook_url/webhook_secret
}
```

**SSE** `GET /jobs/{id}/events` — `text/event-stream`. Replays persisted
events with id > `Last-Event-ID` (header or `?lastEventId=`), then streams
live events with 15 s keepalives. The stream closes after a terminal event
(`job.status` with `to` ∈ terminal states). Event types: `job.queued`,
`job.status`, `job.phase`, `job.file_started`, `job.file_completed`,
`job.warning`, `job.usage`, `job.model_request`, `job.summary`, `job.log`.
`job.usage` contains cumulative `input_tokens` and `output_tokens` for the
active review. `job.model_request` carries a cumulative `count` of observed
model requests; progress percentages add a small bounded credit per request
(`MICRO_STEP_FILES`/`MICRO_CAP_FILES` in `app/services/eta.py`) so the bar
moves while planning/grouping requests run before the first file completes.

**Reasoning (opt-in)** — `thinking` is `null` everywhere unless
`include_reasoning=true` is passed on the findings endpoints or the export
(SPEC §38.15).

**Session inspector filters** — `GET /jobs/{id}/session` accepts `q`
(case-insensitive substring over the raw record), `task_type` (exact match:
`plan_task`, `main_task`, `review_filter_task`, `memory_compression_task`,
`re_location_task`), and `file` (path substring). `total` reflects the
filtered count; `limit`/`offset` paginate after filtering.

## Queue

```text
GET  /queue                      {"paused": bool, "jobs": [Job…]}
POST /queue/pause                stop dispatching (running jobs finish)
POST /queue/resume
POST /queue/reorder              {"job_ids": […]} transactional reorder
POST /queue/clear-completed      remove terminal jobs → {"removed": n}
```

## Webhooks

```text
GET    /webhooks                          list (has_secret only)
POST   /webhooks                          {"name","url","secret"?,"allowed_events"?,"enabled"?} → 201
PATCH  /webhooks/{id}                     incl. {"rotate_secret": true} → returns the new secret once
DELETE /webhooks/{id}
POST   /webhooks/{id}/test                send a test delivery
GET    /webhooks/{id}/deliveries          delivery log (status, http_status, attempt, next_attempt_at)
POST   /webhook-deliveries/{id}/replay    requeue a delivery
```

Payload/signing reference: [WEBHOOKS.md](WEBHOOKS.md).

## Application / system

```text
GET  /health                       {"status":"ok","version","ocr_status"}
GET  /system/info                full diagnostics snapshot (SPEC §30)
GET  /system/ocr                 OCR detection + capabilities; "ocr_not_found" when absent
POST /system/ocr/test            force re-probe
GET  /system/mcp                 MCP server status: transport, URL, tool/resource/prompt counts
GET  /ocr/mcp-servers            MCP servers configured for the OCR review engine
GET  /ocr/mcp-servers/{name}     one OCR review-engine MCP server
PUT  /ocr/mcp-servers/{name}     create/replace (body = server config; see below)
DELETE /ocr/mcp-servers/{name}   remove from ~/.opencodereview/config.json
GET  /system/diagnostics/bundle  sanitized zip download (no credentials, no source
                                 content; log excerpts capped at 16 KB and redacted)
GET  /system/python              interpreter info
GET  /settings                   editable settings map
PATCH /settings                  {"changes": {"queue.global_concurrency": 2, …}}
```

OCR review-engine MCP server config (routes above) mirrors the upstream
`mcp_servers` map: `type` (`stdio`, default, or `remote`), `command` + `args`
(stdio), `url` + `headers` (remote), `tools` allowlist, `setup`, and `env`
(`KEY=VALUE` strings). A `stdio` server requires `command`; a `remote` server
requires `url`. These are the servers whose tools become available to the
review agent during reviews.

Editable setting keys: `queue.global_concurrency`,
`queue.per_project_concurrency`, `queue.per_provider_concurrency`,
`queue.paused`, `retention.artifact_days`, `retention.keep_worktrees`,
`webhooks.require_https`, `webhooks.allow_private_networks`,
`ocr.executable`, `git.executable`.

## MCP

`POST /mcp` — MCP Streamable HTTP endpoint (tools, resources, prompts).
See [MCP.md](MCP.md).
