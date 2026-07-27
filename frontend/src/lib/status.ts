import type { JobStatus } from "../types";
import type { StatusTone } from "../components/ui";

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  preparing: "Preparing",
  running: "Running",
  cancelling: "Cancelling",
  completed: "Completed",
  completed_with_warnings: "Completed with warnings",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

export const STATUS_TONE: Record<JobStatus, StatusTone> = {
  queued: "muted",
  preparing: "accent",
  running: "accent",
  cancelling: "warn",
  completed: "ok",
  completed_with_warnings: "warn",
  failed: "danger",
  cancelled: "muted",
  interrupted: "warn",
};

export const MODE_LABEL: Record<string, string> = {
  range: "Range",
  commit: "Commit",
  workspace: "Workspace",
  pr: "Pull request",
  scan: "Scan",
};

export function jobTargetLabel(job: {
  mode: string;
  base_ref: string | null;
  target_ref: string | null;
  commit_ref: string | null;
  configuration_snapshot_json: Record<string, unknown> | null;
}): string {
  if (job.mode === "range" || job.mode === "pr")
    return `${job.base_ref ?? "?"} → ${job.target_ref ?? "?"}`;
  if (job.mode === "commit") return job.commit_ref ?? "?";
  if (job.mode === "scan") return "Full repository";
  return "Working tree";
}
