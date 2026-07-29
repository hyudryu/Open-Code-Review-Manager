/** Webhook delivery history (SPEC §18, §33.19) — status, http code, excerpt, replay. */

import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useDeliveries, useReplayDelivery, useWebhooks } from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Select,
  Skeleton,
  StatusDot,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
  toast,
} from "../components/ui";
import { formatDateTime, relativeTime } from "../lib/format";
import type { WebhookDelivery } from "../types";
import layout from "../layouts/layout.module.css";

function deliveryTone(status: string): "ok" | "danger" | "warn" | "muted" | "accent" {
  if (status === "delivered" || status === "success") return "ok";
  if (status === "failed" || status === "exhausted") return "danger";
  if (status === "pending" || status === "delivering") return "accent";
  return "muted";
}

function DeliveryRow({ delivery }: { delivery: WebhookDelivery }) {
  const replay = useReplayDelivery();
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <Tr onClick={() => setExpanded((v) => !v)}>
        <Td>
          <code className={layout.monoPath} style={{ fontSize: 12 }}>{delivery.event_type}</code>
        </Td>
        <Td>
          <StatusDot tone={deliveryTone(delivery.status)} label={delivery.status} />
        </Td>
        <Td>{delivery.http_status ?? "—"}</Td>
        <Td className={layout.small}>attempt {delivery.attempt}</Td>
        <Td className={layout.small} title={formatDateTime(delivery.created_at)}>
          {relativeTime(delivery.created_at)}
        </Td>
        <Td className={layout.small}>
          {delivery.next_attempt_at ? relativeTime(delivery.next_attempt_at) : "—"}
        </Td>
        <Td>
          {delivery.status === "failed" || delivery.status === "exhausted" ? (
            <Button
              variant="secondary"
              size="small"
              disabled={replay.isPending}
              onClick={(e) => {
                e.stopPropagation();
                replay.mutateAsync(delivery.id).then(
                  () => toast.success("Delivery re-queued"),
                  (err: Error) => toast.error("Replay failed", err.message),
                );
              }}
            >
              Replay
            </Button>
          ) : null}
        </Td>
      </Tr>
      {expanded ? (
        <tr>
          <Td colSpan={7}>
            <div className={layout.stack} style={{ gap: 6, padding: "8px 0" }}>
              <span className={layout.small}>
                Delivery ID: <code>{delivery.delivery_id}</code>
                {delivery.job_id ? (
                  <>
                    {" · "}
                    <Link to={`/reviews/${delivery.job_id}`}>view job</Link>
                  </>
                ) : null}
              </span>
              {delivery.response_excerpt ? (
                <pre
                  className={layout.monoPath}
                  style={{
                    fontSize: 11.5,
                    background: "var(--code-bg)",
                    borderRadius: 6,
                    padding: 8,
                    whiteSpace: "pre-wrap",
                    margin: 0,
                  }}
                >
                  {delivery.response_excerpt}
                </pre>
              ) : (
                <span className={layout.small}>No response recorded.</span>
              )}
            </div>
          </Td>
        </tr>
      ) : null}
    </>
  );
}

export function DeliveriesPage() {
  const [params, setParams] = useSearchParams();
  const webhooks = useWebhooks();
  const endpointId = params.get("endpoint") ?? "";
  const effectiveId = endpointId || (webhooks.data?.[0]?.id ?? "");
  const deliveries = useDeliveries(effectiveId);

  return (
    <>
      <PageHeader
        title="Webhook deliveries"
        subtitle="Every delivery attempt with response status and excerpt. Failed deliveries can be replayed."
        actions={
          <Link to="/integrations/webhooks">
            <Button variant="secondary">Endpoints</Button>
          </Link>
        }
      />

      <div className={layout.row} style={{ marginBottom: 16 }}>
        <span className={layout.small} style={{ alignSelf: "center", marginRight: 8 }}>
          Endpoint
        </span>
        <Select
          aria-label="Filter by endpoint"
          value={effectiveId}
          onChange={(e) => setParams({ endpoint: e.target.value })}
        >
          <option value="">All</option>
          {(webhooks.data ?? []).map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </Select>
      </div>

      {!effectiveId ? (
        <div className={layout.section}>
          <EmptyState
            title="No endpoints yet"
            body="Create a webhook endpoint first, then deliveries will appear here."
            action={
              <Link to="/integrations/webhooks">
                <Button variant="primary" size="small">Manage endpoints</Button>
              </Link>
            }
          />
        </div>
      ) : deliveries.error ? (
        <ErrorState title="Could not load deliveries" error={deliveries.error} onRetry={() => deliveries.refetch()} />
      ) : deliveries.isLoading ? (
        <div className={layout.stack}>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} height={40} />
          ))}
        </div>
      ) : (deliveries.data ?? []).length === 0 ? (
        <div className={layout.section}>
          <EmptyState
            title="No deliveries yet"
            body="Deliveries appear here when reviews reach a state this endpoint subscribes to, or when you send a test."
          />
        </div>
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>Event</Th>
              <Th>Status</Th>
              <Th>HTTP</Th>
              <Th>Attempt</Th>
              <Th>Created</Th>
              <Th>Next retry</Th>
              <Th />
            </tr>
          </THead>
          <TBody>
            {(deliveries.data ?? []).map((d) => (
              <DeliveryRow key={d.id} delivery={d} />
            ))}
          </TBody>
        </Table>
      )}
      <p className={layout.small} style={{ marginTop: 12 }}>
        <Badge tone="neutral">Retry policy</Badge> immediate → 1 min → 5 min → 30 min → 2 h →
        12 h → 24 h. Any 2xx is a success; 4xx (except 408/409/425/429) is not retried.
      </p>
    </>
  );
}
