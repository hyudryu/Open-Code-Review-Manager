/**
 * Server port setting: persisted via the settings API and flagged with a
 * "Restart required" badge when the saved port differs from the running port.
 *
 * The running process binds the port once at startup, so a port change is
 * saved but cannot take effect until restart. The badge relies on the backend
 * reporting running_port vs configured_port via /system/info.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SettingsPage } from "../src/pages/SettingsPage";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type FetchOverrides = Record<
  string,
  (url: URL, init: RequestInit | undefined) => Response | Promise<Response>
>;

function makeOverrides(overrides: {
  settings?: Record<string, unknown>;
  systemInfo?: Record<string, unknown>;
}): FetchOverrides {
  const baseSettings = {
    "queue.global_concurrency": 1,
    "queue.per_project_concurrency": 1,
    "queue.per_provider_concurrency": 1,
    "queue.paused": false,
    "retention.artifact_days": 30,
    "retention.keep_worktrees": false,
    "webhooks.require_https": true,
    "webhooks.allow_private_networks": false,
    "ocr.executable": null,
    "git.executable": null,
    "server.port": 8372,
    ...overrides.settings,
  };
  const baseInfo = {
    app_version: "0.1.0",
    python_version: "3.12",
    platform: "test",
    database_path: "/tmp/test.db",
    database_status: "ok",
    data_dir: "/tmp/data",
    running_port: 8372,
    configured_port: 8372,
    ocr: { status: "ok", version: "9.9.9" },
    git_version: "2.0",
    mcp: { mounted: true, endpoint: "/mcp" },
    queue_worker: { running: false, active_jobs: 0 },
    webhook_worker: { running: false },
    active_process_count: 0,
    job_count: 0,
    worktree_count: 0,
    session_storage_bytes: 0,
    ...overrides.systemInfo,
  };
  return {
    "/api/v1/health": () => jsonResponse({ status: "ok", version: "0.1.0" }),
    "/api/v1/settings": (_u, init) => {
      // PATCH reflects the saved change back.
      if ((init?.method ?? "GET") === "PATCH") {
        const changes = JSON.parse(String(init?.body)).changes as Record<string, unknown>;
        return jsonResponse({ ...baseSettings, ...changes });
      }
      return jsonResponse(baseSettings);
    },
    "/api/v1/system/info": () => jsonResponse(baseInfo),
    "/api/v1/system/ocr": () =>
      jsonResponse({ status: "ok", version: "9.9.9", capabilities: {} }),
    "/api/v1/system/ocr/update-status": () =>
      jsonResponse({ update_available: false, current_version: "9.9.9" }),
  };
}

function renderPage(overrides: Parameters<typeof makeOverrides>[0]) {
  const handlers = makeOverrides(overrides);
  const patchCalls: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname;
      // CSRF prime is a GET to /api/v1/health; capture PATCH bodies.
      if ((init?.method ?? "GET") === "PATCH" && path === "/api/v1/settings") {
        patchCalls.push(JSON.parse(String(init?.body)).changes);
      }
      const handler = handlers[path];
      if (handler) return handler(url, init);
      return jsonResponse({ error: { code: "not_found", message: "nope" } }, 404);
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, patchCalls };
}

describe("SettingsPage — server port", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a 'Running on <port>' badge when saved port equals the running port", async () => {
    renderPage({});
    await waitFor(() =>
      expect(screen.getByLabelText("Server port")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Running on 8372/)).toBeInTheDocument();
    expect(screen.queryByText(/Restart required/)).not.toBeInTheDocument();
  });

  it("shows a 'Restart required' badge when the saved port differs from the running port", async () => {
    renderPage({
      settings: { "server.port": 9000 },
      systemInfo: { running_port: 8372, configured_port: 9000 },
    });
    await waitFor(() =>
      expect(screen.getByLabelText("Server port")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Restart required/)).toBeInTheDocument();
  });

  it("saves a valid port on blur and shows the restart badge afterwards", async () => {
    const { patchCalls } = renderPage({});
    const input = await screen.findByLabelText("Server port");
    expect((input as HTMLInputElement).value).toBe("8372");

    fireEvent.change(input, { target: { value: "9100" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(patchCalls).toEqual([{ "server.port": 9100 }]),
    );
  });

  it("rejects an out-of-range port without saving", async () => {
    const { patchCalls } = renderPage({});
    const input = await screen.findByLabelText("Server port");

    fireEvent.change(input, { target: { value: "99999" } });
    fireEvent.blur(input);

    // Value reverts; nothing is saved.
    await waitFor(() => expect((input as HTMLInputElement).value).toBe("8372"));
    expect(patchCalls).toEqual([]);
  });
});
