/** Diagnostics (SPEC §30, §33.21) — full system snapshot. */

import { useSystemInfo } from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  CopyButton,
  ErrorState,
  Skeleton,
  StatusDot,
} from "../components/ui";
import { IconRefresh } from "../components/ui/icons";
import { formatBytes } from "../lib/format";
import layout from "../layouts/layout.module.css";

export function DiagnosticsPage() {
  const info = useSystemInfo();

  if (info.isLoading) {
    return (
      <>
        <PageHeader title="Diagnostics" />
        <div className={layout.stack}>
          <Skeleton height={120} />
          <Skeleton height={200} />
        </div>
      </>
    );
  }

  if (info.error || !info.data) {
    return (
      <>
        <PageHeader title="Diagnostics" />
        <ErrorState title="Could not collect diagnostics" error={info.error} onRetry={() => info.refetch()} />
      </>
    );
  }

  const d = info.data;
  const snapshot = JSON.stringify(d, null, 2);

  return (
    <>
      <PageHeader
        title="Diagnostics"
        subtitle="Sanitized system snapshot — no credentials or source content."
        actions={
          <>
            <CopyButton text={snapshot} label="Copy snapshot" />
            <Button variant="secondary" onClick={() => info.refetch()} disabled={info.isFetching}>
              <IconRefresh size={14} /> Refresh
            </Button>
          </>
        }
      />

      <div className={`${layout.stack} ${layout.stackLg}`} style={{ maxWidth: 860 }}>
        <section className={`${layout.section} ${layout.sectionTight}`} aria-label="Application">
          <h2 className={layout.sectionTitle}>Application</h2>
          <dl className={layout.dl}>
            <dt>Version</dt>
            <dd>{d.app_version}</dd>
            <dt>Python</dt>
            <dd>{d.python_version}</dd>
            <dt>Platform</dt>
            <dd>{d.platform}</dd>
            <dt>Database</dt>
            <dd style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <StatusDot
                tone={d.database_status === "ok" ? "ok" : "danger"}
                label={d.database_status}
              />
              <code className={layout.monoPath} style={{ fontSize: 11.5 }}>{d.database_path}</code>
            </dd>
            <dt>Data directory</dt>
            <dd>
              <code className={layout.monoPath} style={{ fontSize: 11.5 }}>{d.data_dir}</code>
            </dd>
            <dt>Jobs recorded</dt>
            <dd>{d.job_count}</dd>
          </dl>
        </section>

        <section className={`${layout.section} ${layout.sectionTight}`} aria-label="Toolchain">
          <h2 className={layout.sectionTitle}>Toolchain</h2>
          <dl className={layout.dl}>
            <dt>OpenCodeReview</dt>
            <dd>
              <StatusDot
                tone={d.ocr.status === "ok" ? "ok" : "danger"}
                label={
                  d.ocr.status === "ok"
                    ? `${d.ocr.version ?? "detected"}`
                    : d.ocr.status
                }
              />
            </dd>
            <dt>OCR binary</dt>
            <dd>
              <code className={layout.monoPath} style={{ fontSize: 11.5 }}>
                {d.ocr.binary_path ?? "not detected"}
              </code>
            </dd>
            <dt>OCR capabilities</dt>
            <dd>
              <div className={layout.row} style={{ gap: 4 }}>
                {Object.entries(d.ocr.capabilities)
                  .filter(([, v]) => v)
                  .map(([k]) => (
                    <Badge key={k} tone="success">
                      {k.replaceAll("_", " ")}
                    </Badge>
                  ))}
                {Object.values(d.ocr.capabilities).every((v) => !v) ? "—" : null}
              </div>
            </dd>
            <dt>Git</dt>
            <dd>{d.git_version ?? "not detected"}</dd>
          </dl>
        </section>

        <section className={`${layout.section} ${layout.sectionTight}`} aria-label="Workers and storage">
          <h2 className={layout.sectionTitle}>Workers & storage</h2>
          <dl className={layout.dl}>
            <dt>Queue worker</dt>
            <dd>
              <StatusDot
                tone={d.queue_worker.running ? "ok" : "warn"}
                label={
                  d.queue_worker.running
                    ? `running · ${d.queue_worker.active_jobs} active job${d.queue_worker.active_jobs === 1 ? "" : "s"}`
                    : "stopped"
                }
              />
            </dd>
            <dt>Webhook worker</dt>
            <dd>
              <StatusDot
                tone={d.webhook_worker.running ? "ok" : "warn"}
                label={d.webhook_worker.running ? "running" : "stopped"}
              />
            </dd>
            <dt>MCP server</dt>
            <dd>
              <StatusDot
                tone={d.mcp.mounted ? "ok" : "danger"}
                label={d.mcp.mounted ? `mounted at ${d.mcp.endpoint}` : "unavailable"}
              />
            </dd>
            <dt>Active processes</dt>
            <dd>{d.active_process_count}</dd>
            <dt>Worktrees on disk</dt>
            <dd>{d.worktree_count}</dd>
            <dt>Session storage</dt>
            <dd>{formatBytes(d.session_storage_bytes)}</dd>
          </dl>
        </section>

        <section className={`${layout.section} ${layout.sectionTight}`} aria-label="Diagnostic bundle">
          <h2 className={layout.sectionTitle}>Diagnostic bundle</h2>
          <p className={layout.small}>
            The backend does not currently expose a downloadable bundle endpoint. The
            snapshot above is fully sanitized (no credentials, no source content) — copy it
            when reporting an issue.
          </p>
        </section>
      </div>
    </>
  );
}
