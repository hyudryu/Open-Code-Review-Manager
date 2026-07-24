/** Providers list (SPEC §9, §20) — health, endpoint, protocol, models, last test. */

import { useNavigate } from "react-router-dom";
import { useProviders } from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Button,
  EmptyState,
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
import { IconPlus, IconProviders } from "../components/ui/icons";
import { relativeTime } from "../lib/format";
import layout from "../layouts/layout.module.css";
import { ModelCount } from "../features/providers/ModelCount";

export function ProvidersPage() {
  const navigate = useNavigate();
  const providers = useProviders();

  return (
    <>
      <PageHeader
        title="Providers"
        subtitle="LLM endpoints and credentials. Keys are stored in the OS credential store and never shown after saving."
        actions={
          <Button variant="primary" onClick={() => navigate("/providers/new")}>
            <IconPlus size={14} /> Add provider
          </Button>
        }
      />

      {providers.error ? (
        <ErrorState title="Could not load providers" error={providers.error} onRetry={() => providers.refetch()} />
      ) : providers.isLoading ? (
        <div className={layout.stack}>
          <Skeleton height={44} />
          <Skeleton height={44} />
        </div>
      ) : (providers.data ?? []).length === 0 ? (
        <div className={layout.section}>
          <EmptyState
            icon={<IconProviders size={28} />}
            title="No providers configured"
            body="Add an LLM provider — a preset like OpenAI or Anthropic, or any OpenAI-compatible endpoint."
            action={
              <Button variant="primary" onClick={() => navigate("/providers/new")}>
                <IconPlus size={14} /> Add provider
              </Button>
            }
          />
        </div>
      ) : (
        <Table>
          <THead>
            <tr>
              <Th>Provider</Th>
              <Th>Protocol</Th>
              <Th>Endpoint</Th>
              <Th>Models</Th>
              <Th>Last discovery</Th>
              <Th>Status</Th>
            </tr>
          </THead>
          <TBody>
            {(providers.data ?? []).map((p) => (
              <Tr key={p.id} onClick={() => navigate(`/providers/${p.id}`)}>
                <Td>
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    <span style={{ fontWeight: 500 }}>{p.name}</span>
                    <span className={layout.small} style={{ fontSize: 11.5 }}>
                      {p.provider_type}
                    </span>
                  </div>
                </Td>
                <Td className={layout.small}>{p.protocol}</Td>
                <Td>
                  <span className={layout.monoPath} style={{ fontSize: 12 }}>
                    {p.base_url || "—"}
                  </span>
                </Td>
                <Td>
                  <ModelCount providerId={p.id} />
                </Td>
                <Td className={layout.small}>
                  {p.last_discovery_error ? (
                    <span style={{ color: "var(--danger)" }} title={p.last_discovery_error}>
                      failed
                    </span>
                  ) : (
                    relativeTime(p.last_discovery_at)
                  )}
                </Td>
                <Td>
                  <StatusDot
                    tone={!p.enabled ? "muted" : p.has_credential ? "ok" : "warn"}
                    label={!p.enabled ? "disabled" : p.has_credential ? "configured" : "no key"}
                  />
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
    </>
  );
}
