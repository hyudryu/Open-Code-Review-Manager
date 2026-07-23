# MCP Server

The control center exposes an MCP server over **Streamable HTTP** at
`http://127.0.0.1:8787/mcp` (same process, same port as the REST API; stateless
HTTP mode — no session affinity required). Tools are thin wrappers over the
same application services as the REST API, so behavior is identical whether a
job is submitted from the UI, the API, or an MCP client.

## Tools

| Tool | Description | Key arguments |
|---|---|---|
| `ocr_list_projects` | List registered projects | `include_unavailable?` |
| `ocr_list_branches` | Cached branches for a project | `project_id`, `refresh?`, `fetch?` |
| `ocr_list_profiles` | List review profiles | — |
| `ocr_preview_review` | Preview included/excluded files (no LLM) | `project_id`, `mode`, refs |
| `ocr_submit_review` | Submit a review job — **returns a durable job id immediately** | `project_id`, `mode` (`range`/`commit`/`workspace`), `base_ref`/`target_ref`/`commit_ref`, `profile_id?`, `background?`, `exclude_patterns?`, `priority?` |
| `ocr_get_job` | Job status and progress | `job_id` |
| `ocr_get_findings` | Structured findings (never includes raw reasoning) | `job_id`, `user_state?`, `limit?` |
| `ocr_cancel_job` | Request cancellation | `job_id` |
| `ocr_retry_job` | Create a retry of a failed/cancelled job | `job_id` |
| `ocr_reorder_job` | Move a queued job | `job_id`, `action` (`top`/`up`/`down`) |

### Asynchronous semantics

`ocr_submit_review` does not block on the review. It persists the job and
returns its id; the queue worker picks it up. Poll `ocr_get_job` (or read
`ocr://jobs/{job_id}`) until `status` is terminal (`completed`,
`completed_with_warnings`, `failed`, `cancelled`), then read findings via
`ocr_get_findings` or `ocr://jobs/{job_id}/result`.

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
    "ocr-control-center": {
      "type": "http",
      "url": "http://127.0.0.1:8787/mcp"
    }
  }
}
```

(On Claude Desktop builds that only support stdio, use any streamable-HTTP →
stdio bridge, e.g. `mcp-remote`: `"command": "npx", "args": ["mcp-remote",
"http://127.0.0.1:8787/mcp"]`.)

### Generic streamable-HTTP client (Python)

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://127.0.0.1:8787/mcp") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        projects = await session.call_tool("ocr_list_projects", {})
        job = await session.call_tool("ocr_submit_review", {
            "project_id": "…", "mode": "commit", "commit_ref": "HEAD",
        })
        # poll ocr_get_job until terminal, then:
        findings = await session.read_resource(f"ocr://jobs/{job_id}/result")
```

No authentication is required beyond the localhost binding; the MCP endpoint
shares the app's trust model (binds to 127.0.0.1). Credentials never appear in
tool outputs — providers are referenced by id/name only.
