# OpenCodeReview (ocr) upstream grounding notes

Source: `github.com/alibaba/open-code-review` (shallow clone, verified 2026-07; the CLI is
implemented in **Go** under `cmd/opencodereview/` + `internal/`). The clone is not kept in the
repo; re-clone when building the Stage-4 patch set.

## Commands (cmd/opencodereview/main.go)

`review` (alias `r`), `scan`, `rules check <file>`, `config provider|model|set|unset`,
`llm test`, `llm providers`, `session`, `viewer`, `version` (also `--version` / `-V`).

## `ocr review` flags (cmd/opencodereview/flags.go — exact)

| Flag | Short | Default | Notes |
|---|---|---|---|
| `--tools` | | embedded | path to JSON tools config file |
| `--rule` | | | path to JSON system-rules file |
| `--repo` | | cwd | git repo root |
| `--from` | | | source ref (merge-base mode); requires `--to` |
| `--to` | | | target ref; requires `--from` |
| `--commit` | `-c` | | single commit hash/tag (vs its parent) |
| `--resume` | | | previous review session id; incompatible with `--preview` |
| `--exclude` | | | **single comma-separated** gitignore-style pattern list (NOT repeatable) |
| `--format` | `-f` | text | `text` or `json` |
| `--concurrency` | | 8 | max concurrent file reviews |
| `--timeout` | | 10 | **per-file** task timeout in minutes |
| `--audience` | | human | `human` or `agent` |
| `--background` | `-b` | | inline context |
| `--background-file` | `-B` | | Markdown file; combined with `--background` (inline first) |
| `--model` | | | LLM model override |
| `--max-tools` | | 0 | 0 = template default; values 1-9 are clamped to 10 |
| `--max-git-procs` | | 16 | max concurrent git subprocesses |
| `--preview` | `-p` | false | file preview, no LLM |

No mode flags at all = workspace mode (staged+unstaged+untracked).
NOT present upstream (our patch set adds these): `--plan-mode`, `--plan-threshold`,
`--max-tokens`, `--template`.

## Env vars honored (internal/llm/resolver.go)

`OCR_LLM_URL`, `OCR_LLM_TOKEN`, `OCR_LLM_MODEL`, `OCR_LLM_AUTH_HEADER`,
`OCR_LLM_EXTRA_HEADERS` (format **`K=V,K=V`**, not JSON), `OCR_LLM_TIMEOUT` (integer seconds),
`OCR_LLM_PROTOCOL` (normalized; wins over `OCR_USE_ANTHROPIC` when set), `OCR_USE_ANTHROPIC`
(legacy fallback), `OCR_CONFIG_PATH` (overrides config file location).
Also falls back to `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_MODEL`.

## Config file (`~/.opencodereview/config.json`, cmd/opencodereview/config_cmd.go)

```json
{
  "provider": "anthropic",
  "model": "...",
  "providers": {"<name>": {"api_key","url","protocol","model","models","auth_header","timeout_sec","extra_body","extra_headers"}},
  "custom_providers": {"<name>": { ... same ProviderEntry ... }},
  "llm": {"url","auth_token","auth_header","model","protocol","use_anthropic","timeout_sec","extra_body","extra_headers"},
  "language": "English",
  "telemetry": {"enabled","exporter","otlp_endpoint","content_logging"},
  "mcp_servers": {"<name>": {"command","args","env","tools","setup"}}
}
```

Protocol values: `anthropic`, `openai`, `openai-responses`.
Project rules: `<repo>/.opencodereview/rule.json`; global: `~/.opencodereview/rule.json`.

## Result JSON (`ocr review --format json`, cmd/opencodereview/output.go)

```json
{
  "status": "success",
  "trace_id": "...",
  "message": "...",
  "summary": {"files_reviewed": 0, "comments": 0, "total_tokens": 0, "input_tokens": 0,
              "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "elapsed": "1m2s"},
  "tool_calls": {"total": 0, "by_tool": {"read_file": 3}},
  "comments": [ {"path","content","start_line","end_line","existing_code","suggestion_code",
                 "thinking","category","severity"} ],
  "warnings": [ {"file","message","type"} ],
  "project_summary": "...",
  "resume": {"resumed_from","reused_files","rerun_files","previous_model","current_model"},
  "session_id": "..."
}
```

Findings live under **`comments`**. `category`/`severity` are `omitempty` model output —
pass through when present, never invent (SPEC §38.16). No exit-code distinction for
"completed with warnings" — the control plane derives that from a non-empty `warnings` array.

## Preview JSON (`--preview --format json`, internal/model/preview.go)

`{"files": [{"path","status","insertions","deletions","will_review","exclude_reason"}],
 "total_insertions","total_deletions","total_files","reviewable_count","excluded_count"}`

## Session JSONL (`~/.opencodereview/sessions/<encoded-repo-path>/<session-id>.jsonl`)

Record `type` values (internal/session/persist.go): `session_start`, `review_item_done`,
`review_item_reused`, `review_item_failed`, `llm_request`, `llm_response`, `llm_error`,
`tool_call`, `session_end`. Task types (history.go): `plan_task`, `main_task`,
`memory_compression_task`, `re_location_task`, `review_filter_task`.
Usage fields: `prompt_tokens`, `completion_tokens`, `cache_read_tokens`, `cache_write_tokens`.

## Template internals (for the Stage-4 patch)

`internal/config/template/template.go`: `MAX_TOKENS` (default 58888 per spec),
`PLAN_MODE_LINE_THRESHOLD` (default 50), `MAX_TOOL_REQUEST_TIMES`, per-task timeout.
Patch targets: `--plan-mode auto|always|never`, `--plan-threshold`, `--max-tokens`,
`--template <path>`.
