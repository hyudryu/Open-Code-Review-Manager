/** Overview (SPEC §20) — decision-focused, varied layout, no stat-card grid. */

import { Link, useNavigate } from "react-router-dom";
import { useMemo } from "react";
import {
  useJobs,
  useOcrUpdateStatus,
  useProjects,
  useProviders,
  useQueue,
  useSystemInfo,
  useSystemOcr,
} from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import { Button, EmptyState, Skeleton, StatusDot } from "../components/ui";
import { IconFolder, IconPlus } from "../components/ui/icons";
import { formatDateTime, formatDuration, relativeTime } from "../lib/format";
import { jobTargetLabel, STATUS_LABEL, STATUS_TONE } from "../lib/status";
import { TERMINAL_STATUSES, type Job } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

function FindingsTrend({ jobs }: { jobs: Job[] }) {
  const days = useMemo(() => {
    const buckets: { label: string; count: number }[] = [];
    const now = new Date();
    for (let i = 13; i >= 0; i -= 1) {
      const day = new Date(now);
      day.setDate(now.getDate() - i);
      const key = day.toDateString();
      const count = jobs
        .filter(
          (j) =>
            j.completed_at && new Date(j.completed_at).toDateString() === key,
        )
        .reduce(
          (sum, j) => sum + (j.result_summary_json?.comments ?? j.findings_count ?? 0),
          0,
        );
      buckets.push({
        label: day.toLocaleDateString(undefined, { weekday: "narrow" }),
        count,
      });
    }
    return buckets;
  }, [jobs]);

  const max = Math.max(1, ...days.map((d) => d.count));
  return (
    <div>
      <div className={styles.trend} role="img"
        aria-label={`Findings over the last 14 days, peak ${max}`}>
        {days.map((day, i) => (
          <div
            key={i}
            className={`${styles.trendBar} ${day.count === 0 ? styles.trendBarEmpty : ""}`}
            style={{ height: `${Math.max(6, (day.count / max) * 100)}%` }}
            title={`${day.count} findings`}
          />
        ))}
      </div>
      <div className={styles.trendLegend}>
        <span>{days[0]?.label}</span>
        <span>Findings · last 14 days</span>
        <span>{days[days.length - 1]?.label}</span>
      </div>
    </div>
  );
}

export function OverviewPage() {
  const navigate = useNavigate();
  const queue = useQueue({ refetchInterval: 8_000 });
  const jobs = useJobs({ limit: 50 });
  const projects = useProjects();
  const providers = useProviders();
  const ocr = useSystemOcr();
  const ocrUpdate = useOcrUpdateStatus();
  const info = useSystemInfo();

  const activeJobs = useMemo(
    () =>
      (queue.data?.jobs ?? []).filter(
        (j) => j.status === "running" || j.status === "preparing",
      ),
    [queue.data],
  );
  const queuedJobs = useMemo(
    () => (queue.data?.jobs ?? []).filter((j) => j.status === "queued"),
    [queue.data],
  );
  const recentCompleted = useMemo(
    () =>
      (jobs.data?.items ?? [])
        .filter((j) => TERMINAL_STATUSES.includes(j.status))
        .slice(0, 6),
    [jobs.data],
  );
  const attentionProjects = useMemo(
    () =>
      (projects.data ?? []).filter(
        (p) => !p.is_available || p.is_dirty,
      ),
    [projects.data],
  );

  const projectName = (id: string) =>
    projects.data?.find((p) => p.id === id)?.display_name ?? "Project";

  const emptySetup =
    projects.data && providers.data && projects.data.length === 0;

  if (emptySetup) {
    return (
      <>
        <PageHeader title="Overview" />
        <div className={layout.section}>
          <EmptyState
            icon={<IconFolder size={32} />}
            title="Set up your first review"
            body="Add a folder of Git repositories, configure an LLM provider, and create a review profile. The guided setup takes about a minute."
            action={
              <Button variant="primary" onClick={() => navigate("/setup")}>
                <IconPlus size={14} /> Start guided setup
              </Button>
            }
          />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Overview"
        actions={
          <Button variant="primary" onClick={() => navigate("/reviews/new")}>
            <IconPlus size={14} /> New review
          </Button>
        }
      />
      <div className={styles.overviewGrid}>
        <div className={styles.overviewCol}>
          {/* Active review — the one thing that matters right now */}
          <section aria-labelledby="ov-active">
            <h2 className={layout.sectionTitle} id="ov-active">Active review</h2>
            {queue.isLoading ? (
              <Skeleton height={96} />
            ) : activeJobs.length === 0 ? (
              <div className={layout.section}>
                <p className={layout.muted}>
                  Nothing is running.
                  {queuedJobs.length > 0
                    ? ` ${queuedJobs.length} job${queuedJobs.length === 1 ? "" : "s"} waiting in the queue.`
                    : " Start a review from a project page."}
                </p>
              </div>
            ) : (
              <div className={styles.activeReview}>
                {activeJobs.map((job) => (
                  <div key={job.id} style={{ display: "contents" }}>
                    <div className={styles.activeReviewTop}>
                      <Link to={`/jobs/${job.id}`} className={styles.activeReviewName}>
                        {projectName(job.project_id)}
                      </Link>
                      <StatusDot
                        tone={STATUS_TONE[job.status]}
                        label={STATUS_LABEL[job.status]}
                        pulse
                      />
                    </div>
                    <p className={layout.small}>{jobTargetLabel(job)}</p>
                    <div className={styles.progressBar} aria-hidden="true">
                      <div
                        className={`${styles.progressFill} ${styles.progressFillIndeterminate}`}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Queue strip */}
          <section aria-labelledby="ov-queue">
            <div className={layout.sectionHeader}>
              <h2 className={layout.sectionTitle} id="ov-queue" style={{ margin: 0 }}>
                Queue
              </h2>
              <Link to="/queue" className={layout.small}>Open queue</Link>
            </div>
            <div className={`${layout.section} ${layout.sectionTight}`}>
              <div className={styles.statRow}>
                <div className={styles.stat}>
                  <span className={styles.statValue}>{queuedJobs.length}</span>
                  <span className={styles.statLabel}>waiting</span>
                </div>
                <div className={styles.stat}>
                  <span className={styles.statValue}>{activeJobs.length}</span>
                  <span className={styles.statLabel}>running</span>
                </div>
                <div className={styles.stat}>
                  <span className={styles.statValue}>
                    {queue.data?.paused ? "Paused" : "Live"}
                  </span>
                  <span className={styles.statLabel}>worker</span>
                </div>
              </div>
              {queuedJobs.slice(0, 3).map((job) => (
                <div key={job.id} className={styles.compactRow}>
                  <div className={styles.compactRowMain}>
                    <span className={styles.compactRowTitle}>
                      {projectName(job.project_id)} · {jobTargetLabel(job)}
                    </span>
                    <span className={styles.compactRowMeta}>
                      priority {job.priority} · queued {relativeTime(job.queued_at)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Findings trend */}
          <section aria-labelledby="ov-trend">
            <h2 className={layout.sectionTitle} id="ov-trend">Findings trend</h2>
            <div className={`${layout.section} ${layout.sectionTight}`}>
              {jobs.isLoading ? <Skeleton height={64} /> : <FindingsTrend jobs={jobs.data?.items ?? []} />}
            </div>
          </section>

          {/* Recent completed */}
          <section aria-labelledby="ov-recent">
            <div className={layout.sectionHeader}>
              <h2 className={layout.sectionTitle} id="ov-recent" style={{ margin: 0 }}>
                Recently completed
              </h2>
              <Link to="/reviews" className={layout.small}>All reviews</Link>
            </div>
            <div className={`${layout.section} ${layout.sectionTight}`}>
              {recentCompleted.length === 0 ? (
                <p className={layout.small}>No completed reviews yet.</p>
              ) : (
                recentCompleted.map((job) => (
                  <div key={job.id} className={styles.compactRow}>
                    <div className={styles.compactRowMain}>
                      <Link to={`/reviews/${job.id}`} className={styles.compactRowTitle}>
                        {projectName(job.project_id)} · {jobTargetLabel(job)}
                      </Link>
                      <span className={styles.compactRowMeta}>
                        {job.findings_count} finding{job.findings_count === 1 ? "" : "s"} ·{" "}
                        {formatDuration(job.started_at, job.completed_at)} ·{" "}
                        {relativeTime(job.completed_at)}
                      </span>
                    </div>
                    <StatusDot
                      tone={STATUS_TONE[job.status]}
                      label={STATUS_LABEL[job.status]}
                    />
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        <div className={styles.overviewCol}>
          {/* System status */}
          <section aria-labelledby="ov-system">
            <h2 className={layout.sectionTitle} id="ov-system">System</h2>
            <div className={`${layout.section} ${layout.sectionTight} ${layout.stack}`}>
              <div className={styles.compactRow}>
                <div className={styles.compactRowMain}>
                  <span className={styles.compactRowTitle}>OpenCodeReview</span>
                  <span className={styles.compactRowMeta}>
                    {ocr.data?.binary_path ?? "Not detected — reviews cannot run"}
                  </span>
                </div>
                {ocr.data ? (
                  <StatusDot
                    tone={ocr.data.status === "ok" ? "ok" : "danger"}
                    label={ocr.data.status === "ok" ? ocr.data.version ?? "ok" : "missing"}
                  />
                ) : (
                  <StatusDot tone="muted" label="checking" />
                )}
                {ocr.data?.status === "ok" && ocrUpdate.data?.update_available && (
                  <div>
                    <span style={{ fontSize: 11, color: "var(--accent)" }}>
                      {ocrUpdate.data.latest_version} available
                    </span>
                  </div>
                )}
              </div>
              <div className={styles.compactRow}>
                <div className={styles.compactRowMain}>
                  <span className={styles.compactRowTitle}>Git</span>
                  <span className={styles.compactRowMeta}>
                    {info.data?.git_version ?? "Not detected"}
                  </span>
                </div>
                <StatusDot
                  tone={info.data?.git_version ? "ok" : "danger"}
                  label={info.data?.git_version ? "ok" : "missing"}
                />
              </div>
              <div className={styles.compactRow}>
                <div className={styles.compactRowMain}>
                  <span className={styles.compactRowTitle}>Queue worker</span>
                </div>
                <StatusDot
                  tone={info.data?.queue_worker.running ? "ok" : "warn"}
                  label={info.data?.queue_worker.running ? "running" : "stopped"}
                />
              </div>
            </div>
          </section>

          {/* Providers */}
          <section aria-labelledby="ov-providers">
            <div className={layout.sectionHeader}>
              <h2 className={layout.sectionTitle} id="ov-providers" style={{ margin: 0 }}>
                Providers
              </h2>
              <Link to="/providers" className={layout.small}>Manage</Link>
            </div>
            <div className={`${layout.section} ${layout.sectionTight}`}>
              {(providers.data ?? []).length === 0 ? (
                <p className={layout.small}>
                  No providers configured.{" "}
                  <Link to="/providers/new">Add one</Link> to run reviews.
                </p>
              ) : (
                (providers.data ?? []).map((p) => (
                  <div key={p.id} className={styles.compactRow}>
                    <div className={styles.compactRowMain}>
                      <span className={styles.compactRowTitle}>{p.name}</span>
                      <span className={styles.compactRowMeta}>
                        {p.protocol} · {p.base_url || "no endpoint"}
                      </span>
                    </div>
                    <StatusDot
                      tone={!p.enabled ? "muted" : p.has_credential || p.base_url === "" ? "ok" : "warn"}
                      label={
                        !p.enabled
                          ? "disabled"
                          : p.has_credential || p.protocol
                            ? "configured"
                            : "no key"
                      }
                    />
                  </div>
                ))
              )}
            </div>
          </section>

          {/* Projects needing attention */}
          <section aria-labelledby="ov-attention">
            <h2 className={layout.sectionTitle} id="ov-attention">
              Projects needing attention
            </h2>
            <div className={`${layout.section} ${layout.sectionTight}`}>
              {attentionProjects.length === 0 ? (
                <p className={layout.small}>
                  All {projects.data?.length ?? 0} projects are healthy.
                </p>
              ) : (
                attentionProjects.map((p) => (
                  <div key={p.id} className={styles.compactRow}>
                    <div className={styles.compactRowMain}>
                      <Link to={`/projects/${p.id}`} className={styles.compactRowTitle}>
                        {p.display_name}
                      </Link>
                      <span className={styles.compactRowMeta}>
                        {!p.is_available
                          ? "Path is unavailable on disk"
                          : "Uncommitted changes in working tree"}
                      </span>
                    </div>
                    <StatusDot
                      tone={!p.is_available ? "danger" : "warn"}
                      label={!p.is_available ? "unavailable" : "dirty"}
                    />
                  </div>
                ))
              )}
            </div>
          </section>

          <p className={layout.small} style={{ textAlign: "right" }}>
            Backend {info.data?.app_version ?? "…"} · updated {formatDateTime(new Date().toISOString())}
          </p>
        </div>
      </div>
    </>
  );
}
