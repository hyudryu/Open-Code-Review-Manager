/** MCP page (SPEC §17) — two surfaces behind tabs:
 *
 *  - "Manager server": this app's own MCP endpoint (live status, the full
 *    tool/resource/prompt reference, and a copy-ready client config).
 *  - "OCR MCP servers": the MCP servers configured for the OpenCodeReview
 *    review engine itself (the `mcp_servers` map of its user config). Those
 *    servers' tools become available to the review agent during reviews —
 *    e.g. docs lookup, Cognee, or CodeGraph.
 */

import { useState } from "react";
import {
  useDeleteOcrMcpServer,
  useOcrMcpServers,
  useSystemMcp,
  useUpsertOcrMcpServer,
} from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  ConfirmDialog,
  CopyButton,
  EmptyState,
  ErrorState,
  Input,
  Menu,
  Modal,
  Select,
  Skeleton,
  StatusDot,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
  Tabs,
  Textarea,
  toast,
} from "../components/ui";
import { IconMore, IconPlus } from "../components/ui/icons";
import {
  MCP_PROMPTS,
  MCP_RESOURCES,
  MCP_TOOLS,
  buildMcpClientConfig,
} from "../lib/mcp";
import {
  headersToText,
  listToText,
  parseEnvLines,
  parseHeaderLines,
  parseLines,
  parseToolList,
} from "../lib/ocr-mcp";
import type { OcrMcpServer, OcrMcpServerInput } from "../types";
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

// ---------------------------------------------------------------------------
// Tab 1 — this app's MCP endpoint
// ---------------------------------------------------------------------------

function ManagerServerTab() {
  const status = useSystemMcp();

  const fallbackUrl = `${window.location.origin}/mcp`;
  const url = status.data?.url ?? fallbackUrl;
  const clientConfig = buildMcpClientConfig(url);

  return (
    <div className={`${layout.stack} ${layout.stackLg}`}>
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
  );
}

// ---------------------------------------------------------------------------
// Tab 2 — the review engine's own MCP servers
// ---------------------------------------------------------------------------

function McpServerForm({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: OcrMcpServer | null;
}) {
  const upsert = useUpsertOcrMcpServer();
  const [name, setName] = useState(editing?.name ?? "");
  const [type, setType] = useState<"stdio" | "remote">(editing?.type ?? "stdio");
  const [command, setCommand] = useState(editing?.command ?? "");
  const [argsText, setArgsText] = useState(listToText(editing?.args));
  const [url, setUrl] = useState(editing?.url ?? "");
  const [headersText, setHeadersText] = useState(headersToText(editing?.headers));
  const [toolsText, setToolsText] = useState((editing?.tools ?? []).join(", "));
  const [setup, setSetup] = useState(editing?.setup ?? "");
  const [envText, setEnvText] = useState(listToText(editing?.env));
  const [error, setError] = useState<unknown>(null);

  async function submit() {
    setError(null);
    let config: OcrMcpServerInput;
    try {
      config = {
        type,
        ...(type === "stdio"
          ? {
              command: command.trim(),
              args: parseLines(argsText),
              setup: setup.trim() || null,
              env: parseEnvLines(envText),
            }
          : {
              url: url.trim(),
              headers: Object.keys(parseHeaderLines(headersText)).length
                ? parseHeaderLines(headersText)
                : null,
            }),
        tools: parseToolList(toolsText),
      };
    } catch (err) {
      setError(err);
      return;
    }
    try {
      await upsert.mutateAsync({ name: name.trim(), ...config });
      toast.success(
        editing ? "MCP server updated" : "MCP server added",
        "Reviews will connect to it from the next run.",
      );
      onOpenChange(false);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={editing ? `Edit MCP server “${editing.name}”` : "New OCR MCP server"}
      description="Saved to the OpenCodeReview user config (~/.opencodereview/config.json). Its tools become available to the review agent on every subsequent review."
      width={560}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={
              upsert.isPending ||
              !name.trim() ||
              (type === "stdio" ? !command.trim() : !url.trim())
            }
          >
            {editing ? "Save changes" : "Add server"}
          </Button>
        </>
      }
    >
      <div className={layout.stack}>
        <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 140px" }}>
          <Input
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="docs"
            help="Letters, digits, hyphen, underscore — no dots."
            required
            disabled={Boolean(editing)}
            mono
          />
          <Select
            label="Type"
            value={type}
            onChange={(e) => setType(e.target.value as "stdio" | "remote")}
            help="stdio runs locally; remote dials out."
          >
            <option value="stdio">stdio</option>
            <option value="remote">remote</option>
          </Select>
        </div>

        {type === "stdio" ? (
          <>
            <Input
              label="Command"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="npx"
              help="Executable that starts the MCP server."
              required
              mono
            />
            <Textarea
              label="Arguments"
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
              rows={3}
              placeholder={"-y\n@acme/docs-mcp-server"}
              help="One argument per line."
              mono
            />
            <Input
              label="Setup command (optional)"
              value={setup}
              onChange={(e) => setSetup(e.target.value)}
              placeholder="npm install -g @acme/docs-mcp-server"
              help="Shell command run once before the server starts (5-minute timeout)."
              mono
            />
            <Textarea
              label="Environment (optional)"
              value={envText}
              onChange={(e) => setEnvText(e.target.value)}
              rows={2}
              placeholder={"DOCS_TOKEN=secret\nDOCS_REGION=eu"}
              help="KEY=VALUE per line, passed to the server subprocess."
              mono
            />
          </>
        ) : (
          <>
            <Input
              label="URL"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://mcp.example.com/mcp"
              help="Streamable HTTP endpoint."
              required
              mono
            />
            <Textarea
              label="Headers (optional)"
              value={headersText}
              onChange={(e) => setHeadersText(e.target.value)}
              rows={2}
              placeholder={"Authorization: Bearer $MCP_TOKEN"}
              help={'"Name: value" per line. Values expand $ENV_VARS at connection time.'}
              mono
            />
          </>
        )}

        <Input
          label="Tool allowlist (optional)"
          value={toolsText}
          onChange={(e) => setToolsText(e.target.value)}
          placeholder="search_docs, get_page"
          help="Comma-separated tool names to expose to the reviewer. Empty registers every tool the server offers."
          mono
        />

        {error ? (
          <ErrorState title="Could not save MCP server" error={error} />
        ) : null}
      </div>
    </Modal>
  );
}

function OcrMcpServersTab() {
  const servers = useOcrMcpServers();
  const remove = useDeleteOcrMcpServer();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<OcrMcpServer | null>(null);
  const [deleting, setDeleting] = useState<OcrMcpServer | null>(null);

  return (
    <div className={`${layout.stack} ${layout.stackLg}`}>
      <section className={`${layout.section} ${layout.stack}`} aria-label="OCR MCP servers">
        <div className={layout.sectionHeader} style={{ margin: 0 }}>
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>
            Review engine MCP servers
          </h2>
          <Button
            variant="primary"
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <IconPlus size={14} /> New server
          </Button>
        </div>
        <p className={layout.small} style={{ margin: 0 }}>
          OpenCodeReview acts as an MCP client: every server listed here is
          connected before a review and its tools become available to the review
          agent next to the built-in ones. Use this to give the reviewer external
          context — a docs or issue-tracker lookup, Cognee memory, CodeGraph
          queries, or any other MCP server. Changes apply to all future reviews,
          including jobs queued from this app.
        </p>

        {servers.error ? (
          <ErrorState
            title="Could not load OCR MCP servers"
            error={servers.error}
            onRetry={() => servers.refetch()}
          />
        ) : servers.isLoading ? (
          <Skeleton height={140} />
        ) : (servers.data ?? []).length === 0 ? (
          <EmptyState
            title="No MCP servers configured"
            body="Add a server to extend the review agent with external tools."
            action={
              <Button
                variant="primary"
                onClick={() => {
                  setEditing(null);
                  setFormOpen(true);
                }}
              >
                <IconPlus size={14} /> New server
              </Button>
            }
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Name</Th>
                <Th>Type</Th>
                <Th>Target</Th>
                <Th>Tools</Th>
                <Th aria-label="Actions" />
              </tr>
            </THead>
            <TBody>
              {(servers.data ?? []).map((server) => (
                <Tr key={server.name}>
                  <Td>
                    <code className={layout.monoPath} style={{ fontSize: 12.5 }}>
                      {server.name}
                    </code>
                  </Td>
                  <Td>
                    <Badge tone={server.type === "remote" ? "accent" : "neutral"}>
                      {server.type}
                    </Badge>
                  </Td>
                  <Td className={layout.small}>
                    {server.type === "remote"
                      ? (server.url ?? "—")
                      : [server.command, ...(server.args ?? [])].join(" ")}
                    {server.setup ? (
                      <span className={layout.small} style={{ display: "block", opacity: 0.75 }}>
                        setup: {server.setup}
                      </span>
                    ) : null}
                  </Td>
                  <Td className={layout.small}>
                    {server.tools?.length ? server.tools.join(", ") : "all tools"}
                  </Td>
                  <Td>
                    <div className={layout.row} style={{ justifyContent: "flex-end" }}>
                      <Menu
                        ariaLabel={`Actions for ${server.name}`}
                        trigger={
                          <Button variant="tertiary" size="small" aria-label="Server actions">
                            <IconMore size={15} />
                          </Button>
                        }
                        items={[
                          {
                            key: "edit",
                            label: "Edit",
                            onSelect: () => {
                              setEditing(server);
                              setFormOpen(true);
                            },
                          },
                          { key: "sep", label: "", type: "separator" },
                          {
                            key: "delete",
                            label: "Remove",
                            danger: true,
                            onSelect: () => setDeleting(server),
                          },
                        ]}
                      />
                    </div>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}

        <p className={layout.small} style={{ margin: 0 }}>
          Equivalent CLI commands:{" "}
          <code className={layout.monoPath} style={{ fontSize: 12 }}>
            ocr config set mcp_servers.&lt;name&gt;.&lt;field&gt; …
          </code>{" "}
          and{" "}
          <code className={layout.monoPath} style={{ fontSize: 12 }}>
            ocr config unset mcp_servers.&lt;name&gt;
          </code>
          . Agents can manage the same list through the{" "}
          <code>ocr_add_mcp_server</code> / <code>ocr_remove_mcp_server</code>{" "}
          tools on the Manager server tab.
        </p>
      </section>

      {formOpen ? (
        <McpServerForm open={formOpen} onOpenChange={setFormOpen} editing={editing} />
      ) : null}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title="Remove MCP server"
        description={`Remove "${deleting?.name}" from OpenCodeReview? Its tools will no longer be available to the review agent.`}
        confirmLabel="Remove server"
        destructive
        busy={remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await remove.mutateAsync(deleting.name);
            toast.success("MCP server removed");
            setDeleting(null);
          } catch (err) {
            toast.error(
              "Remove failed",
              err instanceof Error ? err.message : undefined,
            );
          }
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------

export function McpPage() {
  return (
    <>
      <PageHeader
        title="MCP"
        subtitle="Model Context Protocol integrations — this app's agent endpoint and the review engine's own MCP servers."
      />
      <div style={{ maxWidth: 860 }}>
        <Tabs
          aria-label="MCP sections"
          items={[
            {
              value: "manager",
              label: "Manager server",
              content: <ManagerServerTab />,
            },
            {
              value: "ocr-servers",
              label: "OCR MCP servers",
              content: <OcrMcpServersTab />,
            },
          ]}
        />
      </div>
    </>
  );
}
