/** Webhook endpoints (SPEC §18, §33.18) — CRUD, events, rotate, test, sample payloads. */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useCreateWebhook,
  useDeleteWebhook,
  useTestWebhook,
  useUpdateWebhook,
  useWebhooks,
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
  Skeleton,
  Switch,
  toast,
} from "../components/ui";
import { IconIntegrations, IconMore, IconPlus } from "../components/ui/icons";
import { relativeTime } from "../lib/format";
import { WEBHOOK_EVENTS, type WebhookEndpoint } from "../types";
import layout from "../layouts/layout.module.css";

const SAMPLE_PAYLOAD = JSON.stringify(
  {
    id: "delivery_uuid",
    event: "review.completed",
    created_at: "2026-01-01T10:00:00Z",
    job: {
      id: "job_uuid",
      source: "mcp",
      status: "completed",
      project_name: "example-project",
      mode: "range",
      base_ref: "main",
      target_ref: "feature/auth",
      provider: "openai",
      model: "gpt-4o",
    },
    summary: {
      files_reviewed: 12,
      comments: 4,
      warnings: 1,
      input_tokens: 42000,
      output_tokens: 3800,
      total_tokens: 45800,
    },
    findings: [],
    warnings: [],
  },
  null,
  2,
);

const VERIFY_PYTHON = `import hashlib, hmac

def verify(secret: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

# Headers: X-OCR-Signature-256, X-OCR-Timestamp, X-OCR-Delivery, X-OCR-Event
`;

const VERIFY_NODE = `const crypto = require("crypto");

function verify(secret, timestamp, rawBody, signature) {
  const expected =
    "sha256=" +
    crypto.createHmac("sha256", secret).update(timestamp + "." + rawBody).digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
}

// Headers: X-OCR-Signature-256, X-OCR-Timestamp, X-OCR-Delivery, X-OCR-Event
`;

function EndpointForm({
  open,
  onOpenChange,
  endpoint,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  endpoint: WebhookEndpoint | null;
}) {
  const create = useCreateWebhook();
  const update = useUpdateWebhook();
  const [name, setName] = useState(endpoint?.name ?? "");
  const [url, setUrl] = useState(endpoint?.url ?? "");
  const [secret, setSecret] = useState("");
  const [events, setEvents] = useState<Set<string>>(
    new Set(endpoint?.allowed_events ?? ["review.completed", "review.failed"]),
  );
  const [error, setError] = useState<unknown>(null);

  async function submit() {
    setError(null);
    try {
      if (endpoint) {
        await update.mutateAsync({
          id: endpoint.id,
          name: name.trim(),
          url: url.trim(),
          allowed_events: Array.from(events),
        });
        toast.success("Endpoint updated");
      } else {
        await create.mutateAsync({
          name: name.trim(),
          url: url.trim(),
          secret: secret.trim() || undefined,
          allowed_events: Array.from(events),
        });
        toast.success("Endpoint created");
      }
      onOpenChange(false);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={endpoint ? "Edit endpoint" : "New webhook endpoint"}
      description="Signed callbacks are delivered when reviews reach the selected states. HTTPS is required unless relaxed in Settings."
      width={520}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={create.isPending || update.isPending || !name.trim() || !url.trim()}
          >
            {endpoint ? "Save changes" : "Create endpoint"}
          </Button>
        </>
      }
    >
      <div className={layout.stack}>
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        <Input
          label="URL"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://agent.example.com/hooks/ocr"
          mono
          required
        />
        {!endpoint ? (
          <Input
            label="Signing secret (optional)"
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            help="Stored in the OS credential store. A random secret is generated when empty."
          />
        ) : null}
        <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
          <legend style={{ font: "var(--text-label)", color: "var(--text-secondary)", marginBottom: 6 }}>
            Events
          </legend>
          <div className={layout.stack} style={{ gap: 4 }}>
            {WEBHOOK_EVENTS.map((event) => (
              <label key={event} className={layout.small} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={events.has(event)}
                  onChange={(e) => {
                    setEvents((prev) => {
                      const next = new Set(prev);
                      if (e.target.checked) next.add(event);
                      else next.delete(event);
                      return next;
                    });
                  }}
                />
                <code style={{ fontSize: 12 }}>{event}</code>
              </label>
            ))}
          </div>
        </fieldset>
        {error ? <ErrorState title="Could not save endpoint" error={error} /> : null}
      </div>
    </Modal>
  );
}

export function WebhooksPage() {
  const navigate = useNavigate();
  const webhooks = useWebhooks();
  const update = useUpdateWebhook();
  const remove = useDeleteWebhook();
  const test = useTestWebhook();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<WebhookEndpoint | null>(null);
  const [deleting, setDeleting] = useState<WebhookEndpoint | null>(null);

  return (
    <>
      <PageHeader
        title="Webhook endpoints"
        subtitle="Signed HMAC-SHA256 callbacks for review lifecycle events."
        actions={
          <Button
            variant="primary"
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <IconPlus size={14} /> New endpoint
          </Button>
        }
      />

      {webhooks.error ? (
        <ErrorState title="Could not load endpoints" error={webhooks.error} onRetry={() => webhooks.refetch()} />
      ) : webhooks.isLoading ? (
        <div className={layout.stack}>
          <Skeleton height={64} />
          <Skeleton height={64} />
        </div>
      ) : (webhooks.data ?? []).length === 0 ? (
        <div className={layout.section}>
          <EmptyState
            icon={<IconIntegrations size={28} />}
            title="No webhook endpoints"
            body="Add an endpoint to receive signed callbacks when reviews complete or fail."
            action={
              <Button variant="primary" onClick={() => setFormOpen(true)}>
                <IconPlus size={14} /> New endpoint
              </Button>
            }
          />
        </div>
      ) : (
        <div className={layout.stack}>
          {(webhooks.data ?? []).map((endpoint) => (
            <section key={endpoint.id} className={`${layout.section} ${layout.sectionTight}`}>
              <div className={layout.row} style={{ justifyContent: "space-between" }}>
                <div style={{ minWidth: 0 }}>
                  <div className={layout.row}>
                    <strong>{endpoint.name}</strong>
                    {endpoint.has_secret ? <Badge tone="success">signed</Badge> : <Badge tone="warning">no secret</Badge>}
                  </div>
                  <div className={layout.row} style={{ marginTop: 2 }}>
                    <code className={layout.monoPath} style={{ fontSize: 12 }}>{endpoint.url}</code>
                    <CopyButton text={endpoint.url} aria-label="Copy endpoint URL" />
                  </div>
                  <p className={layout.small} style={{ marginTop: 4 }}>
                    {endpoint.allowed_events.join(" · ") || "no events selected"}
                    {endpoint.last_delivery_at
                      ? ` — last delivery ${relativeTime(endpoint.last_delivery_at)}`
                      : ""}
                  </p>
                </div>
                <div className={layout.row}>
                  <Switch
                    checked={endpoint.enabled}
                    aria-label={`Enable ${endpoint.name}`}
                    onCheckedChange={(enabled) =>
                      update.mutateAsync({ id: endpoint.id, enabled }).catch((err: Error) =>
                        toast.error("Update failed", err.message),
                      )
                    }
                  />
                  <Button
                    variant="secondary"
                    size="small"
                    disabled={test.isPending}
                    onClick={() =>
                      test.mutateAsync(endpoint.id).then(
                        (d) =>
                          toast.success(
                            "Test delivery sent",
                            d.http_status ? `HTTP ${d.http_status}` : undefined,
                          ),
                        (err: Error) => toast.error("Test failed", err.message),
                      )
                    }
                  >
                    Test
                  </Button>
                  <Button
                    variant="secondary"
                    size="small"
                    onClick={() => navigate(`/integrations/deliveries?endpoint=${endpoint.id}`)}
                  >
                    Deliveries
                  </Button>
                  <Menu
                    ariaLabel={`Actions for ${endpoint.name}`}
                    trigger={
                      <Button variant="tertiary" size="small" aria-label="Endpoint actions">
                        <IconMore size={15} />
                      </Button>
                    }
                    items={[
                      {
                        key: "edit",
                        label: "Edit",
                        onSelect: () => {
                          setEditing(endpoint);
                          setFormOpen(true);
                        },
                      },
                      {
                        key: "rotate",
                        label: "Rotate secret",
                        onSelect: () =>
                          void update
                            .mutateAsync({ id: endpoint.id, rotate_secret: true })
                            .then(() => toast.success("Secret rotated"))
                            .catch((err: Error) => toast.error("Rotation failed", err.message)),
                      },
                      { key: "sep", label: "", type: "separator" },
                      {
                        key: "delete",
                        label: "Delete",
                        danger: true,
                        onSelect: () => setDeleting(endpoint),
                      },
                    ]}
                  />
                </div>
              </div>
            </section>
          ))}
        </div>
      )}

      <section className={`${layout.section} ${layout.stack}`} style={{ marginTop: 24 }} aria-label="Receiver documentation">
        <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Verifying signatures</h2>
        <p className={layout.small}>
          Every delivery sends <code>X-OCR-Event</code>, <code>X-OCR-Delivery</code>,{" "}
          <code>X-OCR-Timestamp</code>, and <code>X-OCR-Signature-256</code>. The signature is{" "}
          <code>sha256=HMAC_SHA256(secret, timestamp + "." + raw_body)</code>. Deduplicate by{" "}
          <code>X-OCR-Delivery</code>.
        </p>
        <div>
          <div className={layout.sectionHeader} style={{ marginBottom: 6 }}>
            <h3 className={layout.sectionTitle} style={{ margin: 0, fontSize: 13.5 }}>Sample payload</h3>
            <CopyButton text={SAMPLE_PAYLOAD} label="Copy payload" />
          </div>
          <pre style={{ font: "var(--text-code)", background: "var(--code-bg)", borderRadius: 8, padding: 12, maxHeight: 240, overflow: "auto" }}>
            {SAMPLE_PAYLOAD}
          </pre>
        </div>
        <div className={layout.grid2} style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
          <div>
            <div className={layout.sectionHeader} style={{ marginBottom: 6 }}>
              <h3 className={layout.sectionTitle} style={{ margin: 0, fontSize: 13.5 }}>Python</h3>
              <CopyButton text={VERIFY_PYTHON} label="Copy" />
            </div>
            <pre style={{ font: "var(--text-code)", background: "var(--code-bg)", borderRadius: 8, padding: 12, overflowX: "auto" }}>
              {VERIFY_PYTHON}
            </pre>
          </div>
          <div>
            <div className={layout.sectionHeader} style={{ marginBottom: 6 }}>
              <h3 className={layout.sectionTitle} style={{ margin: 0, fontSize: 13.5 }}>Node.js</h3>
              <CopyButton text={VERIFY_NODE} label="Copy" />
            </div>
            <pre style={{ font: "var(--text-code)", background: "var(--code-bg)", borderRadius: 8, padding: 12, overflowX: "auto" }}>
              {VERIFY_NODE}
            </pre>
          </div>
        </div>
      </section>

      {formOpen ? (
        <EndpointForm open={formOpen} onOpenChange={setFormOpen} endpoint={editing} />
      ) : null}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title="Delete endpoint"
        description={`Delete "${deleting?.name}"? Pending deliveries for this endpoint are dropped.`}
        confirmLabel="Delete endpoint"
        destructive
        busy={remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await remove.mutateAsync(deleting.id);
            toast.success("Endpoint deleted");
            setDeleting(null);
          } catch (err) {
            toast.error("Delete failed", err instanceof Error ? err.message : undefined);
          }
        }}
      />
    </>
  );
}
