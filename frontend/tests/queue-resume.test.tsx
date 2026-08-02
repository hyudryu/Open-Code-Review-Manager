/**
 * Cancelled-job actions menu: a "Resume" item (continue the OCR session from
 * its checkpoint) appears only when the job actually started and recorded an
 * ocr_session_id. Jobs cancelled while queued never started, so they only get
 * Retry. Full-file scans also only get Retry because OCR scan sessions cannot
 * be resumed.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { QueuePage } from "../src/pages/QueuePage";
import type { Job, Project } from "../src/types";

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-a",
    project_id: "p1",
    profile_id: null,
    source: "web",
    mode: "range",
    base_ref: "main",
    target_ref: "feature",
    commit_ref: null,
    priority: 50,
    queue_position: null,
    status: "cancelled",
    status_message: null,
    paused: false,
    configuration_snapshot_json: null,
    generated_command_json: null,
    ocr_version: null,
    ocr_session_id: null,
    result_summary_json: null,
    warnings_json: null,
    exit_code: null,
    retry_of_job_id: null,
    resume_from_session_id: null,
    error_code: null,
    queued_at: new Date().toISOString(),
    started_at: null,
    completed_at: new Date().toISOString(),
    findings_count: 0,
    ...overrides,
  };
}

const project: Project = {
  id: "p1",
  folder_id: null,
  display_name: "Demo",
  absolute_path: "/tmp/demo",
  default_branch: "main",
  remote_name: "origin",
  remote_url: null,
  current_branch: "main",
  is_dirty: false,
  is_available: true,
  last_branch_refresh_at: null,
  created_at: new Date().toISOString(),
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderQueuePage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <QueuePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Open a Radix DropdownMenu trigger in jsdom. jsdom lacks pointer-capture
 * support, so pointer events don't open the menu; focus the trigger first and
 * dispatch a keyDown ArrowDown, which Radix treats as an open intent.
 */
function openMenu(trigger: HTMLElement) {
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
}

describe("QueuePage cancelled-job menu", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.startsWith("/api/v1/queue")) {
          return jsonResponse({ paused: false, jobs: [] });
        }
        if (url.startsWith("/api/v1/jobs") && method === "GET") {
          return jsonResponse({ items: [job], total: 1, limit: 15, offset: 0 });
        }
        if (url.startsWith("/api/v1/projects")) {
          return jsonResponse([project]);
        }
        return jsonResponse({}, 404);
      }),
    );
  });

  let job: Job;

  it("offers Resume when the cancelled job has an OCR session", async () => {
    job = makeJob({ ocr_session_id: "sess-123" });

    renderQueuePage();

    // Cancelled jobs appear under "Recently completed".
    await screen.findByText(/Recently completed/i);
    const trigger = screen.getByRole("button", { name: "Job actions" });
    openMenu(trigger);

    await waitFor(() => {
      expect(screen.getByRole("menuitem", { name: "Resume" })).toBeInTheDocument();
      expect(screen.getByRole("menuitem", { name: "Retry" })).toBeInTheDocument();
    });
  });

  it("hides Resume when the cancelled job has no OCR session", async () => {
    job = makeJob({ ocr_session_id: null });

    renderQueuePage();

    await screen.findByText(/Recently completed/i);
    const trigger = screen.getByRole("button", { name: "Job actions" });
    openMenu(trigger);

    // Retry is still offered, but Resume is not.
    await waitFor(() => {
      expect(screen.getByRole("menuitem", { name: "Retry" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("menuitem", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("hides Resume for scans even when OCR recorded a session", async () => {
    job = makeJob({ mode: "scan", ocr_session_id: "scan-session-123" });

    renderQueuePage();

    await screen.findByText(/Recently completed/i);
    openMenu(screen.getByRole("button", { name: "Job actions" }));

    await waitFor(() => {
      expect(screen.getByRole("menuitem", { name: "Retry" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("menuitem", { name: "Resume" })).not.toBeInTheDocument();
  });
});
