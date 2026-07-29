import { estimateActiveJobETA, learn } from "../src/lib/speed-learner";
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
