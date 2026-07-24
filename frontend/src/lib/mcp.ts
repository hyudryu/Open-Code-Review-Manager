/**
 * MCP surface documentation — names verified against
 * backend/app/mcp/server.py. Shared by the MCP page and the Integrations
 * page summary.
 */

export interface McpToolDoc {
  name: string;
  description: string;
  args?: string;
}

export interface McpResourceDoc {
  uri: string;
  description: string;
}

export interface McpPromptDoc {
  name: string;
  args: string;
  description: string;
}

export const MCP_TOOLS: McpToolDoc[] = [
  {
    name: "ocr_list_projects",
    description: "List registered projects.",
    args: "query?, include_unavailable?",
  },
  {
    name: "ocr_list_branches",
    description: "List cached branches for a project, optionally refreshing or fetching first.",
    args: "project_id, refresh?, fetch?",
  },
  {
    name: "ocr_list_profiles",
    description: "List review profiles.",
  },
  {
    name: "ocr_preview_review",
    description: "Preview included/excluded files without using the LLM.",
    args: "project_id, mode, base_ref?, target_ref?, commit_ref?, profile_id?, exclude_patterns?",
  },
  {
    name: "ocr_submit_review",
    description: "Submit a review job asynchronously — returns a durable job id immediately.",
    args: "project_id, mode, refs, profile_id?, background?, priority?, webhook_url?, webhook_secret?, metadata?",
  },
  {
    name: "ocr_get_job",
    description:
      "Get job status and progress. wait_for_terminal=true blocks server-side until the job reaches a terminal state or the timeout (adds terminal / wait_expired flags).",
    args: "job_id, wait_for_terminal?, timeout_seconds?",
  },
  {
    name: "ocr_get_findings",
    description: "Get structured findings for a job (never raw reasoning).",
    args: "job_id, limit?, offset?",
  },
  {
    name: "ocr_cancel_job",
    description: "Request job cancellation.",
    args: "job_id",
  },
  {
    name: "ocr_retry_job",
    description: "Create a retry of a failed job.",
    args: "job_id",
  },
  {
    name: "ocr_reorder_job",
    description: "Move a queued job within the queue.",
    args: "job_id, action (top | up | down)",
  },
];

export const MCP_RESOURCES: McpResourceDoc[] = [
  { uri: "ocr://projects", description: "All registered projects (JSON)." },
  { uri: "ocr://projects/{project_id}", description: "One project." },
  { uri: "ocr://projects/{project_id}/branches", description: "Cached branch list for a project." },
  { uri: "ocr://jobs/{job_id}", description: "Job status and progress." },
  { uri: "ocr://jobs/{job_id}/result", description: "Full JSON result export." },
  { uri: "ocr://jobs/{job_id}/findings", description: "Structured findings." },
  { uri: "ocr://jobs/{job_id}/logs", description: "Redacted stdout/stderr tails." },
];

export const MCP_PROMPTS: McpPromptDoc[] = [
  { name: "review_branch", args: "project, base?, target?", description: "Drive a branch-range review end-to-end." },
  { name: "review_commit", args: "project, commit", description: "Review a single commit." },
  { name: "review_workspace", args: "project", description: "Review uncommitted workspace changes." },
  { name: "summarize_findings", args: "job_id", description: "Summarize a completed job's findings." },
  { name: "turn_findings_into_fix_plan", args: "job_id", description: "Turn findings into an actionable fix plan." },
];

/** Copy-ready MCP client configuration snippet for streamable-HTTP clients. */
export function buildMcpClientConfig(url: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        "ocr-control-center": {
          type: "http",
          url,
        },
      },
    },
    null,
    2,
  );
}

/** One-line success summary for the provider connection test panel. */
export function formatProviderTestSuccess(result: {
  elapsed_ms?: number | null;
  reply?: string | null;
}): string {
  const ms =
    result.elapsed_ms != null ? ` in ${Math.round(result.elapsed_ms)} ms` : "";
  if (result.reply) {
    return `Responded${ms}: "${result.reply}"`;
  }
  return `Connection successful${ms}`;
}
