/**
 * Queue (SPEC §12, §20) — operator workspace: header controls, queued jobs,
 * active jobs, recently completed with inline findings expansion.
 * Reorder commits only on a valid drop and reverts on API failure.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  useCancelJob,
  useClearCompleted,
  useDuplicateJob,
  useFindings,
  useJobs,
  useMoveJob,
  usePauseJob,
  usePauseQueue,
  useProjects,
  useQueue,
  useReorderQueue,
  useResumePausedJob,
  useResumeQueue,
  useRetryJob,
} from "../api/hooks";
import { useSpeedLearner } from "../hooks/use-speed-learner";
import { PageHeader } from "../layouts/AppLayout";
import {
  Button,
  ConfirmDialog,
  Menu,
  Skeleton,
  StatusDot,
  toast,
} from "../components/ui";
import {
  IconGrip,
  IconMore,
  IconPause,
  IconPlay,
  IconQueue,
} from "../components/ui/icons";
import { formatDateTime } from "../lib/format";
import { jobTargetLabel, MODE_LABEL, STATUS_LABEL, STATUS_TONE } from "../lib/status";
import { TERMINAL_STATUSES, type Job } from "../types";
import { FindingCard } from "../features/reviews/FindingCard";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

function jobKey(job: Job) {
  return job.id;
}

/** Inline findings expansion for completed jobs in the queue. */
function ExpandedFindings({ jobId }: { jobId: string }) {
  const findings = useFindings(jobId, { limit: 500 });
  if (findings.isLoading) {
    return (
      <div className={styles.queueExpandBody}>
        <Skeleton height={80} />
      </div>
    );
  }
  if (findings.error) {
    return (
      <div className={styles.queueExpandBody}>
        <p className={layout.small} style={{ color: "var(--danger)" }}>
          Could not load findings.
        </p>
      </div>
    );
  }
  const items = findings.data?.items ?? [];
  if (items.length === 0) {
    return (
      <div className={styles.queueExpandBody}>
        <p className={layout.small}>No findings recorded.</p>
      </div>
    );
  }
  return (
    <div className={styles.queueExpandBody}>
      <div className={layout.stack} style={{ gap: 8 }}>
        {items.map((f) => (
          <FindingCard key={f.id} finding={f} />
        ))}
      </div>
    </div>
  );
}

export function QueuePage() {
  const queue = useQueue();
  const recent = useJobs({ limit: 15 }, { refetchInterval: 5_000 });
  const projects = useProjects();
  const navigate = useNavigate();

  const pauseQueue = usePauseQueue();
  const resumeQueue = useResumeQueue();
  const clearCompleted = useClearCompleted();
  const reorder = useReorderQueue();
  const moveJob = useMoveJob();
  const cancelJob = useCancelJob();
  const retryJob = useRetryJob();
  const duplicateJob = useDuplicateJob();
  const pauseJob = usePauseJob();
  const resumePaused = useResumePausedJob();
  const { eta } = useSpeedLearner();

  const [optimisticOrder, setOptimisticOrder] = useState<string[] | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{ id: string; position: "before" | "after" } | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const [cancelTarget, setCancelTarget] = useState<Job | null>(null);
  const [expandedJob, setExpandedJob] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const announceTimer = useRef<number | null>(null);

  const projectName = (id: string) =>
    projects.data?.find((p) => p.id === id)?.display_name ?? "Unknown project";

  function announce(message: string) {
    setAnnouncement(message);
    if (announceTimer.current) window.clearTimeout(announceTimer.current);
    announceTimer.current = window.setTimeout(() => setAnnouncement(""), 4000);
  }

  const serverQueued = useMemo(
    () => (queue.data?.jobs ?? []).filter((j) => j.status === "queued"),
    [queue.data],
  );
  const activeJobs = useMemo(
    () =>
      (queue.data?.jobs ?? []).filter(
        (j) => j.status === "running" || j.status === "preparing" || j.status === "cancelling",
      ),
    [queue.data],
  );
  const completedJobs = useMemo(
    () => (recent.data?.items ?? []).filter((j) => TERMINAL_STATUSES.includes(j.status)),
    [recent.data],
  );

  // Drop optimistic state once the server confirms a new order.
  useEffect(() => {
    if (optimisticOrder) {
      const serverIds = serverQueued.map(jobKey).join(",");
      if (serverIds === optimisticOrder.join(",")) setOptimisticOrder(null);
    }
  }, [serverQueued, optimisticOrder]);

  const queuedJobs = useMemo(() => {
    if (!optimisticOrder) return serverQueued;
    const byId = new Map(serverQueued.map((j) => [j.id, j]));
    const ordered = optimisticOrder
      .map((id) => byId.get(id))
      .filter((j): j is Job => Boolean(j));
    // Include any new jobs not in the optimistic snapshot at the end.
    for (const job of serverQueued) {
      if (!optimisticOrder.includes(job.id)) ordered.push(job);
    }
    return ordered;
  }, [serverQueued, optimisticOrder]);

  async function commitOrder(ids: string[]) {
    setOptimisticOrder(ids);
    try {
      await reorder.mutateAsync(ids);
      announce("Queue order updated.");
    } catch (err) {
      setOptimisticOrder(null);
      toast.error(
        "Reorder failed — order restored",
        err instanceof Error ? err.message : undefined,
      );
      announce("Reorder failed; the queue order was restored.");
    }
  }

  function onDrop(targetId: string, position: "before" | "after") {
    if (!dragId || dragId === targetId) return;
    const ids = queuedJobs.map((j) => j.id).filter((id) => id !== dragId);
    let index = ids.indexOf(targetId);
    if (index === -1) return;
    if (position === "after") index += 1;
    ids.splice(index, 0, dragId);
    void commitOrder(ids);
    setDragId(null);
    setDropTarget(null);
  }

  async function quickMove(job: Job, action: "top" | "up" | "down") {
    try {
      await moveJob.mutateAsync({ id: job.id, body: { action } });
      announce(`Moved ${projectName(job.project_id)} ${action === "top" ? "to the top" : action}.`);
    } catch (err) {
      toast.error("Move failed", err instanceof Error ? err.message : undefined);
    }
  }

  async function toggleQueuePaused() {
    try {
      if (queue.data?.paused) {
        await resumeQueue.mutateAsync();
        announce("Queue resumed.");
      } else {
        await pauseQueue.mutateAsync();
        announce("Queue paused. Running jobs finish; queued jobs wait.");
      }
    } catch (err) {
      toast.error("Queue control failed", err instanceof Error ? err.message : undefined);
    }
  }

  function rowActions(job: Job) {
    const isQueued = job.status === "queued";
    return [
      ...(isQueued
        ? [
            { key: "top", label: "Move to top", onSelect: () => void quickMove(job, "top") },
            { key: "up", label: "Move up", onSelect: () => void quickMove(job, "up") },
            { key: "down", label: "Move down", onSelect: () => void quickMove(job, "down") },
            job.paused
              ? {
                  key: "resume",
                  label: "Resume job",
                  onSelect: () =>
                    void resumePaused
                      .mutateAsync({ id: job.id })
                      .then(() => announce("Job resumed."))
                      .catch((e: Error) => toast.error("Resume failed", e.message)),
                }
              : {
                  key: "pause",
                  label: "Pause job",
                  onSelect: () =>
                    void pauseJob
                      .mutateAsync({ id: job.id })
                      .then(() => announce("Job paused."))
                      .catch((e: Error) => toast.error("Pause failed", e.message)),
                },
          ]
        : []),
      {
        key: "logs",
        label: "Logs",
        onSelect: () => navigate(`/reviews/${job.id}/logs`),
      },
      {
        key: "duplicate",
        label: "Duplicate",
        onSelect: () =>
          void duplicateJob
            .mutateAsync({ id: job.id })
            .then(() => toast.success("Job duplicated"))
            .catch((e: Error) => toast.error("Duplicate failed", e.message)),
      },
      ...(job.status === "failed" || job.status === "cancelled" || job.status === "interrupted"
        ? [
            {
              key: "retry",
              label: "Retry",
              onSelect: () =>
                void retryJob
                  .mutateAsync({ id: job.id })
                  .then(() => toast.success("Retry queued"))
                  .catch((e: Error) => toast.error("Retry failed", e.message)),
            },
          ]
        : []),
      { key: "sep", label: "", type: "separator" as const },
      {
        key: "cancel",
        label: job.status === "queued" ? "Remove from queue" : "Cancel",
        danger: true,
        onSelect: () => setCancelTarget(job),
      },
    ];
  }

  return (
    <>
      {/* Screen-reader announcements for queue status changes (SPEC §26) */}
      <div aria-live="polite" role="status" className="visually-hidden">
        {announcement}
      </div>

      <PageHeader
        title="Queue"
        subtitle="Durable review queue — reorder, pause, cancel, retry."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={toggleQueuePaused}
              disabled={pauseQueue.isPending || resumeQueue.isPending}
            >
              {queue.data?.paused ? (
                <>
                  <IconPlay size={14} /> Resume queue
                </>
              ) : (
                <>
                  <IconPause size={14} /> Pause queue
                </>
              )}
            </Button>
            <Button variant="tertiary" onClick={() => setClearOpen(true)}>
              Clear completed
            </Button>
          </>
        }
      />

      {queue.data?.paused ? (
        <div className={styles.warningBox} role="status" style={{ marginBottom: 16 }}>
          <span>The queue is paused. Running jobs continue; queued jobs will not start until you resume.</span>
        </div>
      ) : null}

      {queue.error ? (
        <div className={layout.section}>
          <p className={layout.small} style={{ color: "var(--danger)" }}>
            Could not load the queue.
          </p>
        </div>
      ) : queue.isLoading ? (
        <div className={layout.stack}>
          <Skeleton height={44} />
          <Skeleton height={44} />
          <Skeleton height={44} />
        </div>
      ) : (
        <>
          {/* QUEUE — top, grows as items arrive */}
          <h2 className={styles.queueSectionTitle}>
            Queued — {queuedJobs.length}
            {optimisticOrder ? <span style={{ textTransform: "none" }}>(saving order…)</span> : null}
            {eta ? <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>(ETA: ~{eta})</span> : null}
          </h2>
          {queuedJobs.length === 0 ? (
            <div className={styles.queuePlaceholder}>
              <IconQueue size={16} />
              <span>Queue is empty</span>
            </div>
          ) : (
            <div
              className={styles.queueRows}
              role="list"
              aria-label="Queued jobs in execution order"
            >
              {queuedJobs.map((job) => (
                <div
                  key={job.id}
                  role="listitem"
                  className={[
                    styles.queueRow,
                    dragId === job.id ? styles.queueRowDragging : "",
                    dropTarget?.id === job.id
                      ? dropTarget.position === "before"
                        ? styles.queueRowDropBefore
                        : styles.queueRowDropAfter
                      : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  draggable
                  onDragStart={(e) => {
                    setDragId(job.id);
                    e.dataTransfer.effectAllowed = "move";
                    e.dataTransfer.setData("text/plain", job.id);
                  }}
                  onDragEnd={() => {
                    setDragId(null);
                    setDropTarget(null);
                  }}
                  onDragOver={(e) => {
                    if (!dragId || dragId === job.id) return;
                    e.preventDefault();
                    const rect = e.currentTarget.getBoundingClientRect();
                    const position =
                      e.clientY < rect.top + rect.height / 2 ? "before" : "after";
                    setDropTarget({ id: job.id, position });
                  }}
                  onDragLeave={() => {
                    setDropTarget((prev) => (prev?.id === job.id ? null : prev));
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    const target = dropTarget;
                    if (target) onDrop(target.id, target.position);
                  }}
                >
                  <span
                    className={styles.dragHandle}
                    aria-label={`Drag to reorder ${projectName(job.project_id)} — keyboard alternatives in the row menu`}
                    title="Drag to reorder"
                  >
                    <IconGrip size={14} />
                  </span>
                  {job.paused ? (
                    <span className={layout.small} style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                      paused
                    </span>
                  ) : null}
                  <Link to={`/jobs/${job.id}`} className={styles.ellipsize} style={{ color: "var(--text-primary)" }}>
                    {projectName(job.project_id)}
                  </Link>
                  <span className={`${styles.ellipsize} ${layout.small}`}>{jobTargetLabel(job)}</span>
                  <span className={`${styles.ellipsize} ${layout.small} ${styles.queueRowHideMobile}`}>
                    {MODE_LABEL[job.mode]} · via {job.source}
                  </span>
                  <div className={`${styles.ellipsize} ${layout.small} ${styles.queueRowHideMobile}`} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <StatusDot tone="muted" label={job.paused ? "Paused" : "Queued"} />
                    <span>{formatDateTime(job.queued_at)}</span>
                  </div>
                  <Menu
                    ariaLabel={`Actions for ${projectName(job.project_id)}`}
                    trigger={
                      <Button variant="tertiary" size="small" aria-label="Job actions">
                        <IconMore size={15} />
                      </Button>
                    }
                    items={rowActions(job)}
                  />
                </div>
              ))}
            </div>
          )}

          {/* ACTIVE — middle */}
          <h2 className={styles.queueSectionTitle}>
            Active — {activeJobs.length}
          </h2>
          {activeJobs.length === 0 ? (
            <p className={layout.small}>Nothing running.</p>
          ) : (
            <div className={styles.queueRows}>
              {activeJobs.map((job) => (
                <div key={job.id} className={styles.queueRow} style={{ gridTemplateColumns: "24px minmax(0,2fr) minmax(0,2fr) minmax(0,1.4fr) minmax(0,1fr) auto 32px" }}>
                  <span />
                  <Link to={`/jobs/${job.id}`} className={styles.ellipsize} style={{ color: "var(--text-primary)" }}>
                    {projectName(job.project_id)}
                  </Link>
                  <span className={`${styles.ellipsize} ${layout.small}`}>{jobTargetLabel(job)}</span>
                  <span className={`${styles.ellipsize} ${layout.small} ${styles.queueRowHideMobile}`}>
                    {MODE_LABEL[job.mode]} · {job.source}
                  </span>
                  <div className={`${styles.ellipsize} ${layout.small} ${styles.queueRowHideMobile}`} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <StatusDot tone={STATUS_TONE[job.status]} label={STATUS_LABEL[job.status]} pulse />
                    <span>{formatDateTime(job.started_at ?? job.queued_at)}</span>
                  </div>
                  <span style={{ width: 0 }} />
                  <Menu
                    ariaLabel={`Actions for ${projectName(job.project_id)}`}
                    trigger={
                      <Button variant="tertiary" size="small" aria-label="Job actions">
                        <IconMore size={15} />
                      </Button>
                    }
                    items={rowActions(job)}
                  />
                </div>
              ))}
            </div>
          )}

          {/* COMPLETED — bottom, expandable */}
          <h2 className={styles.queueSectionTitle}>
            Recently completed — {completedJobs.length}
          </h2>
          {completedJobs.length === 0 ? (
            <p className={layout.small}>No finished jobs yet.</p>
          ) : (
            <div className={styles.queueRows}>
              {completedJobs.slice(0, 8).map((job) => {
                const isExpanded = expandedJob === job.id;
                return (
                  <div key={job.id}>
                    <div
                      className={[
                        styles.queueRow,
                        styles.queueRowClickable,
                        isExpanded ? styles.queueRowExpanded : "",
                      ].filter(Boolean).join(" ")}
                      style={{ gridTemplateColumns: "24px minmax(0,2fr) minmax(0,2fr) minmax(0,1.4fr) minmax(0,1fr) auto 32px" }}
                      onClick={() => setExpandedJob(isExpanded ? null : job.id)}
                    >
                      <span />
                      <Link
                        to={`/reviews/${job.id}`}
                        className={styles.ellipsize}
                        style={{ color: "var(--text-primary)" }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {projectName(job.project_id)}
                      </Link>
                      <span className={`${styles.ellipsize} ${layout.small}`}>
                        {jobTargetLabel(job)} · {job.findings_count} findings
                      </span>
                      <span className={`${styles.ellipsize} ${layout.small} ${styles.queueRowHideMobile}`}>
                        {MODE_LABEL[job.mode]} · via {job.source}
                      </span>
                      <div className={`${styles.ellipsize} ${layout.small} ${styles.queueRowHideMobile}`} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <StatusDot
                          tone={STATUS_TONE[job.status]}
                          label={STATUS_LABEL[job.status]}
                          title={job.error_code ? `Error: ${job.error_code}${job.status_message ? ` — ${job.status_message}` : ""}` : undefined}
                        />
                        <span>{formatDateTime(job.completed_at)}</span>
                      </div>
                      <span style={{ width: 0 }} />
                      <div onClick={(e) => e.stopPropagation()}>
                        <Menu
                          ariaLabel={`Actions for ${projectName(job.project_id)}`}
                          trigger={
                            <Button variant="tertiary" size="small" aria-label="Job actions">
                              <IconMore size={15} />
                            </Button>
                          }
                          items={rowActions(job)}
                        />
                      </div>
                    </div>
                    {isExpanded ? <ExpandedFindings jobId={job.id} /> : null}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      <ConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="Clear completed jobs"
        description="Remove all completed, failed, and cancelled jobs from the queue history? Job artifacts on disk are kept according to retention settings."
        confirmLabel="Clear completed"
        destructive
        busy={clearCompleted.isPending}
        onConfirm={async () => {
          try {
            const result = await clearCompleted.mutateAsync();
            toast.success(`Removed ${result.removed} job${result.removed === 1 ? "" : "s"}`);
            setClearOpen(false);
          } catch (err) {
            toast.error("Clear failed", err instanceof Error ? err.message : undefined);
          }
        }}
      />

      <ConfirmDialog
        open={cancelTarget !== null}
        onOpenChange={(open) => {
          if (!open) setCancelTarget(null);
        }}
        title={cancelTarget?.status === "queued" ? "Remove from queue" : "Cancel job"}
        description={
          cancelTarget?.status === "queued"
            ? "Remove this job from the queue? It will be marked cancelled."
            : "Request cancellation? OCR receives a graceful termination signal; partial logs and session artifacts are preserved."
        }
        confirmLabel={cancelTarget?.status === "queued" ? "Remove" : "Cancel job"}
        destructive
        busy={cancelJob.isPending}
        onConfirm={async () => {
          if (!cancelTarget) return;
          try {
            await cancelJob.mutateAsync({ id: cancelTarget.id });
            announce(`Cancelled ${projectName(cancelTarget.project_id)}.`);
            setCancelTarget(null);
          } catch (err) {
            toast.error("Cancel failed", err instanceof Error ? err.message : undefined);
          }
        }}
      />
    </>
  );
}
