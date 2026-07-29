/** Active job detail (SPEC §14, §33.9) — SSE-driven live progress. */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useCancelJob, useJob, useProject } from "../api/hooks";
import { useJobEvents } from "../hooks/useJobEvents";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  ConfirmDialog,
  ErrorState,
  Skeleton,
  StatusDot,
} from "../components/ui";
import { relativeTime } from "../lib/format";
import { jobTargetLabel, STATUS_LABEL, STATUS_TONE } from "../lib/status";
import { TERMINAL_STATUSES } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

export function JobLivePage() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const job = useJob(jobId, { refetchInterval: 15_000 });
  const project = useProject(job.data?.project_id ?? "");
  const cancelJob = useCancelJob();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const logRef = useRef<HTMLDivElement | null>(null);

  const isTerminal = job.data ? TERMINAL_STATUSES.includes(job.data.status) : false;
  const live = useJobEvents(jobId, Boolean(job.data) && !isTerminal);

  // Terminal jobs belong on the result page.
  useEffect(() => {
    if (isTerminal && job.data) {
      navigate(`/reviews/${job.data.id}`, { replace: true });
    }
  }, [isTerminal, job.data, navigate]);

  useEffect(() => {
    if (autoScroll && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [live.log, autoScroll]);

  const files = useMemo(() => Array.from(live.files.values()), [live.files]);
  const completedCount = files.filter((f) => f.state === "completed").length;
  const liveStatus = live.status ?? job.data?.status ?? null;

  if (job.isLoading) {
    return (
      <div className={layout.stack}>
        <Skeleton height={36} width={380} />
        <Skeleton height={220} />
      </div>
    );
  }

  if (job.error || !job.data) {
    return <ErrorState title="Could not load job" error={job.error} onRetry={() => job.refetch()} />;
  }

  const j = job.data;

  return (
    <>
      <div aria-live="polite" role="status" className="visually-hidden">
        {liveStatus ? `Job status: ${STATUS_LABEL[liveStatus as keyof typeof STATUS_LABEL] ?? liveStatus}` : ""}
      </div>

      <PageHeader
        title={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
            {project.data?.display_name ?? "Review"}
            {liveStatus ? (
              <StatusDot
                tone={STATUS_TONE[liveStatus as keyof typeof STATUS_TONE] ?? "muted"}
                label={STATUS_LABEL[liveStatus as keyof typeof STATUS_LABEL] ?? liveStatus}
                pulse={!isTerminal}
              />
            ) : null}
          </span>
        }
        subtitle={jobTargetLabel(j)}
        actions={
          <>
            <Badge tone={live.connected ? "success" : "neutral"}>
              {live.connected ? "Live" : isTerminal ? "Finished" : "Reconnecting…"}
            </Badge>
            <Button variant="destructive-quiet" onClick={() => setCancelOpen(true)}>
              Cancel review
            </Button>
          </>
        }
      />

      <div className={`${layout.stack} ${layout.stackLg}`}>
        {j.status_message ? (
          <div
            className={styles.warningBox}
            role="status"
            title={j.error_code ? `Error: ${j.error_code}` : undefined}
          >
            <span>{j.status_message}</span>
            {j.error_code ? (
              <span className={layout.small} style={{ display: "block", marginTop: 4, color: "var(--text-tertiary)" }}>
                Error code: {j.error_code}
              </span>
            ) : null}
          </div>
        ) : null}

        {live.warnings.length > 0 ? (
          <section className={`${layout.section} ${layout.sectionTight}`} aria-label="Warnings">
            <h2 className={layout.sectionTitle}>Warnings</h2>
            <div className={layout.stack} style={{ gap: 6 }}>
              {live.warnings.map((w, i) => (
                <div key={i} className={styles.warningBox}>
                  <span>{w}</span>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <section className={`${layout.section} ${layout.sectionTight}`} aria-label="Progress">
          <div className={layout.sectionHeader}>
            <h2 className={layout.sectionTitle} style={{ margin: 0 }}>
              Progress
            </h2>
            <span className={layout.small}>
              {live.phase ? `Phase: ${live.phase} · ` : ""}
              {completedCount} of {files.length || "…"} files
            </span>
          </div>
          <div className={styles.progressBar} aria-hidden="true">
            <div
              className={styles.progressFill}
              style={{
                width: files.length
                  ? `${Math.round((completedCount / files.length) * 100)}%`
                  : "8%",
              }}
            />
          </div>
          {files.length > 0 ? (
            <ul style={{ maxHeight: 220, overflowY: "auto", marginTop: 12 }}>
              {files.map((file) => (
                <li key={file.path} className={styles.fileProgress}>
                  <StatusDot
                    tone={file.state === "completed" ? "ok" : "accent"}
                    label=""
                  />
                  <span className={styles.fileProgressPath}>{file.path}</span>
                  <span className={layout.small}>
                    {file.state === "completed"
                      ? `${file.comments ?? 0} comment${file.comments === 1 ? "" : "s"}`
                      : "reviewing…"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={layout.small} style={{ marginTop: 12 }}>
              Waiting for OCR to report per-file progress…
            </p>
          )}
        </section>

        <section aria-label="Live log">
          <div className={layout.sectionHeader}>
            <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Log tail</h2>
            <label className={layout.small} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              Follow output
            </label>
          </div>
          <div
            ref={logRef}
            className={styles.logTail}
            role="log"
            aria-label="Job log output"
            tabIndex={0}
          >
            {live.log.length === 0 ? (
              <span style={{ color: "var(--text-tertiary)" }}>
                No output yet — OCR writes progress here as it runs.
              </span>
            ) : (
              live.log.map((line, i) => (
                <div
                  key={i}
                  className={line.stream === "stderr" ? styles.logLineStderr : undefined}
                >
                  {line.text}
                </div>
              ))
            )}
          </div>
        </section>

        <div className={layout.row}>
          <span className={layout.small}>
            Queued {relativeTime(j.queued_at)} · priority {j.priority} · via {j.source}
            {j.ocr_session_id ? ` · session ${j.ocr_session_id.slice(0, 8)}` : ""}
          </span>
        </div>
      </div>

      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title="Cancel this review"
        description="OCR receives a graceful termination signal and is force-killed after the grace period if needed. Partial logs and session artifacts are preserved."
        confirmLabel="Cancel review"
        destructive
        busy={cancelJob.isPending}
        onConfirm={async () => {
          try {
            await cancelJob.mutateAsync({ id: jobId });
            setCancelOpen(false);
          } catch {
            setCancelOpen(false);
          }
        }}
      />
    </>
  );
}
