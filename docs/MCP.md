# MCP Server

The control center exposes an MCP server (named **`code-review`**) over
**Streamable HTTP** at `http://127.0.0.1:8372/mcp` (same process, same port as
the REST API; stateless HTTP mode — no session affinity required). Tools are
thin wrappers over the same application services as the REST API, so behavior
is identical whether a job is submitted from the UI, the API, or an MCP client.

The server name and tool descriptions are designed to trigger on natural
phrases like "do a code review", "review my changes", "find bugs in this diff",
or "check my PR". When an agent hears these, it should call `ocr_submit_review`
rather than reviewing the code itself.

## Tools

| Tool | Description | Key arguments |
|---|---|---|
| `ocr_list_projects` | List all registered code repositories. Call this FIRST before submitting a review. | `include_unavailable?` |
| `ocr_add_project` | Register a repository and return its `project_id` (**idempotent** — returns the existing project if already registered) | `absolute_path`, `display_name?` |
| `ocr_list_branches` | Cached branches for a project | `project_id`, `refresh?`, `fetch?` |
| `ocr_list_profiles` | List review profiles | — |
| `ocr_preview_review` | Preview included/excluded files (no LLM) | `project_id`, `mode`, refs, `pr_number?` |
| `ocr_submit_review` | **CODE REVIEW tool** — reviews code for bugs, security issues, and quality problems. Use when the user asks to review code, check changes, or audit a diff. | `project_id`, `mode` (`range`/`commit`/`workspace`/`pr`), `base_ref`/`target_ref`/`commit_ref`, `pr_number?`, `profile_id?`, `background?`, `exclude_patterns?`, `priority?` |
| `ocr_get_job` | Check code review status. `wait_for_terminal=true` blocks server-side until the job finishes. | `job_id`, `wait_for_terminal?`, `timeout_seconds?` |
| `ocr_get_findings` | Get code review results — the bugs, issues, and findings found by the review. | `job_id`, `user_state?`, `limit?` |
| `ocr_cancel_job` | Cancel a running or queued review job | `job_id` |
| `ocr_retry_job` | Create a retry of a failed/cancelled job | `job_id` |
| `ocr_reorder_job` | Move a queued job (top/up/down) | `job_id`, `action` |

### Asynchronous semantics

`ocr_submit_review` does not block on the review. It persists the job and
returns its id; the queue worker picks it up. To wait for completion, call
`ocr_get_job` with `wait_for_terminal=true` — the call **blocks server-side**
(purely async; other requests are unaffected) until the job reaches a
terminal status (`completed`, `completed_with_warnings`, `failed`,
`cancelled`, `interrupted`) or `timeout_seconds` elapses (default 300,
`0` = indefinite). When waiting was requested the payload includes two extra
flags: `terminal` and `wait_expired`. If `wait_expired` is true the job is
still in flight — call again to keep waiting.

> **Tip:** The MCP client may time out after ~30s. For a single indefinite
> blocking call, use curl via the Bash tool:
> `curl 'http://127.0.0.1:8372/api/v1/jobs/{job_id}?wait_for_terminal=true&timeout_seconds=0'`

Alternatively, read `ocr://jobs/{job_id}` and poll, then fetch findings via
`ocr_get_findings` or `ocr://jobs/{job_id}/result`.

### Registering a project on demand

Every review tool takes a `project_id` — the repository must already be
registered. If you call `ocr_submit_review` or `ocr_preview_review` with a
project that isn't registered (for example because the agent is operating on
its own current working directory), the response is a structured
`not_found` error rather than a thrown exception. Recover by registering the
repository, then retrying:

```python
# The repo the agent is working in isn't registered yet.
add = await session.call_tool("ocr_add_project", {
    "absolute_path": "/path/to/repo",     # the agent's current repo
})
project_id = json.loads(add.content[0].text)["id"]   # safe to reuse immediately

# Now the review tools accept it.
job = await session.call_tool("ocr_submit_review", {
    "project_id": project_id, "mode": "commit", "commit_ref": "HEAD",
})
```

`ocr_add_project` is idempotent: it resolves the path to its git top-level
and returns the matching existing project (with `already_registered: true`)
if one is already registered, so calling it defensively before a review is
safe. If the path isn't a usable git repository, it returns a
`validation_failed` error with the reason.

### Blocking-wait example flow

```python
job = await session.call_tool("ocr_submit_review", {
    "project_id": "…", "mode": "commit", "commit_ref": "HEAD",
})
job_id = json.loads(job.content[0].text)["job_id"]

# One call waits up to 5 minutes for completion — no polling loop.
while True:
    result = await session.call_tool("ocr_get_job", {
        "job_id": job_id, "wait_for_terminal": True, "timeout_seconds": 300,
    })
    payload = json.loads(result.content[0].text)
    if payload["terminal"]:
        break  # payload["status"] is completed / failed / cancelled / …
    # wait_expired=True: still running; loop to wait again.

findings = await session.call_tool("ocr_get_findings", {"job_id": job_id})
```

### Pull request reviews

`mode="pr"` with `pr_number` resolves the open pull request against the
project's remote (GitHub API when the remote is a GitHub URL —
`OCR_CC_GITHUB_TOKEN` is honored; `git ls-remote refs/pull/*/head`
otherwise) and captures the base/target SHAs immutably at queue time. The
job then runs exactly like a range review in a detached worktree. When the
listing comes from the git fallback the base is unknown and `base_ref` is
required.

### Cancel and retry

- `ocr_cancel_job` — sends a graceful termination signal to a running job
  (or removes a queued job). The job transitions to `cancelling` then
  `cancelled`; partial logs and session artifacts are preserved.
- `ocr_retry_job` — creates a new job with the same project, mode, refs, and
  profile as the original. The new job gets a fresh `job_id`.

## Resources

| URI | Content |
|---|---|
| `ocr://projects` | All registered projects (JSON) |
| `ocr://projects/{project_id}` | One project |
| `ocr://projects/{project_id}/branches` | Cached branch list |
| `ocr://jobs/{job_id}` | Job status/progress |
| `ocr://jobs/{job_id}/result` | Full JSON result export (same as REST export `format=json`) |
| `ocr://jobs/{job_id}/findings` | Structured findings |
| `ocr://jobs/{job_id}/logs` | Redacted stdout/stderr tails |

## Prompts

| Prompt | Arguments | Purpose |
|---|---|---|
| `review_branch` | `project`, `base`, `target` | Drive a range review end-to-end |
| `review_commit` | `project`, `commit` | Review a single commit |
| `review_workspace` | `project` | Review uncommitted workspace changes |
| `summarize_findings` | `job_id` | Summarize a completed job's findings |
| `turn_findings_into_fix_plan` | `job_id` | Turn findings into an actionable fix plan |

## Client configuration

### Claude Desktop

```json
{
  "mcpServers": {
    "code-review": {
      "type": "http",
      "url": "http://127.0.0.1:8372/mcp"
    }
  }
}
```

(On Claude Desktop builds that only support stdio, use any streamable-HTTP →
stdio bridge, e.g. `mcp-remote`: `"command": "npx", "args": ["mcp-remote",
"http://127.0.0.1:8372/mcp"]`.)

### Generic streamable-HTTP client (Python)

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://127.0.0.1:8372/mcp") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        projects = await session.call_tool("ocr_list_projects", {})
        job = await session.call_tool("ocr_submit_review", {
            "project_id": "…", "mode": "commit", "commit_ref": "HEAD",
        })
        # wait via ocr_get_job wait_for_terminal=true until terminal, then:
        findings = await session.read_resource(f"ocr://jobs/{job_id}/result")
```

No authentication is required beyond the localhost binding; the MCP endpoint
shares the app's trust model (binds to 127.0.0.1). Credentials never appear in
tool outputs — providers are referenced by id/name only.
