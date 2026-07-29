/** MCP page (SPEC §17) — live server status, full tool/resource/prompt
 * reference, and a copy-ready client configuration. */

import { useSystemMcp } from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  CopyButton,
  ErrorState,
  Skeleton,
  StatusDot,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
} from "../components/ui";
import {
  MCP_PROMPTS,
  MCP_RESOURCES,
  MCP_TOOLS,
  buildMcpClientConfig,
} from "../lib/mcp";
import layout from "../layouts/layout.module.css";

function CodeBlock({ text, copyLabel }: { text: string; copyLabel: string }) {
  return (
    <div>
      <div className={layout.sectionHeader} style={{ marginBottom: 8 }}>
        <span />
        <CopyButton text={text} label={copyLabel} />
      </div>
      <pre
        style={{
          font: "var(--text-code)",
          background: "var(--code-bg)",
          borderRadius: 8,
          padding: 12,
          overflowX: "auto",
          margin: 0,
        }}
      >
        {text}
      </pre>
    </div>
  );
}

export function McpPage() {
  const status = useSystemMcp();

  const fallbackUrl = `${window.location.origin}/mcp`;
  const url = status.data?.url ?? fallbackUrl;
  const clientConfig = buildMcpClientConfig(url);

  return (
    <>
      <PageHeader
        title="MCP server"
        subtitle="Model Context Protocol endpoint for agents — tools, resources, and prompts served by this app."
      />

      <div className={`${layout.stack} ${layout.stackLg}`} style={{ maxWidth: 860 }}>
        <section className={`${layout.section} ${layout.stack}`} aria-label="MCP status">
          <div className={layout.sectionHeader} style={{ margin: 0 }}>
            <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Status</h2>
            {status.data ? (
              <StatusDot
                tone={status.data.enabled ? "ok" : "danger"}
                label={status.data.enabled ? "enabled" : "disabled"}
              />
            ) : (
              <StatusDot tone="muted" label="checking" />
            )}
          </div>
          {status.error ? (
            <ErrorState
              title="Could not load MCP status"
              error={status.error}
              onRetry={() => status.refetch()}
            />
          ) : status.isLoading ? (
            <Skeleton height={120} />
          ) : status.data ? (
            <dl className={layout.dl}>
              <dt>Transport</dt>
              <dd>Streamable HTTP ({status.data.transport})</dd>
              <dt>Endpoint</dt>
              <dd style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <code className={layout.monoPath} style={{ fontSize: 12.5 }}>
                  {status.data.url}
                </code>
                <CopyButton text={status.data.url} label="Copy" />
              </dd>
              <dt>Port</dt>
              <dd>{status.data.port}</dd>
              <dt>Surface</dt>
              <dd className={layout.row} style={{ gap: 6 }}>
                <Badge tone="neutral">{status.data.tool_count} tools</Badge>
                <Badge tone="neutral">{status.data.resource_count} resources</Badge>
                <Badge tone="neutral">{status.data.prompt_count} prompts</Badge>
              </dd>
              <dt>Trust model</dt>
              <dd>
                No authentication beyond the localhost binding — the endpoint shares
                the app's trust model. Credentials never appear in tool outputs;
                providers are referenced by id only.
              </dd>
            </dl>
          ) : null}
          <div>
            <h3 className={layout.sectionTitle} style={{ fontSize: 13.5 }}>
              Client configuration
            </h3>
            <CodeBlock text={clientConfig} copyLabel="Copy config" />
            <p className={layout.small} style={{ marginTop: 8 }}>
              Works with any streamable-HTTP MCP client. For clients that only speak
              stdio, bridge with{" "}
              <code className={layout.monoPath} style={{ fontSize: 12 }}>
                npx mcp-remote {url}
              </code>
              .
            </p>
          </div>
        </section>

        <section className={`${layout.section} ${layout.stack}`} aria-label="MCP tools">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Tools</h2>
          <p className={layout.small} style={{ margin: 0 }}>
            Submissions are asynchronous: <code>ocr_submit_review</code> returns a
            durable job id immediately. Use <code>ocr_get_job</code> for a quick
            status response, or <code>ocr_get_job_results</code> to block until the
            complete result is available.
          </p>
          <Table>
            <THead>
              <tr>
                <Th>Tool</Th>
                <Th>Description</Th>
                <Th>Key arguments</Th>
              </tr>
            </THead>
            <TBody>
              {MCP_TOOLS.map((tool) => (
                <Tr key={tool.name}>
                  <Td>
                    <code className={layout.monoPath} style={{ fontSize: 12.5 }}>
                      {tool.name}
                    </code>
                  </Td>
                  <Td className={layout.small}>{tool.description}</Td>
                  <Td className={layout.small}>{tool.args ?? "—"}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </section>

        <section className={`${layout.section} ${layout.stack}`} aria-label="MCP resources">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Resources</h2>
          <Table>
            <THead>
              <tr>
                <Th>URI</Th>
                <Th>Content</Th>
              </tr>
            </THead>
            <TBody>
              {MCP_RESOURCES.map((resource) => (
                <Tr key={resource.uri}>
                  <Td>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                      <code className={layout.monoPath} style={{ fontSize: 12.5 }}>
                        {resource.uri}
                      </code>
                      <CopyButton text={resource.uri} aria-label={`Copy ${resource.uri}`} />
                    </span>
                  </Td>
                  <Td className={layout.small}>{resource.description}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </section>

        <section className={`${layout.section} ${layout.stack}`} aria-label="MCP prompts">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Prompts</h2>
          <Table>
            <THead>
              <tr>
                <Th>Prompt</Th>
                <Th>Arguments</Th>
                <Th>Purpose</Th>
              </tr>
            </THead>
            <TBody>
              {MCP_PROMPTS.map((prompt) => (
                <Tr key={prompt.name}>
                  <Td>
                    <code className={layout.monoPath} style={{ fontSize: 12.5 }}>
                      {prompt.name}
                    </code>
                  </Td>
                  <Td className={layout.small}>{prompt.args}</Td>
                  <Td className={layout.small}>{prompt.description}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </section>
      </div>
    </>
  );
}
