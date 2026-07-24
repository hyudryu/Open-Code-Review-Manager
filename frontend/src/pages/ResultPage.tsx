/** Completed result detail (SPEC §15, §33.11) — stats header + grouped findings. */

import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useDuplicateJob,
  useFindings,
  useJob,
  useJobEventHistory,
  useProject,
  useRetryJob,
  useWarnings,
} from "../api/hooks";
import { requestText } from "../api/client";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  CopyButton,
  EmptyState,
  ErrorState,
  Menu,
  Skeleton,
  StatusDot,
  toast,
} from "../components/ui";
import {
  IconDownload,
  IconWarning,
} from "../components/ui/icons";
import {
  formatDateTime,
  formatDuration,
  formatTokens,
  relativeTime,
} from "../lib/format";
import { jobTargetLabel, MODE_LABEL, STATUS_LABEL, STATUS_TONE } from "../lib/status";
import { TERMINAL_STATUSES, type Finding, type JobWarning } from "../types";
import { FindingCard } from "../features/reviews/FindingCard";
import { CommandPreviewView } from "../features/reviews/CommandPreview";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

const EXPORT_FORMATS = [
  { value: "md", label: "Markdown (.md)" },
  { value: "json", label: "JSON (.json)" },
  { value: "csv", label: "CSV (.csv)" },
  { value: "jsonl", label: "JSONL (.jsonl)" },
  { value: "txt", label: "Plain text (.txt)" },
  { value: "agent-prompt", label: "Agent prompt (.md)" },
  { value: "github-summary", label: "GitHub review summary (.md)" },
];

function downloadFile(filename: string, content: string, type = "text/plain") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function groupByFile(findings: Finding[]) {
  const map = new Map<string, Finding[]>();
  for (const f of findings) {
    const list = map.get(f.path) ?? [];
    list.push(f);
    map.set(f.path, list);
  }
  return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length);
}

function FileGroup({
  path,
  findings,
  warnings,
}: {
  path: string;
  findings: Finding[];
  warnings: JobWarning[];
}) {
  const [open, setOpen] = useState(true);
  const fileWarnings = warnings.filter((w) => w.file === path);
  return (
    <div className={styles.fileGroup}>
      <button
        type="button"
        className={styles.fileGroupHeader}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <code className={layout.monoPath} style={{ fontSize: 12.5, flex: 1, textAlign: "left" }}>
          {path}
        </code>
        <Badge tone={findings.length ? "accent" : "neutral"}>
          {findings.length} finding{findings.length === 1 ? "" : "s"}
        </Badge>
        {fileWarnings.length ? (
          <Badge tone="warning">{fileWarnings.length} warning{fileWarnings.length === 1 ? "" : "s"}</Badge>
        ) : null}
      </button>
      {open ? (
        <div className={styles.fileGroupBody}>
          {fileWarnings.map((w, i) => (
            <div key={i} className={styles.warningBox}>
              <IconWarning size={14} style={{ flex: "none", marginTop: 1 }} />
              <span>{w.message}</span>
            </div>
          ))}
          {findings.map((finding) => (
            <FindingCard key={finding.id} finding={finding} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ResultPage() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const job = useJob(jobId);
  const project = useProject(job.data?.project_id ?? "");
  const findings = useFindings(jobId, { limit: 500 });
  const warnings = useWarnings(jobId);
  const events = useJobEventHistory(jobId);
  const retryJob = useRetryJob();
  const duplicateJob = useDuplicateJob();
  const [stateFilter, setStateFilter] = useState("");

  const filteredFindings = useMemo(() => {
    const all = findings.data?.items ?? [];
    return stateFilter ? all.filter((f) => f.user_state === stateFilter) : all;
  }, [findings.data, stateFilter]);

  const groups = useMemo(() => groupByFile(filteredFindings), [filteredFindings]);

  const summary = job.data?.result_summary_json ?? null;
  const snapshot = job.data?.configuration_snapshot_json ?? null;
  const snapshotProvider = (snapshot?.provider as { name?: string } | null)?.name ?? null;
  const snapshotModel = (snapshot?.model as { model_id?: string } | null)?.model_id ?? null;

  const queueWait = useMemo(() => {
    if (!job.data?.queued_at || !job.data?.started_at) return null;
    return formatDuration(job.data.queued_at, job.data.started_at);
  }, [job.data]);

  const phaseCount = useMemo(() => {
    const phases = (events.data ?? []).filter((e) => e.event_type === "job.phase").length;
    return phases || null;
  }, [events.data]);

  if (job.isLoading) {
    return (
      <div className={layout.stack}>
        <Skeleton height={36} width={400} />
        <Skeleton height={120} />
        <Skeleton height={280} />
      </div>
    );
  }

  if (job.error || !job.data) {
    return <ErrorState title="Could not load review" error={job.error} onRetry={() => job.refetch()} />;
  }

  const j = job.data;
  if (!TERMINAL_STATUSES.includes(j.status)) {
    navigate(`/jobs/${j.id}`, { replace: true });
    return null;
  }

  async function exportJob(format: string) {
    try {
      const content = await requestText(`/api/v1/jobs/${jobId}/export`, { format });
      downloadFile(`review-${jobId.slice(0, 8)}.${format === "agent-prompt" || format === "github-summary" ? "md" : format}`, content);
    } catch (err) {
      toast.error("Export failed", err instanceof Error ? err.message : undefined);
    }
  }

  const warningList = (warnings.data ?? j.warnings_json ?? []) as JobWarning[];

  return (
    <>
      <PageHeader
        title={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
            {project.data?.display_name ?? "Review"}
            <StatusDot tone={STATUS_TONE[j.status]} label={STATUS_LABEL[j.status]} />
          </span>
        }
        subtitle={`${jobTargetLabel(j)} · ${MODE_LABEL[j.mode]} review · via ${j.source}`}
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() =>
                retryJob.mutateAsync({ id: jobId }).then((nj) => {
                  toast.success("Retry queued");
                  navigate(`/jobs/${nj.id}`);
                }).catch((e: Error) => toast.error("Retry failed", e.message))
              }
            >
              Retry
            </Button>
            <Menu
              ariaLabel="Export and more actions"
              trigger={
                <Button variant="secondary">
                  <IconDownload size={14} /> Export
                </Button>
              }
              items={[
                { key: "copy-md", label: "Copy as Markdown", onSelect: () => void requestText(`/api/v1/jobs/${jobId}/export`, { format: "md" }).then((t) => navigator.clipboard.writeText(t)).then(() => toast.success("Copied report as Markdown")) },
                { key: "copy-json", label: "Copy as JSON", onSelect: () => void requestText(`/api/v1/jobs/${jobId}/export`, { format: "json" }).then((t) => navigator.clipboard.writeText(t)).then(() => toast.success("Copied report as JSON")) },
                { key: "sep", label: "", type: "separator" },
                ...EXPORT_FORMATS.map((f) => ({
                  key: f.value,
                  label: f.label,
                  onSelect: () => void exportJob(f.value),
                })),
                { key: "sep2", label: "", type: "separator" },
                {
                  key: "duplicate",
                  label: "Duplicate job",
                  onSelect: () =>
                    void duplicateJob.mutateAsync({ id: jobId }).then((nj) => {
                      toast.success("Duplicated into queue");
                      navigate(`/jobs/${nj.id}`);
                    }),
                },
                {
                  key: "session",
                  label: "Open session inspector",
                  onSelect: () => navigate(`/reviews/${jobId}/session`),
                },
              ]}
            />
          </>
        }
      />

      <div className={`${layout.stack} ${layout.stackLg}`}>
        {/* Stats header (SPEC §15) */}
        <section className={`${layout.section} ${layout.sectionTight}`} aria-label="Review summary">
          <div className={layout.grid2} style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 24 }}>
            <dl className={layout.dl}>
              <dt>Files reviewed</dt>
              <dd>{summary?.files_reviewed ?? "—"}</dd>
              <dt>Findings</dt>
              <dd>{summary?.comments ?? j.findings_count}</dd>
              <dt>Warnings</dt>
              <dd>{warningList.length}</dd>
              <dt>Duration</dt>
              <dd>{formatDuration(j.started_at, j.completed_at)}</dd>
              <dt>Queue wait</dt>
              <dd>{queueWait ?? "—"}</dd>
            </dl>
            <dl className={layout.dl}>
              <dt>Provider / model</dt>
              <dd>
                {snapshotProvider ?? "—"}
                {snapshotModel ? ` · ${snapshotModel}` : ""}
              </dd>
              <dt>Tokens</dt>
              <dd>
                {formatTokens(summary?.total_tokens)} total
                {summary?.input_tokens != null ? ` · ${formatTokens(summary.input_tokens)} in` : ""}
                {summary?.output_tokens != null ? ` · ${formatTokens(summary.output_tokens)} out` : ""}
              </dd>
              {(summary?.cache_read_tokens != null || summary?.cache_write_tokens != null) ? (
                <>
                  <dt>Cache tokens</dt>
                  <dd>
                    {formatTokens(summary?.cache_read_tokens)} read · {formatTokens(summary?.cache_write_tokens)} write
                  </dd>
                </>
              ) : null}
              <dt>OCR version</dt>
              <dd>{j.ocr_version ?? "—"}</dd>
              <dt>Session</dt>
              <dd style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <code className={layout.monoPath} style={{ fontSize: 12 }}>
                  {j.ocr_session_id ?? "—"}
                </code>
                {j.ocr_session_id ? <CopyButton text={j.ocr_session_id} aria-label="Copy session id" /> : null}
              </dd>
              <dt>Completed</dt>
              <dd>{formatDateTime(j.completed_at)}</dd>
            </dl>
          </div>
          {phaseCount != null ? (
            <p className={layout.small} style={{ marginTop: 8 }}>
              {phaseCount} planning phases recorded.{" "}
              <Link to={`/reviews/${jobId}/session`}>Inspect the raw OCR session</Link>.
            </p>
          ) : null}
        </section>

        {j.status_message ? (
          <div className={styles.warningBox} role="status">
            <IconWarning size={14} style={{ flex: "none", marginTop: 1 }} />
            <span>{j.status_message}</span>
          </div>
        ) : null}

        {warningList.length > 0 && warningList.every((w) => !w.file) ? (
          <section className={`${layout.section} ${layout.sectionTight}`} aria-label="Warnings">
            <h2 className={layout.sectionTitle}>Warnings</h2>
            <div className={layout.stack} style={{ gap: 6 }}>
              {warningList.map((w, i) => (
                <div key={i} className={styles.warningBox}>
                  <IconWarning size={14} style={{ flex: "none", marginTop: 1 }} />
                  <span>{w.message}</span>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <section aria-label="Findings">
          <div className={layout.sectionHeader}>
            <h2 className={layout.sectionTitle} style={{ margin: 0 }}>
              Findings by file
            </h2>
            <select
              aria-label="Filter by finding state"
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              style={{
                height: 28,
                borderRadius: 6,
                border: "1px solid var(--border-strong)",
                background: "var(--bg-surface)",
                color: "var(--text-primary)",
                padding: "0 10px",
                font: "var(--text-body)",
                fontSize: 12.5,
              }}
            >
              <option value="">All states</option>
              <option value="unreviewed">Unreviewed</option>
              <option value="accepted">Accepted</option>
              <option value="dismissed">Dismissed</option>
              <option value="needs_followup">Needs follow-up</option>
            </select>
          </div>

          {findings.isLoading ? (
            <div className={layout.stack}>
              <Skeleton height={120} />
              <Skeleton height={120} />
            </div>
          ) : groups.length === 0 ? (
            <div className={layout.section}>
              <EmptyState
                title={stateFilter ? "No findings in this state" : "No findings"}
                body={
                  stateFilter
                    ? "Change the state filter to see other findings."
                    : j.status === "completed" || j.status === "completed_with_warnings"
                      ? "OCR completed the review without raising findings."
                      : "This job did not produce findings."
                }
              />
            </div>
          ) : (
            <div className={layout.stack}>
              {groups.map(([path, list]) => (
                <FileGroup
                  key={path}
                  path={path}
                  findings={list}
                  warnings={warningList}
                />
              ))}
            </div>
          )}
          {findings.data && findings.data.total > (findings.data.items.length || 0) ? (
            <p className={layout.small} style={{ marginTop: 8 }}>
              Showing {findings.data.items.length} of {findings.data.total} findings.
            </p>
          ) : null}
        </section>

        {j.generated_command_json ? (
          <section aria-label="Generated command">
            <h2 className={layout.sectionTitle}>Generated command</h2>
            <CommandPreviewView
              preview={{
                executable: j.generated_command_json.executable ?? "ocr",
                argv: j.generated_command_json.argv,
                env: j.generated_command_json.env,
                cwd: j.generated_command_json.cwd ?? "—",
              }}
              title="Executed command (recorded at queue time)"
            />
          </section>
        ) : null}

        <p className={layout.small}>
          Queued {relativeTime(j.queued_at)}
          {j.retry_of_job_id ? " · retry of an earlier job" : ""}
          {j.resume_from_session_id ? " · resumed from a previous OCR session" : ""}
        </p>
      </div>
    </>
  );
}
