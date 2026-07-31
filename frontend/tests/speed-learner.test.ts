import { estimateActiveJobETA, estimateAdaptiveETA, learn } from "../src/lib/speed-learner";
import type { Job } from "../src/types";

function job(id: string, model = "review-model"): Job {
  return {
    id,
    project_id: "project",
    profile_id: "profile",
    source: "web",
    mode: "commit",
    base_ref: null,
    target_ref: null,
    commit_ref: "HEAD",
    priority: 0,
    queue_position: null,
    status: "completed",
    status_message: null,
    error_code: null,
    paused: false,
    configuration_snapshot_json: {
      model: { model_id: model },
      settings: { concurrency: 2 },
    },
    generated_command_json: null,
    ocr_version: null,
    ocr_session_id: null,
    result_summary_json: { files_reviewed: 4 },
    warnings_json: null,
    exit_code: 0,
    retry_of_job_id: null,
    resume_from_session_id: null,
    queued_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:40Z",
    findings_count: 0,
  };
}

describe("review speed learner", () => {
  beforeEach(() => localStorage.clear());

  it("estimates remaining files using the matching model and concurrency", () => {
    learn(job("past"), 40_000);
    learn(job("slower-model", "other-model"), 80_000);

    expect(estimateActiveJobETA(job("active"), 1, 4)).toBe("30 s");
  });

  it("does not learn the same completed job more than once", () => {
    const completed = job("past");
    learn(completed, 40_000);
    learn(completed, 40_000);

    const entries = JSON.parse(localStorage.getItem("ocrcc.speed-learner") ?? "[]");
    expect(entries).toHaveLength(1);
  });
});

describe("estimateAdaptiveETA", () => {
  beforeEach(() => localStorage.clear());

  it("returns null until at least one file has completed", () => {
    expect(estimateAdaptiveETA({ completedFiles: 0, totalFiles: 32, elapsedMs: 5_000, historicalPerFile: 10_000 })).toEqual({
      remaining: null,
      perFile: 0,
    });
  });

  it("returns null when the total file count is unknown", () => {
    expect(estimateAdaptiveETA({ completedFiles: 4, totalFiles: null, elapsedMs: 40_000, historicalPerFile: 10_000 })).toEqual({
      remaining: null,
      perFile: 0,
    });
  });

  it("uses the job's own observed pace when there is no history", () => {
    // Previously this returned null for the whole review; now 4 files in 40s
    // (10s/file) -> 28 remaining * 10s = 280s = "4 min 40 s".
    expect(
      estimateAdaptiveETA({ completedFiles: 4, totalFiles: 32, elapsedMs: 40_000, historicalPerFile: 0 }).remaining,
    ).toBe("4 min 40 s");
  });

  it("blends observed pace with history, landing strictly between them", () => {
    // History says 10s/file; this job is faster at 5s/file (4 in 20s).
    const result = estimateAdaptiveETA({
      completedFiles: 4,
      totalFiles: 32,
      elapsedMs: 20_000,
      historicalPerFile: 10_000,
    }).remaining;
    // Historical-only would be "4 min 40 s"; observed-only "2 min 20 s".
    expect(result).toBe("3 min 20 s");
  });

  it("converges toward the observed pace as more files complete", () => {
    // Same history (10s/file) and observed pace (5s/file), more completions.
    const few = estimateAdaptiveETA({
      completedFiles: 4,
      totalFiles: 100,
      elapsedMs: 20_000,
      historicalPerFile: 10_000,
    }).perFile;
    const many = estimateAdaptiveETA({
      completedFiles: 40,
      totalFiles: 100,
      elapsedMs: 200_000,
      historicalPerFile: 10_000,
    }).perFile;
    // Both between 5s and 10s, and the estimate with more data is closer to 5s.
    expect(few).toBeGreaterThan(5_000);
    expect(few).toBeLessThan(10_000);
    expect(many).toBeGreaterThan(5_000);
    expect(many).toBeLessThan(few);
  });

  it("reports under a second when no files remain", () => {
    expect(
      estimateAdaptiveETA({ completedFiles: 32, totalFiles: 32, elapsedMs: 320_000, historicalPerFile: 10_000 }).remaining,
    ).toBe("under 1 s");
  });
});
