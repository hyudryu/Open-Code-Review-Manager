/** Integrations page (SPEC §17, §33.17) — MCP summary + API access.
 * The full MCP reference lives on the dedicated MCP tab. */

import { useSystemInfo } from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import { Button, CopyButton, StatusDot } from "../components/ui";
import { useNavigate } from "react-router-dom";
import layout from "../layouts/layout.module.css";

export function IntegrationsPage() {
  const info = useSystemInfo();
  const navigate = useNavigate();

  const origin = window.location.origin;
  const mcpUrl = `${origin}/mcp`;

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
          <p className={layout.small} style={{ margin: 0 }}>
            Live status, the full tool/resource/prompt reference, and a copy-ready client
            configuration live on the dedicated tab.
          </p>
          <div className={layout.row}>
            <Button variant="secondary" size="small" onClick={() => navigate("/mcp")}>
              Open MCP tab
            </Button>
          </div>
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
