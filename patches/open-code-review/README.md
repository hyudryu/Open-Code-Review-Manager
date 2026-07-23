# OpenCodeReview planning-controls patch set

Upstream: [`alibaba/open-code-review`](https://github.com/alibaba/open-code-review) (Go CLI, `ocr`).

These patches add explicit planning controls to `ocr review` so a control plane
(like this app) can configure planning per job instead of relying on the
built-in threshold behavior. See SPEC §8 (Planning Controls).

## Patches

| Patch | Description |
|---|---|
| `0001-planning-controls.patch` | Adds `--plan-mode`, `--plan-threshold`, `--max-tokens`, `--template` to `ocr review`. |

Base revision: `3355baea0e83b3be7653e6f422c83242541f77c0` (2026-07-23). The patch
is a plain unified diff with `a/`/`b/` prefixes — apply with `git apply` or
`git am` from the upstream repository root:

```bash
git clone https://github.com/alibaba/open-code-review
cd open-code-review
git apply /path/to/0001-planning-controls.patch
go build ./cmd/opencodereview
```

## What the patch does

### New flags (`cmd/opencodereview/flags.go`)

```text
--plan-mode auto|always|never   planning behavior (default "auto")
--plan-threshold <lines>        changed-line threshold for auto mode (0 = template default)
--max-tokens <n>                token budget per file (0 = template default)
--template <path>               load a complete custom task template JSON
```

Semantics (SPEC §8):

- `auto` — current upstream behavior, unchanged: the plan phase is skipped for
  files whose changed lines (`insertions + deletions`) fall below
  `PLAN_MODE_LINE_THRESHOLD` (default 50 in the embedded template).
- `always` — run the plan phase for every eligible file, regardless of size.
- `never` — skip the plan phase entirely.
- `--plan-threshold` — replaces the template's `PLAN_MODE_LINE_THRESHOLD` for
  this run.
- `--max-tokens` — replaces the template's `MAX_TOKENS` budget for this run.
- `--template` — loads a complete task template from a JSON manifest with the
  same shape as the embedded `task_template.json`. `prompt_file` references
  resolve relative to the manifest's directory (then `<dir>/prompts/`) and
  fall back to the embedded prompts, so a custom template may override only
  the prompts it changes.

Invalid values fail fast during flag parsing (`--plan-mode` outside
`auto|always|never`, negative thresholds/budgets). Template overrides are
re-validated before any LLM call.

### Implementation notes

- `internal/agent/agent.go`: `agent.Args` gains a `PlanMode` field; the
  plan-phase skip decision in `executeSubtask` switches on it. Callers that
  leave `PlanMode` empty get exactly the old `auto` behavior.
- `internal/config/template/template.go`: prompt resolution is refactored
  behind a `promptReader` so `LoadDefault()` (embedded) and the new
  `LoadFromFile(path)` share one manifest→template code path.
- `cmd/opencodereview/review_cmd.go`: `applyPlanningOverrides` applies the
  template overrides after `loadCommonContext` and re-runs `Validate()`.

The patch is deliberately minimal and additive: no existing flag, default, or
code path changes when the new flags are not used, which keeps it
upstream-friendly.

## Capability detection

The control plane's `OCRAdapter` never assumes these flags exist. It parses
`ocr review --help`; the capabilities `plan_mode`, `plan_threshold`,
`max_tokens`, and `template_override` flip to `true` only when the flags are
observed (see `backend/app/ocr/adapter.py` and
`backend/tests/test_ocr_adapter.py`). Until a patched binary is detected, the
UI shows planning as *Automatic* and disables the controls.
