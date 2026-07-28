/**
 * Speed learner hook — watches completed jobs and automatically learns
 * from their timing data. Provides ETA estimation for queued jobs.
 */

import { useEffect, useMemo } from "react";
import { useJobs, useQueue } from "../api/hooks";
import { learn, estimateQueueETA } from "../lib/speed-learner";
import { TERMINAL_STATUSES } from "../types";

export function useSpeedLearner() {
  const queue = useQueue({ refetchInterval: 6_000 });
  const recent = useJobs({ limit: 15 });

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

  // Learn from recently completed jobs
  useEffect(() => {
    for (const job of completedJobs) {
      if (job.completed_at && job.started_at) {
        const started = new Date(job.started_at).getTime();
        const completed = new Date(job.completed_at).getTime();
        const elapsedMs = completed - started;
        if (elapsedMs > 0) {
          learn(job, elapsedMs);
        }
      }
    }
  }, [completedJobs]);

  // Compute ETA for the queue
  const eta = useMemo(() => {
    // Use the first queued job's profile/model as a reference
    const firstQueued = serverQueued[0];
    if (!firstQueued) return { eta: null, perJob: null };

    const model = firstQueued.profile_id;
    const config = firstQueued.configuration_snapshot_json as Record<string, unknown> | null;
    const concurrency = (config?.concurrency as number) ?? 1;

    // Estimate files from reviewable_count in configuration snapshot
    const estimatedFiles = (config?.total_files as number)
      ?? (config?.reviewable_count as number)
      ?? 10; // fallback estimate

    return estimateQueueETA(
      serverQueued,
      activeJobs,
      model,
      concurrency,
      estimatedFiles,
    );
  }, [serverQueued, activeJobs]);

  return {
    eta: eta.eta,
    perJob: eta.perJob,
    queuedCount: serverQueued.length,
    activeCount: activeJobs.length,
  };
}
