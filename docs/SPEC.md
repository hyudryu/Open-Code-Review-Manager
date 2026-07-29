# OpenCodeReview Control Center

## One-Shot Implementation Specification

Build the complete application in one implementation pass. Do not divide the work into phases, MVPs, or future enhancements. Do not leave placeholder screens, mocked queue behavior, inactive controls, or settings that are not wired into the actual OpenCodeReview invocation.

The application is a local-first web control plane for Alibaba OpenCodeReview.

It must allow a user to:

- Register folders containing multiple Git projects.
- Register individual Git repositories.
- Discover and refresh all local and remote branches.
- Configure LLM providers, endpoints, models, credentials, and provider-specific request options.
- Create reusable review profiles containing every supported OCR option.
- Submit workspace, branch-range, and commit reviews.
- Manage a durable review queue.
- Watch live review progress.
- Inspect findings, warnings, logs, token usage, and OCR session traces.
- Copy or export findings with one action.
- Submit and manage reviews through an MCP server.
- Deliver signed webhook callbacks when reviews complete or fail.

The interface must feel intentionally designed and professionally engineered. It must not resemble a generic admin dashboard, a default component-library demo, or an AI-generated collection of cards.

---

# 1. Product Principles

1. **OpenCodeReview remains the review engine.**  
   Do not reimplement its diff parsing, filtering, rules, planning loop, tool execution, comment collection, or session logic.

2. **The GUI is the control plane.**  
   It manages projects, branches, providers, profiles, jobs, worktrees, queue state, results, exports, MCP requests, and webhook deliveries.

3. **Every control must be real.**  
   A setting shown in the interface must either map to an OCR CLI flag, OCR configuration value, generated task-template override, or an explicitly documented control-plane behavior.

4. **Every job is reproducible.**  
   Persist the resolved provider, model, settings, refs, generated command, OCR version, and output artifacts used for each run.

5. **Concurrent jobs must be isolated.**  
   Never mutate a single shared OCR configuration while jobs are running.

6. **The application is local-first and privacy-conscious.**  
   Source code, OCR session transcripts, credentials, and findings remain on the host unless the user explicitly configures an external provider or webhook.

---

# 2. Technology Stack

## Backend

Use:

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- Alembic
- SQLite in WAL mode by default
- PostgreSQL-compatible database models
- `asyncio.create_subprocess_exec` for Git and OCR processes
- Server-Sent Events for live job events
- Official Python MCP SDK where practical
- Native operating-system credential storage through Python `keyring`
- Structured JSON logging
- `httpx` for provider model discovery and webhook delivery

Do not use shell command strings. Every Git and OCR process must be executed as an argument array.

Correct:

```python
await asyncio.create_subprocess_exec(
    ocr_binary,
    "review",
    "--repo",
    repo_path,
    "--from",
    base_ref,
    "--to",
    target_ref,
    "--format",
    "json",
    "--audience",
    "human",
)
```

Incorrect:

```python
subprocess.run(f"ocr review {user_input}", shell=True)
```

## Frontend

Use:

- React
- TypeScript with strict mode
- Vite
- React Router
- TanStack Query
- Zustand only for temporary interface state
- React Hook Form
- Zod
- Radix Primitives or React Aria for accessible behavior
- Custom CSS variables and CSS Modules
- Monaco only where code or raw JSON editing genuinely requires it

Do not construct the interface primarily from pre-styled component-library components. Unstyled primitives are acceptable, but the visual system must be original.

## Production Packaging

In production:

- Build the React frontend into static assets.
- Serve those assets from FastAPI.
- Run the entire application with one command.
- Run database migrations automatically.
- Start the queue worker and MCP server with the application.
- Support Windows, macOS, and Linux paths.
- Detect the `ocr` executable automatically.
- Allow the user to select a custom OCR executable.
- Include an application health check and OCR compatibility check.

Docker may be supported for server deployments, but it must not be the primary local installation because the application needs direct access to host Git repositories, credentials, and worktrees.

---

# 3. System Architecture

```text
React Web Application
        │
        ├── REST API
        ├── Server-Sent Events
        └── MCP Streamable HTTP
                │
          FastAPI Control Plane
                │
        ┌───────┼───────────────┐
        │       │               │
 Project   Durable Queue    MCP/Webhooks
 Manager      Worker
        │       │
        │    OCR Runner
        │       │
        ├── Git worktrees
        ├── Isolated job HOME
        ├── Per-job OCR config
        ├── Per-job task template
        ├── OCR JSON result
        └── OCR JSONL session trace
```

The Python backend owns all orchestration. The React application must never invoke Git or OCR directly.

---

# 4. Core Domain Model

## Folder

Represents a user-added parent directory that may contain one or more Git repositories.

Fields:

```text
id
display_name
absolute_path
scan_depth
auto_discover
created_at
updated_at
last_scanned_at
```

Folder scanning must:

1. Resolve and normalize the path.
2. Search for Git repositories up to the configured depth.
3. Detect both `.git` directories and Git worktree `.git` files.
4. Resolve each repository’s actual top-level path.
5. Deduplicate repositories already registered.
6. Show a preview before adding all discovered projects.
7. Avoid symbolic-link loops.
8. Skip known heavy or irrelevant directories.

Default excluded folder names:

```text
node_modules
.venv
venv
dist
build
target
vendor
.git
.cache
.next
.nuxt
coverage
```

The default scan depth should be two directory levels.

## Project

Fields:

```text
id
folder_id
display_name
absolute_path
git_common_dir
default_branch
remote_name
remote_url
current_branch
is_dirty
is_available
last_branch_refresh_at
created_at
updated_at
```

A project can exist without a parent Folder.

## Branch Cache

Fields:

```text
id
project_id
name
full_ref
kind
remote_name
commit_sha
commit_subject
commit_timestamp
is_default
is_current
last_seen_at
```

`kind` is one of:

```text
local
remote
tag
```

The cache improves interface performance but is not authoritative. Validate refs again when a job starts.

## Provider Profile

Fields:

```text
id
name
provider_type
protocol
base_url
credential_reference
auth_header
http_timeout_seconds
extra_headers_json
extra_body_json
model_discovery_mode
enabled
created_at
updated_at
```

Supported protocols:

```text
openai
openai-responses
anthropic
```

## Model

Fields:

```text
id
provider_profile_id
model_id
display_name
context_length
supports_tools
is_manual
is_enabled
last_discovered_at
```

## Review Profile

A reusable configuration preset.

Fields:

```text
id
name
description
provider_profile_id
model_id
language
concurrency
per_file_timeout_minutes
llm_http_timeout_seconds
max_tools
max_git_processes
plan_mode
plan_threshold_lines
max_tokens
exclude_patterns
rule_file_path
tools_file_path
background_template
additional_arguments
created_at
updated_at
```

## Review Job

Fields:

```text
id
project_id
profile_id
source
mode
base_ref
target_ref
commit_ref
workspace_path
priority
queue_position
status
status_message
configuration_snapshot_json
generated_command_json
ocr_version
ocr_session_id
worktree_path
job_home_path
process_id
exit_code
stdout_path
stderr_path
result_json_path
queued_at
started_at
completed_at
cancel_requested_at
```

`source` is one of:

```text
web
mcp
api
retry
```

`mode` is one of:

```text
range
commit
workspace
```

`status` is one of:

```text
queued
preparing
running
cancelling
completed
completed_with_warnings
failed
cancelled
interrupted
```

## Finding

Fields:

```text
id
job_id
path
content
start_line
end_line
existing_code
suggestion_code
thinking
user_state
user_note
created_at
```

`user_state` is one of:

```text
unreviewed
accepted
dismissed
needs_followup
```

Do not invent severity values when OCR does not provide one.

## Webhook Endpoint

Fields:

```text
id
name
url
secret_reference
allowed_events
enabled
last_delivery_at
created_at
updated_at
```

## Webhook Delivery

Fields:

```text
id
endpoint_id
job_id
event_type
delivery_id
attempt
status
http_status
response_excerpt
next_attempt_at
created_at
completed_at
```

---

# 5. Project and Folder Management

## Adding a Folder

The Add Folder flow must:

1. Accept an absolute directory path.
2. Validate that it exists and is readable.
3. Scan for Git repositories.
4. Present the discovered repository list.
5. Allow individual repositories to be excluded.
6. Add the selected projects.
7. Immediately retrieve branch information.

Do not rely on an HTML folder picker alone. Browsers may not expose arbitrary host paths reliably.

Provide:

- A native path entry field.
- A Browse button when an optional desktop/native bridge is available.
- Clear validation and path normalization.
- Recently used paths.
- A scan-depth selector.
- A scan preview before saving.

## Adding a Project

The Add Project flow must accept a direct repository path and validate it with Git.

Collect data using commands equivalent to:

```bash
git rev-parse --show-toplevel
git rev-parse --git-common-dir
git remote -v
git symbolic-ref --short HEAD
git status --porcelain
git remote show origin
```

The application must reject:

- Paths that do not exist.
- Paths that are not Git work trees.
- Bare repositories for review execution.
- Duplicate project paths.
- Repositories whose resolved top-level path is outside configured allowed roots when path restrictions are enabled.

## Project Detail

Each project detail page must show:

- Project name and path.
- Remote URL.
- Current branch.
- Default branch.
- Dirty or clean state.
- Last branch refresh.
- Local branches.
- Remote branches.
- Recent review jobs.
- Default review profile.
- Project-level rule file.
- Project-level exclude patterns.

Actions:

- Start Review.
- Refresh Branches.
- Fetch Remote.
- Open Folder.
- Copy Path.
- Edit Project.
- Remove Project.
- View History.

Removing a project must not delete the Git repository.

---

# 6. Branch Discovery

On initial project registration and every manual refresh, run the equivalent of:

```bash
git for-each-ref \
  --format="%(refname)|%(objectname)|%(subject)|%(committerdate:iso-strict)" \
  refs/heads refs/remotes refs/tags
```

Also determine:

- Current branch.
- Default remote branch.
- Detached HEAD state.
- Branch tracking relationships.
- Whether local and remote refs share the same commit.
- Whether each selected ref resolves to a commit.

Do not use `git branch` output parsing intended for humans.

## Refresh Behavior

Support:

- Refresh from local refs only.
- Fetch and refresh.
- Prune remote refs.
- Automatic refresh when opening a project.
- Optional periodic refresh.
- Configurable fetch timeout.

A failed fetch must not erase the existing branch cache.

## Branch Selector

The branch selector must:

- Search by branch name.
- Group Local, Remote, and Tags.
- Show commit subject and relative timestamp.
- Mark the current and default branches.
- Avoid duplicate-looking refs by showing full ref context when needed.
- Support keyboard navigation.
- Never silently select a branch after a failed refresh.

---

# 7. Review Creation

The New Review interface must support three modes.

## Range Review

Inputs:

```text
Project
Base branch/ref
Target branch/ref
Review profile
Optional background context
Optional rule override
Optional exclude overrides
Priority
Webhook endpoint
```

Generated OCR mode:

```bash
ocr review --repo <worktree> --from <base> --to <target>
```

Use the exact target commit SHA captured when the job is created or prepared. Do not allow a moving branch to silently change the review after the user has queued it.

## Commit Review

Inputs:

```text
Project
Commit SHA/ref
Review profile
Optional background context
Optional rule override
Optional excludes
Priority
Webhook endpoint
```

Generated OCR mode:

```bash
ocr review --repo <worktree> --commit <commit>
```

## Workspace Review

Inputs:

```text
Project
Review profile
Optional background context
Optional rule override
Optional excludes
Priority
Webhook endpoint
```

Workspace mode reviews the selected project’s current staged, unstaged, and untracked changes.

Workspace jobs must not use a clean worktree because that would remove the user’s uncommitted changes. They must run against the real project path and obtain a per-project exclusive lock.

The interface must warn that workspace results represent the working state at execution time unless a snapshot strategy is enabled.

## Preview

Add a Preview Files action using OCR preview behavior.

Preview must show:

- Included files.
- Excluded files.
- Exclusion reason.
- Added, modified, renamed, or deleted state.
- Estimated review count.

Preview must not call the LLM.

## Background Context

Support:

- Inline Markdown.
- A Markdown file path.
- Project default context.
- Profile default context.
- Job-specific context.

Show the final merged context before submission.

---

# 8. Complete OCR Setting Coverage

The GUI must expose all supported review controls.

## Standard Review Controls

```text
Repository
From ref
To ref
Commit
Resume session
Preview
Output format
Audience
Background
Background file
Concurrency
Per-file timeout
Rule file
Exclude patterns
Max tools
Model override
Max Git processes
Tools configuration file
```

For GUI jobs, force:

```text
format = json
audience = human
```

These can be displayed in Advanced Settings but should not normally be changed. JSON keeps the terminal result structured, while the human audience supplies the progress lines shown in the live log.

## Provider Controls

Expose:

```text
Provider type
Protocol
Base URL
API key/token
Auth header
Model
HTTP request timeout
Extra headers
Extra body
Connection test
Model discovery
```

Built-in provider presets may be preloaded, but users must also be able to create arbitrary custom providers.

## Planning Controls

OCR currently plans automatically for files that meet its plan threshold. Implement a small compatibility patch to OCR so the control plane can explicitly configure planning.

Add upstream-friendly OCR options:

```text
--plan-mode auto|always|never
--plan-threshold <changed-lines>
--max-tokens <tokens>
--template <path>
```

Required behavior:

- `auto`: use threshold behavior.
- `always`: run planning for every eligible file.
- `never`: skip planning.
- `--plan-threshold`: replace the template threshold for the job.
- `--max-tokens`: replace the template token budget for the job.
- `--template`: load a complete custom task template from a path.

Until the patched OCR binary is detected, the GUI must:

- Show planning as `Automatic`.
- Explain that the installed OCR version controls the threshold internally.
- Disable unsupported controls.
- Never pretend that a disabled setting was applied.

## Additional Arguments

Provide an expert-only additional-arguments field, but:

- Parse it into an array.
- Reject shell metacharacter interpretation.
- Reject arguments that conflict with control-plane-owned values.
- Show the final command array before submission.
- Mark jobs using custom arguments.

---

# 9. Provider and Model Management

## Provider Presets

Preload definitions for the built-in OCR provider types, while allowing edits and custom providers.

Examples include:

```text
Anthropic
OpenAI
DashScope
DeepSeek
Kimi
MiniMax
Z.ai
Volcengine
Tencent
Baidu Qianfan
Local OpenAI-compatible
Custom Anthropic-compatible
Custom OpenAI Responses-compatible
```

Do not hardcode the model list as the only allowed values.

## Model Discovery

For OpenAI-compatible providers:

```http
GET {base_url}/models
Authorization: Bearer <token>
```

Normalize IDs from the response.

For providers without compatible discovery:

- Allow manual model IDs.
- Allow provider-specific adapters.
- Clearly label manually entered models.

Store discovery failures with actionable error details.

## Connection Test

The Test Connection action must:

1. Resolve the selected provider and model.
2. Build an isolated OCR configuration.
3. Run `ocr llm test` under that configuration.
4. Capture stdout, stderr, elapsed time, and exit code.
5. Return a structured success or failure result.

Do not expose API keys in logs, command previews, database rows, browser payloads, or exports.

## Credential Storage

Store credentials through an abstraction.

Default implementation:

- Windows Credential Manager.
- macOS Keychain.
- Secret Service/keyring on Linux.

Database rows store only the credential reference.

Allow environment-variable references for headless deployments.

---

# 10. Per-Job OCR Isolation

OCR normally reads configuration and sessions from the user’s home directory. The queue must not rewrite a shared global config when jobs use different providers.

For each job, create:

```text
<data_dir>/jobs/<job-id>/
├── home/
│   └── .opencodereview/
│       ├── config.json
│       └── sessions/
├── template/
├── stdout.log
├── stderr.log
├── result.json
└── metadata.json
```

Launch OCR with a job-specific environment:

```text
HOME=<job-home>                 # Linux/macOS
USERPROFILE=<job-home>          # Windows
OCR_LLM_URL=<resolved-url>
OCR_LLM_TOKEN=<secret>
OCR_LLM_MODEL=<model>
OCR_LLM_PROTOCOL=<protocol>
OCR_LLM_TIMEOUT=<seconds>
OCR_LLM_AUTH_HEADER=<optional>
OCR_LLM_EXTRA_HEADERS=<optional-json>
```

Also write a compatible per-job OCR config file for settings that are not expressible through environment variables.

Environment values and secrets must never be written to the application logs.

After completion:

- Parse `result.json`.
- Locate the OCR session JSONL.
- Record the OCR session ID.
- Keep job artifacts according to retention settings.
- Redact credentials from metadata.

---

# 11. Worktree Isolation

## Range and Commit Jobs

Range and commit reviews must run in isolated detached Git worktrees.

Recommended layout:

```text
<data_dir>/worktrees/<project-id>/<job-id>/
```

Process:

1. Resolve the selected refs to immutable commit SHAs.
2. Create a detached worktree at the target commit.
3. Validate the base and target refs.
4. Run OCR with the intended range or commit.
5. Remove the worktree after completion unless retention is enabled.
6. Run `git worktree prune` when needed.

Use a per-project lock only while creating or removing worktrees. Separate worktrees may then run concurrently.

## Workspace Jobs

Workspace reviews run against the original project path.

Rules:

- Only one workspace job per project may run at a time.
- Range and commit jobs may continue in independent worktrees.
- Display the current dirty-state fingerprint when queued.
- Display a warning when the workspace changes before execution.
- Allow the user to cancel or run against the latest workspace state.

## Cleanup

On startup:

- Mark jobs left in `preparing`, `running`, or `cancelling` as `interrupted`.
- Detect orphan worktrees.
- Offer safe cleanup.
- Never delete a directory that is not recorded as an application-created worktree.
- Never run destructive Git reset or clean commands on a user repository.

---

# 12. Durable Queue

The queue is a core product feature, not an in-memory task list.

## Queue Behavior

Support:

- Configurable global worker count.
- Per-project concurrency limits.
- Provider concurrency limits.
- Job priority.
- Manual ordering.
- Pause queue.
- Resume queue.
- Pause individual queued jobs.
- Move to top.
- Move up or down.
- Cancel queued jobs.
- Cancel running jobs.
- Retry failed jobs.
- Duplicate jobs.
- Resume compatible OCR sessions.
- Clear completed jobs.
- Filter by status, project, provider, model, and source.

Default:

```text
Global concurrent jobs: 1
```

OCR itself already performs per-file concurrency. Running many OCR processes simultaneously can overload the provider or local inference server, so process-level concurrency must be conservative.

## Queue Ordering

Use:

```text
priority DESC
manual_position ASC
queued_at ASC
```

Reordering must be transactional.

## Cancellation

Cancellation flow:

1. Set `cancel_requested_at`.
2. Mark the job `cancelling`.
3. Send a graceful termination signal to the OCR process group.
4. Wait a configurable grace period.
5. Force-kill the process tree when necessary.
6. Preserve partial logs and OCR session artifacts.
7. Mark the job `cancelled`.

Windows and POSIX process-tree handling must both be implemented.

## Retry

Retry creates a new job linked to the original.

It must copy the original immutable configuration snapshot and allow the user to edit it before resubmission.

## Resume

Where OCR supports session resume:

- Show resumable sessions.
- Validate that mode and refs match.
- Create a new queued job with the prior session ID.
- Show reused and rerun file counts after completion.

---

# 13. Job State Machine

Allowed transitions:

```text
queued -> preparing
queued -> cancelled

preparing -> running
preparing -> failed
preparing -> cancelled

running -> completed
running -> completed_with_warnings
running -> failed
running -> cancelling
running -> interrupted

cancelling -> cancelled
cancelling -> failed

failed -> queued via retry
interrupted -> queued via retry or resume
```

Reject invalid transitions at the service layer.

Every transition must emit a persisted job event.

---

# 14. Live Progress

Use Server-Sent Events.

Endpoint:

```text
GET /api/jobs/{job_id}/events
```

Event types:

```text
job.status
job.log
job.phase
job.file_started
job.file_completed
job.warning
job.finding
job.summary
job.completed
job.failed
job.cancelled
```

OCR JSON output may only become complete at process exit. To provide live progress:

1. Stream stderr and any progress output.
2. Tail the job-specific OCR JSONL session file.
3. Parse append-only session records incrementally.
4. Convert records into normalized job events.
5. Persist meaningful events.
6. Avoid persisting every terminal repaint or duplicate line.

The UI must reconnect using event IDs and recover missed persisted events.

Do not use aggressive polling while an SSE connection is active.

---

# 15. Results Experience

## Results Header

Show:

- Project.
- Review mode.
- Base and target refs or commit.
- Provider and model.
- Final status.
- Files reviewed.
- Finding count.
- Warning count.
- Input tokens.
- Output tokens.
- Cache-read and cache-write tokens when present.
- Total tokens.
- Duration.
- OCR version.
- OCR session ID.
- Queue wait time.

## Finding List

Each finding must show:

- File path.
- Line range.
- Finding text.
- Existing code.
- Suggested replacement.
- Optional reasoning.
- User state.
- Copy actions.

Actions:

- Copy Finding.
- Copy Existing Code.
- Copy Suggested Code.
- Copy File and Line.
- Mark Accepted.
- Dismiss.
- Mark Needs Follow-up.
- Add Note.
- Open File.
- Expand Reasoning.

Do not expose raw reasoning by default. Place it behind an explicit disclosure control.

## File Grouping

Group findings by file.

Display:

- Finding count.
- File path.
- Added/deleted line summary when available.
- Anchored versus unanchored findings.
- Warnings associated with the file.

## Warnings

Warnings must be visually distinct from findings.

Examples:

- Per-file timeout.
- Token threshold exceeded.
- Unsupported file.
- Failed sub-agent.
- Unanchored comment.
- Incomplete session.
- Provider error.

Do not silently convert warnings into successful clean reviews.

## Raw Session Inspector

Provide an advanced inspector for OCR session records:

```text
Plan task
Main task
Review filter task
Memory compression task
Re-location task
Tool calls
Token usage
Request duration
Errors
```

Support:

- Search.
- Filter by file.
- Filter by task type.
- Expand raw request or response.
- Copy JSON.
- Download original JSONL.

Large session files must be streamed or virtualized. Do not load the entire transcript into the browser at once.

---

# 16. Copy and Export

Add one-click export actions at both job and finding levels.

## Copy Formats

Support:

- Plain text.
- Markdown.
- JSON.
- Agent prompt.
- GitHub-ready review summary.

## Export Files

Support:

```text
.md
.json
.csv
.jsonl
.txt
```

## Markdown Structure

```markdown
# OpenCodeReview Findings

## Summary

- Project:
- Review:
- Model:
- Files reviewed:
- Findings:
- Duration:

## Findings

### `path/to/file.py:42-47`

Finding text.

**Existing code**

```python
...
```

**Suggested code**

```python
...
```
```

## JSON Export

Include:

```text
job metadata
resolved refs
configuration snapshot
summary
findings
warnings
session ID
timestamps
```

Never include credentials, auth headers, or unredacted provider secrets.

## Clipboard Feedback

After copying:

- Change the icon to a checkmark.
- Show `Copied`.
- Reset after approximately 1.5 seconds.
- Do not display a large toast for every small copy action.

---

# 17. MCP Server

Expose an MCP server from the same backend.

Preferred transport:

```text
Streamable HTTP
```

Optional local transport:

```text
stdio launcher
```

Recommended endpoint:

```text
/mcp
```

## MCP Tools

### `ocr_list_projects`

Returns registered projects.

Input:

```json
{
  "query": "optional search text",
  "include_unavailable": false
}
```

### `ocr_add_project`

Registers the repository at `absolute_path` and returns its project id.
Idempotent: if the repository (resolved to its git top-level) is already
registered, the existing project is returned with `already_registered: true`.
Use it to recover when another tool returns `not_found` for a project id.

Input:

```json
{
  "absolute_path": "/absolute/path/to/git/repo",
  "display_name": "optional override"
}
```

Returns:

```json
{
  "id": "uuid",
  "display_name": "repo",
  "absolute_path": "/absolute/path/to/git/repo",
  "default_branch": "main",
  "current_branch": "main",
  "is_available": true,
  "already_registered": false
}
```

### `ocr_list_branches`

Input:

```json
{
  "project_id": "uuid",
  "refresh": false,
  "fetch": false
}
```

### `ocr_list_profiles`

Returns available review profiles.

### `ocr_preview_review`

Input:

```json
{
  "project_id": "uuid",
  "mode": "range",
  "base_ref": "main",
  "target_ref": "feature/auth",
  "commit_ref": null,
  "profile_id": "uuid",
  "exclude_patterns": []
}
```

Returns included files and exclusion reasons without using the LLM.

### `ocr_submit_review`

Input:

```json
{
  "project_id": "uuid",
  "mode": "range",
  "base_ref": "main",
  "target_ref": "feature/auth",
  "commit_ref": null,
  "profile_id": "uuid",
  "background": "Review the authentication changes.",
  "priority": 50,
  "webhook_url": "https://agent.example.com/hooks/ocr",
  "webhook_secret": "optional-per-request-secret",
  "metadata": {
    "agent_run_id": "run_123"
  }
}
```

Return immediately:

```json
{
  "job_id": "uuid",
  "status": "queued",
  "queue_position": 3,
  "status_url": "/api/jobs/<job-id>",
  "result_resource": "ocr://jobs/<job-id>/result"
}
```

### `ocr_get_job`

Returns status and progress.

### `ocr_get_findings`

Returns structured findings when available.

### `ocr_cancel_job`

Requests cancellation.

### `ocr_retry_job`

Creates a retry.

### `ocr_reorder_job`

Changes queue position when the caller has permission.

## MCP Resources

Expose:

```text
ocr://projects
ocr://projects/{project_id}
ocr://projects/{project_id}/branches
ocr://jobs/{job_id}
ocr://jobs/{job_id}/result
ocr://jobs/{job_id}/findings
ocr://jobs/{job_id}/logs
```

## MCP Prompts

Optional prompts:

```text
review_branch
review_commit
review_workspace
summarize_findings
turn_findings_into_fix_plan
```

## Asynchronous Semantics

MCP submission must be asynchronous.

The caller receives a durable job ID immediately and may:

- Poll through `ocr_get_job`.
- Read the result resource.
- Subscribe through supported MCP task semantics.
- Receive the optional signed webhook.

Do not keep an MCP tool call open for the entire review.

---

# 18. Webhook Completion Delivery

Webhook callbacks complement MCP polling.

## Events

Support:

```text
review.queued
review.started
review.completed
review.completed_with_warnings
review.failed
review.cancelled
```

By default, only terminal events should be enabled.

## Payload

```json
{
  "id": "delivery_uuid",
  "event": "review.completed",
  "created_at": "2026-07-23T10:00:00Z",
  "job": {
    "id": "job_uuid",
    "source": "mcp",
    "status": "completed",
    "project_id": "project_uuid",
    "project_name": "Native-GPT",
    "mode": "range",
    "base_ref": "main",
    "target_ref": "feature/auth",
    "base_sha": "abc123",
    "target_sha": "def456",
    "provider": "local-vllm",
    "model": "qwen3.6-35b",
    "queued_at": "2026-07-23T09:55:00Z",
    "started_at": "2026-07-23T09:55:03Z",
    "completed_at": "2026-07-23T10:00:00Z"
  },
  "summary": {
    "files_reviewed": 12,
    "comments": 4,
    "warnings": 1,
    "input_tokens": 42000,
    "output_tokens": 3800,
    "total_tokens": 45800,
    "elapsed_ms": 297000
  },
  "findings": [
    {
      "path": "src/auth.py",
      "start_line": 42,
      "end_line": 47,
      "content": "Finding text",
      "existing_code": "...",
      "suggestion_code": "..."
    }
  ],
  "warnings": [],
  "metadata": {
    "agent_run_id": "run_123"
  }
}
```

## Signing

Send:

```text
X-OCR-Event
X-OCR-Delivery
X-OCR-Timestamp
X-OCR-Signature-256
```

Signature:

```text
sha256=HMAC_SHA256(secret, timestamp + "." + raw_body)
```

Validation requirements:

- Use the exact raw request body.
- Reject timestamps outside the configured replay window.
- Use constant-time signature comparison.
- Never include the secret in the payload.

## Delivery Policy

Retry failed webhook deliveries with exponential backoff and jitter.

Suggested schedule:

```text
Immediately
1 minute
5 minutes
30 minutes
2 hours
12 hours
24 hours
```

Treat any 2xx response as successful.

Do not retry:

```text
400
401
403
404
410
```

unless the user explicitly configures retry behavior.

Retry:

```text
408
409
425
429
5xx
network errors
timeouts
```

Respect `Retry-After` when present.

## Idempotency

Use the delivery UUID as an idempotency identifier.

The receiver may safely deduplicate by:

```text
X-OCR-Delivery
```

## Webhook Administration

The UI must allow users to:

- Create endpoints.
- Test endpoints.
- Select event types.
- Rotate secrets.
- Disable endpoints.
- View delivery history.
- View response status and excerpt.
- Replay a failed delivery.
- Copy a sample payload.
- Copy signature verification examples.

---

# 19. REST API

Use versioned routes.

## Folders

```text
GET    /api/v1/folders
POST   /api/v1/folders
GET    /api/v1/folders/{id}
PATCH  /api/v1/folders/{id}
DELETE /api/v1/folders/{id}
POST   /api/v1/folders/{id}/scan
```

## Projects

```text
GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/{id}
PATCH  /api/v1/projects/{id}
DELETE /api/v1/projects/{id}
POST   /api/v1/projects/{id}/refresh-branches
POST   /api/v1/projects/{id}/fetch
GET    /api/v1/projects/{id}/branches
GET    /api/v1/projects/{id}/jobs
```

## Providers and Models

```text
GET    /api/v1/providers
POST   /api/v1/providers
GET    /api/v1/providers/{id}
PATCH  /api/v1/providers/{id}
DELETE /api/v1/providers/{id}
POST   /api/v1/providers/{id}/test
POST   /api/v1/providers/{id}/discover-models
GET    /api/v1/providers/{id}/models
```

## Review Profiles

```text
GET    /api/v1/review-profiles
POST   /api/v1/review-profiles
GET    /api/v1/review-profiles/{id}
PATCH  /api/v1/review-profiles/{id}
DELETE /api/v1/review-profiles/{id}
POST   /api/v1/review-profiles/{id}/duplicate
```

## Jobs

```text
GET    /api/v1/jobs
POST   /api/v1/jobs
GET    /api/v1/jobs/{id}
PATCH  /api/v1/jobs/{id}
DELETE /api/v1/jobs/{id}
POST   /api/v1/jobs/preview
POST   /api/v1/jobs/{id}/cancel
POST   /api/v1/jobs/{id}/retry
POST   /api/v1/jobs/{id}/resume
POST   /api/v1/jobs/{id}/move
GET    /api/v1/jobs/{id}/events
GET    /api/v1/jobs/{id}/findings
GET    /api/v1/jobs/{id}/warnings
GET    /api/v1/jobs/{id}/logs
GET    /api/v1/jobs/{id}/session
GET    /api/v1/jobs/{id}/export
```

## Queue

```text
GET  /api/v1/queue
POST /api/v1/queue/pause
POST /api/v1/queue/resume
POST /api/v1/queue/reorder
```

## Webhooks

```text
GET    /api/v1/webhooks
POST   /api/v1/webhooks
PATCH  /api/v1/webhooks/{id}
DELETE /api/v1/webhooks/{id}
POST   /api/v1/webhooks/{id}/test
GET    /api/v1/webhooks/{id}/deliveries
POST   /api/v1/webhook-deliveries/{id}/replay
```

## Application

```text
GET  /api/v1/health
GET  /api/v1/system/info
GET  /api/v1/system/ocr
POST /api/v1/system/ocr/test
GET  /api/v1/settings
PATCH /api/v1/settings
```

---

# 20. Frontend Information Architecture

Primary navigation:

```text
Overview
Projects
Queue
Reviews
Providers
Profiles
Integrations
Settings
```

Use a narrow left sidebar on desktop and a compact drawer on small screens.

## Overview

Show only information that helps the user decide what to do next:

- Active review.
- Queue depth.
- Recent completed reviews.
- Findings over the selected period.
- Projects requiring attention.
- Provider connection status.
- OCR installation status.

Avoid a dashboard made from many same-sized statistic cards.

## Projects

Use a refined table or list.

Columns:

```text
Project
Current branch
Default branch
Remote
Working tree
Last review
Status
```

Folders appear as collapsible groups.

## Queue

The Queue page is an operator workspace.

Layout:

```text
Header and queue controls
Active jobs
Queued jobs
Recently completed jobs
```

Each queued row shows:

```text
Drag handle
Priority
Project
Review target
Profile
Model
Queued time
Estimated file count
Actions
```

Use a compact row, not a large card.

## Reviews

Show searchable review history.

Filters:

```text
Status
Project
Provider
Model
Mode
Date
Source
Has findings
Has warnings
```

## Providers

Show provider health, endpoint, protocol, model count, and last successful test.

API keys are never displayed after saving.

## Profiles

Use a master-detail layout:

- Profile list on the left.
- Settings editor on the right.
- Live generated-command preview below advanced settings.

## Integrations

Sections:

```text
MCP Server
Webhook Endpoints
Webhook Deliveries
API Access
```

## Settings

Sections:

```text
General
OCR Installation
Queue
Storage and Retention
Security
Appearance
Diagnostics
```

---

# 21. Visual Design Direction

## Design Goal

The application should feel like a high-end native productivity tool translated to the web.

References:

- Apple product pages for spacing and restraint.
- macOS System Settings for hierarchy.
- Linear for dense operational data.
- Vercel for typography and technical precision.
- GitHub only for code-diff conventions, not overall styling.

Do not copy any product directly.

## Design Personality

Use:

```text
Precise
Quiet
Premium
Technical
Confident
Minimal
```

Avoid:

```text
Playful gradients
Oversized pills
Neon glows
Glassmorphism everywhere
Large dashboard cards
Decorative blobs
Emoji
Excessive icons
Marketing slogans inside the app
```

---

# 22. Visual System

## Color

Use a restrained neutral palette.

Light mode:

```css
--bg-canvas: #f5f5f7;
--bg-surface: #ffffff;
--bg-subtle: #fafafa;
--text-primary: #1d1d1f;
--text-secondary: #6e6e73;
--text-tertiary: #86868b;
--border-subtle: rgba(0, 0, 0, 0.08);
--border-strong: rgba(0, 0, 0, 0.14);
--accent: #0071e3;
--success: #248a3d;
--warning: #b56a00;
--danger: #d70015;
```

Dark mode:

```css
--bg-canvas: #0b0b0c;
--bg-surface: #151516;
--bg-subtle: #1c1c1e;
--text-primary: #f5f5f7;
--text-secondary: #a1a1a6;
--text-tertiary: #7d7d82;
--border-subtle: rgba(255, 255, 255, 0.08);
--border-strong: rgba(255, 255, 255, 0.14);
--accent: #2997ff;
--success: #30d158;
--warning: #ff9f0a;
--danger: #ff453a;
```

Rules:

- Use one primary accent.
- Reserve status colors for actual status.
- Do not place gradients on routine controls.
- Do not use blue backgrounds for entire sections.
- Code diffs may use muted semantic backgrounds.

## Typography

Preferred stack:

```css
font-family:
  Inter,
  ui-sans-serif,
  -apple-system,
  BlinkMacSystemFont,
  "Segoe UI",
  sans-serif;
```

Use a local system stack when Inter is not bundled.

Monospace:

```css
font-family:
  "SFMono-Regular",
  Consolas,
  "Liberation Mono",
  monospace;
```

Scale:

```text
Display: 32/38, weight 600
Page title: 26/32, weight 600
Section title: 18/24, weight 600
Body: 14/21, weight 400
Small: 12/18, weight 400
Label: 12/16, weight 500
Code: 12.5/19
```

Do not use bold text everywhere. Hierarchy should come primarily from scale, spacing, and placement.

## Spacing

Use a 4-pixel base grid.

Common values:

```text
4
8
12
16
20
24
32
40
48
64
```

Page content maximum width:

```text
1440px
```

Routine application pages should have approximately:

```text
32px desktop outer padding
20px tablet outer padding
16px mobile outer padding
```

## Radius

Use:

```text
6px small controls
8px inputs and buttons
10px menus
12px panels
14px modal containers
```

Avoid fully rounded pill controls unless the content is genuinely tag-like.

## Shadows

Use shadows sparingly.

Panels should primarily rely on:

```text
Surface contrast
Subtle border
Whitespace
```

Menus and modals may use a soft layered shadow.

Do not place a heavy shadow on every card.

---

# 23. Component Guidelines

## Buttons

Primary button:

- Solid accent.
- White text.
- 8px radius.
- Medium weight.
- No gradient.
- No oversized height.

Secondary button:

- Surface background.
- Subtle border.
- Primary text.

Tertiary button:

- Text or icon only.
- Background appears on hover.

Destructive actions must not be the default button in a dialog.

## Inputs

Inputs must have:

- Persistent visible label.
- Optional concise help text.
- Clear focus ring.
- Inline validation.
- Stable height.
- No floating labels.
- No placeholder-only labeling.

## Tables

Tables must:

- Use restrained row height.
- Keep headers sticky when useful.
- Use subtle separators.
- Support keyboard focus.
- Avoid borders around every cell.
- Preserve column alignment.
- Show an intentional empty state.

## Status Indicators

Use a small dot plus text.

Examples:

```text
● Running
● Queued
● Completed
● Warning
● Failed
```

Never rely on color alone.

## Cards

Cards are reserved for:

- A single active review.
- Provider configuration.
- Review summaries.
- Empty states.

Do not turn every table row or setting section into a floating card.

## Modals

Use modals only for:

- Confirmation.
- Small focused creation flows.
- Credential entry.
- Destructive actions.

Use full pages or side panels for complex provider and profile editing.

## Icons

Use one consistent icon family.

Rules:

- 16px routine icons.
- 18–20px navigation icons.
- Stroke width must be consistent.
- Do not mix filled and outline families.
- Icons require tooltips when meaning is not obvious.

---

# 24. Motion and Interaction

Motion must be subtle and functional.

Use:

```text
120–160ms hover transitions
180–220ms panel transitions
Reduced-motion support
```

Do not use:

- Large spring animations.
- Bouncing queue items.
- Animated gradient backgrounds.
- Continuous decorative motion.

The active job progress indicator may animate subtly.

Queue drag-and-drop must:

- Show a clear insertion point.
- Preserve keyboard alternatives.
- Commit ordering only after a valid drop.
- Revert cleanly on API failure.

---

# 25. Responsive Behavior

The primary target is desktop, but the app must remain usable on tablets.

Desktop:

- Persistent sidebar.
- Multi-column master-detail layouts.
- Full queue controls.
- Side-by-side findings and context where space permits.

Tablet:

- Collapsible sidebar.
- Reduced columns.
- Details in a side sheet.

Mobile:

- Read-only result inspection should work.
- Queue and settings tables may collapse into structured rows.
- Complex profile editing may use stacked sections.
- Do not hide critical controls solely because of viewport size.

---

# 26. Accessibility

Meet WCAG 2.2 AA.

Requirements:

- Full keyboard navigation.
- Visible focus states.
- Semantic headings.
- Proper form labels.
- Accessible dialogs.
- Accessible drag-and-drop alternatives.
- Status text in addition to color.
- Sufficient contrast.
- Screen-reader announcements for queue status changes.
- Reduced-motion support.
- Error summaries for long forms.

---

# 27. Security

## Path Security

- Normalize all paths.
- Use allowlisted project roots where configured.
- Never concatenate paths into shell commands.
- Reject null bytes.
- Reject traversal outside the intended root.
- Resolve symbolic links before authorization checks.
- Do not expose arbitrary file-reading endpoints.

## Git Security

- Validate refs with `git rev-parse --verify --end-of-options`.
- Reject refs beginning with `-`.
- Never pass unvalidated user refs before `--end-of-options`.
- Never run hooks supplied by untrusted repositories where avoidable.
- Use safe environment variables for Git subprocesses.
- Never run `git clean -fdx` or destructive resets on user projects.

## Process Security

- Execute argument arrays.
- Redact secrets.
- Limit log sizes.
- Limit uploaded or referenced context-file sizes.
- Set process timeouts.
- Kill process trees on cancellation.
- Restrict the backend bind address to localhost by default.

## API Security

Local mode:

- Bind to `127.0.0.1` by default.
- Use an anti-CSRF token for state-changing requests.
- Restrict allowed origins.
- Do not assume localhost means all requests are trustworthy.

Remote mode:

- Require authentication.
- Require TLS through a reverse proxy.
- Support role-based permissions.
- Protect MCP and webhook administration separately.

## Webhook Security

- HTTPS required by default.
- Block loopback, link-local, and private-network destinations unless explicitly allowed.
- Resolve DNS safely to reduce SSRF risk.
- Revalidate redirects.
- Limit response size.
- Limit connection and total timeouts.
- Sign every delivery.
- Record redacted delivery diagnostics.

---

# 28. Performance and Resource Requirements

The application must remain lightweight during long sessions.

Backend requirements:

- Bounded in-memory event buffers.
- Stream large log and JSONL files.
- Paginate reviews and findings.
- Avoid loading all session transcripts.
- Bounded provider model cache.
- Bounded branch cache.
- Close subprocess pipes correctly.
- Release worktree and process resources after jobs.
- Rotate application logs.
- Configurable artifact retention.
- SQLite WAL mode and short transactions.

Frontend requirements:

- Virtualize long queue, log, and session lists.
- Do not retain unbounded SSE events in memory.
- Paginate history.
- Lazy-load raw session data.
- Avoid global state for server data.
- Cancel obsolete requests.
- Preserve scroll and filters across navigation.

---

# 29. Error Handling

Every error shown to the user must include:

```text
What failed
Why it likely failed
What the user can do next
Relevant sanitized detail
```

Examples:

Bad:

```text
Command failed.
```

Good:

```text
OpenCodeReview could not resolve the target branch.

The branch `feature/login` was refreshed or deleted after this job was queued.
Refresh the project branches and select a valid target ref.

Git: fatal: Needed a single revision
```

Never expose:

- API keys.
- Full auth headers.
- Unredacted environment variables.
- Internal stack traces in normal UI.
- Sensitive source code in application-level error telemetry.

---

# 30. Diagnostics

Include a Diagnostics page with:

- Application version.
- Python version.
- Platform.
- Database path and status.
- OCR executable path.
- OCR version.
- OCR compatibility result.
- Git version.
- MCP server status.
- Queue worker status.
- Active process count.
- Data directory.
- Worktree count.
- Session storage size.
- Last ten sanitized backend errors.
- Downloadable diagnostic bundle.

The diagnostic bundle must redact credentials and source content by default.

---

# 31. Testing Requirements

## Backend Unit Tests

Cover:

- Path normalization.
- Folder scanning.
- Git repository detection.
- Branch parsing.
- Ref validation.
- Command generation.
- Provider resolution.
- Credential redaction.
- Queue ordering.
- State transitions.
- Retry and resume behavior.
- Webhook signature generation.
- Webhook retry policy.
- OCR result parsing.
- JSONL tail parsing.
- Worktree cleanup.

## Backend Integration Tests

Use temporary Git repositories.

Test:

- Add folder with multiple repos.
- Discover local and remote branches.
- Run mocked OCR jobs.
- Run real OCR compatibility smoke tests when OCR is installed.
- Cancel a running process tree.
- Recover interrupted jobs.
- Create and clean worktrees.
- Deliver and retry webhooks.
- Submit jobs through MCP.
- Read MCP result resources.

## Frontend Tests

Use:

- Vitest.
- React Testing Library.
- Playwright.

Cover:

- Add Folder flow.
- Add Project flow.
- Branch refresh.
- Provider creation.
- Model discovery.
- Profile editing.
- Review preview.
- Job submission.
- Queue reordering.
- Cancellation.
- SSE reconnection.
- Results copy actions.
- Export.
- Webhook test delivery.
- MCP status display.
- Keyboard navigation.

## Visual Regression

Add screenshot tests for:

- Overview.
- Projects.
- New Review.
- Queue.
- Running Job.
- Completed Results.
- Provider Settings.
- Dark mode.
- Empty states.
- Error states.

---

# 32. Repository Structure

```text
open-code-review-control-center/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── git/
│   │   ├── mcp/
│   │   ├── models/
│   │   ├── ocr/
│   │   ├── providers/
│   │   ├── queue/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── webhooks/
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── features/
│   │   ├── hooks/
│   │   ├── layouts/
│   │   ├── pages/
│   │   ├── styles/
│   │   ├── types/
│   │   └── main.tsx
│   ├── tests/
│   ├── package.json
│   └── vite.config.ts
├── scripts/
├── docs/
├── .github/
├── README.md
└── LICENSE
```

Feature-oriented frontend folders should include:

```text
features/projects
features/queue
features/reviews
features/providers
features/profiles
features/integrations
features/settings
```

Do not create one enormous generic `components` folder.

---

# 33. Required Screens

The implementation is not complete until all of these screens work:

1. First-run setup.
2. Overview.
3. Folder discovery.
4. Project list.
5. Project detail.
6. New review.
7. File preview.
8. Queue.
9. Active job detail.
10. Review history.
11. Completed result detail.
12. Raw OCR session inspector.
13. Providers.
14. Provider editor.
15. Review profiles.
16. Profile editor.
17. MCP integration.
18. Webhook endpoints.
19. Webhook delivery history.
20. Application settings.
21. Diagnostics.
22. Not-found and error states.

---

# 34. First-Run Experience

On first launch:

1. Detect Git.
2. Detect OCR.
3. Show detected executable and version.
4. Validate minimum compatible OCR behavior.
5. Ask the user to add a folder or project.
6. Ask the user to configure a provider.
7. Test the provider.
8. Create a default review profile.
9. Present the Overview.

Do not show an empty dashboard with no guidance.

---

# 35. OCR Compatibility Layer

Create a dedicated adapter:

```text
OCRAdapter
```

Responsibilities:

- Detect OCR version.
- Detect supported CLI flags.
- Generate commands.
- Build per-job configuration.
- Build task-template overrides.
- Start and stop processes.
- Parse JSON results.
- Parse session JSONL.
- Locate session files.
- Normalize warnings and findings.
- Report unsupported features to the UI.

Do not scatter OCR version checks throughout route handlers.

Compatibility result example:

```json
{
  "version": "1.x.x",
  "capabilities": {
    "json_output": true,
    "agent_audience": true,
    "resume": true,
    "background_file": true,
    "exclude_flag": true,
    "plan_mode": false,
    "template_override": false
  }
}
```

---

# 36. Generated Command Preview

Every review form must provide a collapsible command preview.

Display:

- Executable.
- Argument array.
- Redacted environment overrides.
- Worktree path.
- Job HOME path.
- Provider.
- Model.
- Resolved refs and SHAs.

Example:

```text
ocr
review
--repo
C:\...\worktrees\project-id\job-id
--from
abc123...
--to
def456...
--concurrency
8
--timeout
10
--max-tools
30
--max-git-procs
16
--format
json
--audience
human
```

The preview is informational. Users may copy it, but credential values remain redacted.

---

# 37. Acceptance Criteria

The implementation is accepted only when all of the following are true:

- A user can add a parent folder and discover multiple Git projects.
- A user can add an individual Git repository.
- Local and remote branches are retrieved and searchable.
- Branches can be fetched and refreshed without restarting the app.
- Providers and arbitrary custom endpoints can be configured.
- Models can be discovered or entered manually.
- Provider credentials are stored securely.
- Provider connectivity can be tested.
- Reusable review profiles can configure OCR behavior.
- Every supported OCR review flag is represented or deliberately controlled by the runner.
- Planning controls accurately reflect installed OCR capabilities.
- Branch and commit jobs run in isolated worktrees.
- Workspace jobs preserve uncommitted changes.
- Jobs are stored in a durable queue.
- Queue jobs can be reordered, paused, cancelled, retried, and resumed.
- Multiple jobs can use different providers without shared-config races.
- Live progress is visible without page refresh.
- OCR JSON results are parsed into structured findings.
- OCR JSONL sessions can be inspected.
- Findings can be copied individually.
- Entire reports can be copied and exported.
- An MCP client can list projects and branches.
- An MCP client can submit a review and immediately receive a job ID.
- An MCP client can retrieve status and findings.
- A signed webhook is delivered when a submitted review reaches a terminal state.
- Failed webhook deliveries are visible and replayable.
- The UI supports light and dark mode.
- The UI is keyboard accessible.
- The interface does not look like a generic admin template.
- No credentials appear in logs, exports, command previews, or browser payloads.
- Tests cover the primary workflows.
- The application runs with a single documented command.

---

# 38. Implementation Rules for the Coding Agent

1. Read Alibaba OpenCodeReview’s current CLI, configuration, session, and architecture code before implementing the adapter.
2. Do not guess at OCR flags or output fields.
3. Detect capabilities from the installed OCR binary.
4. Keep all OCR integration behind `OCRAdapter`.
5. Keep all Git integration behind `GitService`.
6. Keep queue transitions behind `QueueService`.
7. Keep credentials behind `SecretStore`.
8. Keep webhook signing and delivery behind `WebhookService`.
9. Keep MCP tools thin and call the same application services as the REST API.
10. Do not duplicate business logic between REST, MCP, and background workers.
11. Do not use shell execution.
12. Do not mutate a shared OCR config for individual jobs.
13. Do not run destructive Git commands against user repositories.
14. Do not store secrets in SQLite.
15. Do not expose raw reasoning by default.
16. Do not invent finding severity.
17. Do not render unbounded logs or sessions into the DOM.
18. Do not use placeholder data in the completed application.
19. Do not use a generic dashboard template.
20. Do not claim the implementation is complete until the acceptance criteria pass.

---

# 39. Definition of Done

The coding agent must deliver:

- Complete backend source.
- Complete React frontend source.
- Alembic migrations.
- OCR compatibility patch or maintained patch set for planning/template controls.
- MCP server.
- Signed webhook delivery system.
- Unit, integration, and end-to-end tests.
- Production build configuration.
- Cross-platform startup scripts.
- Example environment file with no real credentials.
- README with installation and usage instructions.
- Architecture documentation.
- API documentation.
- MCP tool documentation.
- Webhook verification examples.
- Screenshots of all major pages.
- A verification report mapping every acceptance criterion to a passing test or manual validation result.

The final result must be usable as a real local application, not a visual prototype.
