/** MCP integration page (SPEC §17, §33.17) — endpoint, status, docs, config snippets. */

import { useSystemInfo } from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import { Button, CopyButton, StatusDot, Table, TBody, Td, Th, THead, Tr } from "../components/ui";
import { useNavigate } from "react-router-dom";
import layout from "../layouts/layout.module.css";

const MCP_TOOLS = [
  { name: "ocr_list_projects", description: "List registered projects; optional search text." },
  { name: "ocr_list_branches", description: "List cached branches for a project; optionally refresh or fetch." },
  { name: "ocr_list_profiles", description: "List available review profiles." },
  { name: "ocr_preview_review", description: "Preview included/excluded files without calling the LLM." },
  { name: "ocr_submit_review", description: "Queue a review; returns a durable job ID immediately." },
  { name: "ocr_get_job", description: "Get job status and progress." },
  { name: "ocr_get_findings", description: "Get structured findings when available." },
  { name: "ocr_cancel_job", description: "Request job cancellation." },
  { name: "ocr_retry_job", description: "Create a retry of a finished job." },
  { name: "ocr_reorder_job", description: "Change a queued job's position." },
];

const MCP_RESOURCES = [
  "ocr://projects",
  "ocr://projects/{project_id}",
  "ocr://projects/{project_id}/branches",
  "ocr://jobs/{job_id}",
  "ocr://jobs/{job_id}/result",
  "ocr://jobs/{job_id}/findings",
  "ocr://jobs/{job_id}/logs",
];

const MCP_PROMPTS = [
  "review_branch",
  "review_commit",
  "review_workspace",
  "summarize_findings",
  "turn_findings_into_fix_plan",
];

export function IntegrationsPage() {
  const info = useSystemInfo();
  const navigate = useNavigate();

  const origin = window.location.origin;
  const mcpUrl = `${origin}/mcp`;
  const clientConfig = JSON.stringify(
    {
      mcpServers: {
        "ocr-control-center": {
          url: mcpUrl,
        },
      },
    },
    null,
    2,
  );
  const submitExample = JSON.stringify(
    {
      project_id: "<project-uuid>",
      mode: "range",
      base_ref: "main",
      target_ref: "feature/example",
      profile_id: "<profile-uuid>",
      background: "Focus on the auth changes.",
      priority: 50,
    },
    null,
    2,
  );

  return (
    <>
      <PageHeader
        title="Integrations"
        subtitle="MCP server, webhooks, and API access for agents and automation."
        actions={
          <Button variant="secondary" onClick={() => navigate("/integrations/webhooks")}>
            Webhook endpoints
          </Button>
        }
      />

      <div className={`${layout.stack} ${layout.stackLg}`} style={{ maxWidth: 860 }}>
        <section className={`${layout.section} ${layout.stack}`} aria-label="MCP server">
          <div className={layout.sectionHeader} style={{ margin: 0 }}>
            <h2 className={layout.sectionTitle} style={{ margin: 0 }}>MCP server</h2>
            {info.data ? (
              <StatusDot
                tone={info.data.mcp.mounted ? "ok" : "danger"}
                label={info.data.mcp.mounted ? "mounted" : "unavailable"}
              />
            ) : (
              <StatusDot tone="muted" label="checking" />
            )}
          </div>
          <dl className={layout.dl}>
            <dt>Transport</dt>
            <dd>Streamable HTTP</dd>
            <dt>Endpoint</dt>
            <dd style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <code className={layout.monoPath} style={{ fontSize: 12.5 }}>{mcpUrl}</code>
              <CopyButton text={mcpUrl} label="Copy" />
            </dd>
            <dt>Semantics</dt>
            <dd>
              Submissions are asynchronous — the caller receives a durable job ID and polls
              with <code>ocr_get_job</code> or reads result resources.
            </dd>
          </dl>

          <div>
            <div className={layout.sectionHeader} style={{ marginBottom: 8 }}>
              <h3 className={layout.sectionTitle} style={{ margin: 0, fontSize: 13.5 }}>
                Client configuration
              </h3>
              <CopyButton text={clientConfig} label="Copy config" />
            </div>
            <pre style={{ font: "var(--text-code)", background: "var(--code-bg)", borderRadius: 8, padding: 12, overflowX: "auto" }}>
              {clientConfig}
            </pre>
          </div>
        </section>

        <section className={`${layout.section} ${layout.stack}`} aria-label="MCP tools">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Tools</h2>
          <Table>
            <THead>
              <tr>
                <Th>Tool</Th>
                <Th>Description</Th>
              </tr>
            </THead>
            <TBody>
              {MCP_TOOLS.map((tool) => (
                <Tr key={tool.name}>
                  <Td>
                    <code className={layout.monoPath} style={{ fontSize: 12.5 }}>{tool.name}</code>
                  </Td>
                  <Td className={layout.small}>{tool.description}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
          <div>
            <div className={layout.sectionHeader} style={{ marginBottom: 8 }}>
              <h3 className={layout.sectionTitle} style={{ margin: 0, fontSize: 13.5 }}>
                Example — ocr_submit_review
              </h3>
              <CopyButton text={submitExample} label="Copy example" />
            </div>
            <pre style={{ font: "var(--text-code)", background: "var(--code-bg)", borderRadius: 8, padding: 12, overflowX: "auto" }}>
              {submitExample}
            </pre>
          </div>
        </section>

        <section className={`${layout.section} ${layout.stack}`} aria-label="MCP resources and prompts">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Resources</h2>
          <ul className={layout.stack} style={{ gap: 4 }}>
            {MCP_RESOURCES.map((r) => (
              <li key={r} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <code className={layout.monoPath} style={{ fontSize: 12.5 }}>{r}</code>
                <CopyButton text={r} aria-label={`Copy ${r}`} />
              </li>
            ))}
          </ul>
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Prompts</h2>
          <ul className={layout.stack} style={{ gap: 4 }}>
            {MCP_PROMPTS.map((p) => (
              <li key={p}>
                <code className={layout.monoPath} style={{ fontSize: 12.5 }}>{p}</code>
              </li>
            ))}
          </ul>
        </section>

        <section className={`${layout.section} ${layout.stack}`} aria-label="API access">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>API access</h2>
          <dl className={layout.dl}>
            <dt>REST base</dt>
            <dd>
              <code className={layout.monoPath} style={{ fontSize: 12.5 }}>{origin}/api/v1</code>
            </dd>
            <dt>CSRF</dt>
            <dd>
              State-changing requests echo the <code>ocrcc_csrf</code> cookie in the{" "}
              <code>X-OCR-CSRF</code> header (double-submit). Safe GETs set the cookie.
            </dd>
            <dt>Live events</dt>
            <dd>
              <code className={layout.monoPath} style={{ fontSize: 12.5 }}>
                GET /api/v1/jobs/{"{id}"}/events
              </code>{" "}
              — SSE with Last-Event-ID resume; closes at terminal state.
            </dd>
            <dt>Webhooks</dt>
            <dd>
              Signed HMAC-SHA256 delivery callbacks —{" "}
              <a href="/integrations/webhooks" onClick={(e) => { e.preventDefault(); navigate("/integrations/webhooks"); }}>
                manage endpoints
              </a>
              .
            </dd>
          </dl>
        </section>
      </div>
    </>
  );
}
