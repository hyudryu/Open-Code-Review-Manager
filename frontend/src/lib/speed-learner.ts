/**
 * Queue speed learner — learns job timing from completed jobs to estimate
 * ETA for queued jobs based on concurrency, model, and review profile.
 *
 * Stores timing data in localStorage under the key `ocrcc.speed-learner`.
 * Data is bucketed by (model_name, concurrency_level) to capture how
 * different settings affect job duration.
 */

import type { Job } from "../types";

const STORAGE_KEY = "ocrcc.speed-learner";

export interface SpeedEntry {
  job_id?: string;
  elapsed_ms: number;
  files_reviewed: number;
  /** Model id when available; legacy entries contain the review profile id. */
  profile_model: string | null;
  concurrency: number;
  completed_at: string;
}

export interface SpeedBucket {
  key: string;
  avg_elapsed_per_file: number;
  count: number;
  multiplier: number; // how much slower/faster than global average
}

export interface SpeedLearnerState {
  entries: SpeedEntry[];
  buckets: SpeedBucket[];
  globalAvgPerFile: number;
  multiplier: number; // cumulative correction factor
}

/** Load the current learner state from localStorage. */
function loadState(): SpeedLearnerState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return createEmptyState();
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return buildState(parsed);
    }
    return createEmptyState();
  } catch {
    return createEmptyState();
  }
}

/** Save learner state to localStorage. */
function saveState(state: SpeedLearnerState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.entries));
  } catch {
    /* quota exceeded — silently ignore */
  }
}

function createEmptyState(): SpeedLearnerState {
  return { entries: [], buckets: [], globalAvgPerFile: 0, multiplier: 1 };
}

function buildState(entries: SpeedEntry[]): SpeedLearnerState {
  if (entries.length === 0) return createEmptyState();

  // Filter out entries with no useful data
  const valid = entries.filter((e) => e.elapsed_ms > 0 && e.files_reviewed > 0);
  if (valid.length === 0) return createEmptyState();

  // Compute global average
  const totalFiles = valid.reduce((sum, e) => sum + e.files_reviewed, 0);
  const totalTime = valid.reduce((sum, e) => sum + e.elapsed_ms, 0);
  const globalAvgPerFile = totalFiles > 0 ? totalTime / totalFiles : 0;

  // Bucket by (model, concurrency)
  const bucketMap = new Map<string, { elapsed: number; files: number; count: number }>();
  for (const entry of valid) {
    const key = `${entry.profile_model ?? "none"}|${entry.concurrency}`;
    const bucket = bucketMap.get(key) ?? { elapsed: 0, files: 0, count: 0 };
    bucket.elapsed += entry.elapsed_ms;
    bucket.files += entry.files_reviewed;
    bucket.count += 1;
    bucketMap.set(key, bucket);
  }

  const buckets: SpeedBucket[] = [];
  for (const [key, data] of bucketMap) {
    const avgPerFile = data.files > 0 ? data.elapsed / data.files : 0;
    const multiplier = globalAvgPerFile > 0 ? avgPerFile / globalAvgPerFile : 1;
    buckets.push({ key, avg_elapsed_per_file: avgPerFile, count: data.count, multiplier });
  }

  const multiplier = 1;

  return { entries: valid, buckets, globalAvgPerFile, multiplier };
}

/**
 * Learn from a completed job — extract timing data and store it.
 *
 * @param job - The completed job
 * @param actualElapsedMs - Actual elapsed time in ms (started_at to completed_at)
 */
export function learn(job: Job, actualElapsedMs: number): boolean {
  const state = loadState();

  if (state.entries.some((entry) => entry.job_id === job.id)) return false;

  // Prefer the immutable model captured when the job was queued.
  const config = job.configuration_snapshot_json as Record<string, unknown> | null;
  const model = config?.model as Record<string, unknown> | null | undefined;
  const settings = config?.settings as Record<string, unknown> | null | undefined;
  const modelKey = typeof model?.model_id === "string" ? model.model_id : job.profile_id;
  const concurrency = settings?.concurrency as number | undefined;

  // Extract files reviewed from result summary
  const summary = job.result_summary_json as Record<string, unknown> | null;
  const filesReviewed = (summary?.files_reviewed as number) ?? 1;

  const entry: SpeedEntry = {
    job_id: job.id,
    elapsed_ms: Math.max(0, actualElapsedMs),
    files_reviewed: Math.max(1, filesReviewed),
    profile_model: modelKey ?? null,
    concurrency: typeof concurrency === "number" ? concurrency : 1,
    completed_at: job.completed_at ?? new Date().toISOString(),
  };

  // Limit stored entries to last 100
  state.entries.push(entry);
  if (state.entries.length > 100) {
    state.entries = state.entries.slice(-100);
  }

  saveState(state);
  return true;
}

/**
 * Estimate queue ETA based on learned timing data.
 *
 * @param queuedJobs - Jobs waiting in the queue
 * @param activeJobs - Currently running/preparing jobs
 * @param model - Profile model name (for bucket matching)
 * @param concurrency - Concurrency level (for bucket matching)
 * @param estimatedFiles - Estimated files to review (from preview)
 * @returns { eta: string | null, perJob: string | null }
 */
export function estimateQueueETA(
  queuedJobs: Job[],
  activeJobs: Job[],
  model: string | null,
  concurrency: number,
  estimatedFiles: number,
): { eta: string | null; perJob: string | null } {
  const state = loadState();
  if (state.globalAvgPerFile <= 0 || estimatedFiles <= 0) {
    return { eta: null, perJob: null };
  }

  // Find matching bucket or use global average
  const bucketKey = `${model ?? "none"}|${concurrency}`;
  const bucket = state.buckets.find((b) => b.key === bucketKey);
  const avgPerFile = bucket ? bucket.avg_elapsed_per_file : state.globalAvgPerFile;

  // Apply multiplier correction
  const adjustedPerFile = avgPerFile * state.multiplier;

  // Calculate time per job (files * time per file)
  const timePerJob = estimatedFiles * adjustedPerFile;

  // Calculate total wait time:
  // - Active jobs running to completion
  // - Plus queued jobs ahead
  const activeTime = activeJobs.reduce((sum, job) => {
    // Estimate remaining time for active jobs
    const summary = job.result_summary_json as Record<string, unknown> | null;
    const files = (summary?.files_reviewed as number) ?? estimatedFiles;
    return sum + files * adjustedPerFile;
  }, 0);

  const queuedTime = queuedJobs.length * timePerJob;
  const totalWaitMs = activeTime + queuedTime;

  if (totalWaitMs <= 0) {
    return { eta: null, perJob: null };
  }

  // Format ETA
  const etaMs = totalWaitMs;
  const perJobMs = timePerJob;

  return {
    eta: formatMillis(etaMs),
    perJob: formatMillis(perJobMs),
  };
}

/** Estimate the remaining runtime of one active job from completed file count. */
export function estimateActiveJobETA(
  job: Job,
  completedFiles: number,
  totalFiles: number | null,
): string | null {
  if (totalFiles === null) return null;
  const remainingFiles = Math.max(0, totalFiles - completedFiles);
  if (remainingFiles === 0) return "under 1 s";

  const state = loadState();
  if (state.globalAvgPerFile <= 0) return null;

  const config = job.configuration_snapshot_json as Record<string, unknown> | null;
  const model = config?.model as Record<string, unknown> | null | undefined;
  const settings = config?.settings as Record<string, unknown> | null | undefined;
  const modelKey = typeof model?.model_id === "string" ? model.model_id : job.profile_id;
  const concurrency = typeof settings?.concurrency === "number" ? settings.concurrency : 1;
  const bucket = state.buckets.find(
    (candidate) => candidate.key === `${modelKey ?? "none"}|${concurrency}`,
  );
  const averagePerFile = bucket?.avg_elapsed_per_file ?? state.globalAvgPerFile;
  return formatMillis(remainingFiles * averagePerFile * state.multiplier);
}

/**
 * Get the current speed multiplier for display in tooltips.
 */
export function getSpeedMultiplier(): number {
  const state = loadState();
  return state.multiplier;
}

/**
 * Format milliseconds into human-readable duration.
 */
function formatMillis(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return rs ? `${m} min ${rs} s` : `${m} min`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h} h ${rm} min` : `${h} h`;
}
