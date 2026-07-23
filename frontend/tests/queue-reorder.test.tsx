/**
 * Queue drag-and-drop reorder: optimistic order commits only after a valid
 * drop and reverts cleanly when the API call fails (SPEC §24).
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { QueuePage } from "../src/pages/QueuePage";
import type { Job, Project } from "../src/types";

function makeJob(id: string, targetRef: string): Job {
  return {
    id,
    project_id: "p1",
    profile_id: null,
    source: "web",
    mode: "range",
    base_ref: "main",
    target_ref: targetRef,
    commit_ref: null,
    priority: 50,
    queue_position: null,
    status: "queued",
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
    queued_at: new Date().toISOString(),
    started_at: null,
    completed_at: null,
    findings_count: 0,
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

describe("QueuePage reorder", () => {
  const reorderCalls: { job_ids: string[] }[] = [];

  beforeEach(() => {
    reorderCalls.length = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.startsWith("/api/v1/queue/reorder") && method === "POST") {
          reorderCalls.push(JSON.parse(String(init?.body)));
          // Simulate an API failure — the UI must revert the optimistic order.
          return jsonResponse(
            { error: { code: "reorder_failed", message: "boom" } },
            500,
          );
        }
        if (url.startsWith("/api/v1/queue")) {
          return jsonResponse({
            paused: false,
            jobs: [makeJob("job-a", "alpha"), makeJob("job-b", "beta")],
          });
        }
        if (url.startsWith("/api/v1/jobs")) {
          return jsonResponse({ items: [], total: 0, limit: 15, offset: 0 });
        }
        if (url.startsWith("/api/v1/projects")) {
          return jsonResponse([project]);
        }
        return jsonResponse({}, 404);
      }),
    );
  });

  it("reverts the optimistic order when the reorder API fails", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <QueuePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const list = await screen.findByRole("list", {
      name: /queued jobs in execution order/i,
    });

    // Initial order: alpha then beta.
    let rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("main → alpha");
    expect(rows[1]).toHaveTextContent("main → beta");

    // Drag alpha below beta.
    fireEvent.dragStart(rows[0], {
      dataTransfer: { setData: () => undefined, effectAllowed: "move" },
    });
    fireEvent.dragOver(rows[1], { clientY: 0 });
    fireEvent.drop(rows[1]);

    // The reorder request went out with the new order.
    await waitFor(() => expect(reorderCalls).toHaveLength(1));
    expect(reorderCalls[0].job_ids).toEqual(["job-b", "job-a"]);

    // After the API failure the visible order reverts to the server order.
    await waitFor(() => {
      rows = within(list).getAllByRole("listitem");
      expect(rows[0]).toHaveTextContent("main → alpha");
      expect(rows[1]).toHaveTextContent("main → beta");
    });
  });
});
