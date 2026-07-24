/**
 * Queue (SPEC §12, §20) — operator workspace: header controls, active jobs,
 * compact queued rows with drag-and-drop + keyboard alternatives, recently
 * completed. Reorder commits only on a valid drop and reverts on API failure.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  useCancelJob,
  useClearCompleted,
  useDuplicateJob,
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
import { PageHeader } from "../layouts/AppLayout";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
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
import { relativeTime } from "../lib/format";
import { jobTargetLabel, MODE_LABEL, STATUS_LABEL, STATUS_TONE } from "../lib/status";
import { TERMINAL_STATUSES, type Job } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

function jobKey(job: Job) {
  return job.id;
}

export function QueuePage() {
  const queue = useQueue({ refetchInterval: 6_000 });
  const recent = useJobs({ limit: 15 });
  const projects = useProjects();

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

  const [optimisticOrder, setOptimisticOrder] = useState<string[] | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{ id: string; position: "before" | "after" } | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const [cancelTarget, setCancelTarget] = useState<Job | null>(null);
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
        <ErrorState title="Could not load the queue" error={queue.error} onRetry={() => queue.refetch()} />
      ) : queue.isLoading ? (
        <div className={layout.stack}>
          <Skeleton height={44} />
          <Skeleton height={44} />
          <Skeleton height={44} />
        </div>
      ) : (
        <>
          <h2 className={styles.queueSectionTitle}>
            Active — {activeJobs.length}
          </h2>
          {activeJobs.length === 0 ? (
            <p className={layout.small}>Nothing running.</p>
          ) : (
            <div className={styles.queueRows}>
              {activeJobs.map((job) => (
                <div key={job.id} className={styles.queueRow} style={{ gridTemplateColumns: "24px 52px minmax(0,2fr) minmax(0,2fr) minmax(0,1.4fr) minmax(0,1fr) auto 32px" }}>
                  <span />
                  <span className={styles.priority}>{job.priority}</span>
                  <Link to={`/jobs/${job.id}`} className={styles.ellipsize} style={{ color: "var(--text-primary)" }}>
                    {projectName(job.project_id)}
                  </Link>
                  <span className={`${styles.ellipsize} ${layout.small}`}>{jobTargetLabel(job)}</span>
                  <span className={`${styles.ellipsize} ${layout.small} ${styles.queueRowHideMobile}`}>
                    {MODE_LABEL[job.mode]} · {job.source}
                  </span>
                  <StatusDot tone={STATUS_TONE[job.status]} label={STATUS_LABEL[job.status]} pulse />
                  <span className={`${layout.small} ${styles.queueRowHideMobile}`}>
                    {relativeTime(job.started_at ?? job.queued_at)}
                  </span>
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

          <h2 className={styles.queueSectionTitle}>
            Queued — {queuedJobs.length}
            {optimisticOrder ? <span style={{ textTransform: "none" }}>(saving order…)</span> : null}
          </h2>
          {queuedJobs.length === 0 ? (
            <div className={layout.section}>
              <EmptyState
                icon={<IconQueue size={28} />}
                title="Queue is empty"
                body="Start a review from a project page and it will appear here."
                action={
                  <Link to="/reviews/new">
                    <Button variant="primary" size="small">New review</Button>
                  </Link>
                }
              />
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
                  <span className={styles.priority} aria-label={`priority ${job.priority}`}>
                    {job.priority}
                    {job.paused ? (
                      <span className={layout.small} style={{ display: "block", fontSize: 10 }}>
                        paused
                      </span>
                    ) : null}
                  </span>
                  <Link to={`/jobs/${job.id}`} className={styles.ellipsize} style={{ color: "var(--text-primary)" }}>
                    {projectName(job.project_id)}
                  </Link>
                  <span className={`${styles.ellipsize} ${layout.small}`}>{jobTargetLabel(job)}</span>
                  <span className={`${styles.ellipsize} ${layout.small} ${styles.queueRowHideMobile}`}>
                    {MODE_LABEL[job.mode]} · via {job.source}
                  </span>
                  <span className={`${layout.small} ${styles.queueRowHideMobile}`}>
                    {relativeTime(job.queued_at)}
                  </span>
                  <StatusDot tone="muted" label={job.paused ? "Paused" : "Queued"} />
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

          <h2 className={styles.queueSectionTitle}>
            Recently completed — {completedJobs.length}
          </h2>
          {completedJobs.length === 0 ? (
            <p className={layout.small}>No finished jobs yet.</p>
          ) : (
            <div className={styles.queueRows}>
              {completedJobs.slice(0, 8).map((job) => (
                <div key={job.id} className={styles.queueRow} style={{ gridTemplateColumns: "24px 52px minmax(0,2fr) minmax(0,2fr) minmax(0,1.4fr) minmax(0,1fr) auto 32px" }}>
                  <span />
                  <span className={styles.priority}>{job.priority}</span>
                  <Link to={`/reviews/${job.id}`} className={styles.ellipsize} style={{ color: "var(--text-primary)" }}>
                    {projectName(job.project_id)}
                  </Link>
                  <span className={`${styles.ellipsize} ${layout.small}`}>
                    {jobTargetLabel(job)} · {job.findings_count} findings
                  </span>
                  <span className={`${styles.ellipsize} ${layout.small} ${styles.queueRowHideMobile}`}>
                    {MODE_LABEL[job.mode]} · via {job.source}
                  </span>
                  <span className={`${layout.small} ${styles.queueRowHideMobile}`}>
                    {relativeTime(job.completed_at)}
                  </span>
                  <StatusDot tone={STATUS_TONE[job.status]} label={STATUS_LABEL[job.status]} />
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
