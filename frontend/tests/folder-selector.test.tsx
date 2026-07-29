/**
 * FolderSelector: server-backed directory browser.
 *
 * Verifies the picker browses the backend host's filesystem, lets the user
 * navigate into a subdirectory, and pastes the chosen ABSOLUTE path into the
 * form via onSelect — instead of enumerating the folder (the old
 * webkitdirectory behavior the user reported).
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FolderSelector } from "../src/components/ui/FolderSelector";
import type { DirBrowse } from "../src/types";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const home: DirBrowse = {
  path: "/home/me",
  parent: "/home",
  entries: [
    { name: "projects", path: "/home/me/projects" },
    { name: "documents", path: "/home/me/documents" },
  ],
  truncated: false,
};

const projects: DirBrowse = {
  path: "/home/me/projects",
  parent: "/home/me",
  entries: [{ name: "my-repo", path: "/home/me/projects/my-repo" }],
  truncated: false,
};

describe("FolderSelector", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), "http://localhost");
        const method = init?.method ?? "GET";
        if (url.pathname === "/api/v1/health") return jsonResponse({ status: "ok" });
        if (url.pathname === "/api/v1/system/browse" && method === "GET") {
          const paramPath = url.searchParams.get("path") ?? "";
          // Empty path => home.
          const body = paramPath === "/home/me/projects" ? projects : home;
          return jsonResponse(body);
        }
        return jsonResponse({ error: { code: "not_found", message: "nope" } }, 404);
      }),
    );
  });

  function renderSelector(onSelect: (p: string) => void) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <FolderSelector onSelect={onSelect} />
      </QueryClientProvider>,
    );
  }

  it("opens a directory browser, navigates, and selects the absolute path", async () => {
    const selected: string[] = [];
    renderSelector((p) => selected.push(p));

    // Open the picker.
    fireEvent.click(screen.getByRole("button", { name: /select folder/i }));

    // Home directory listing loads.
    await waitFor(() => {
      expect(screen.getByText("/home/me")).toBeInTheDocument();
      expect(screen.getByText("projects")).toBeInTheDocument();
      expect(screen.getByText("documents")).toBeInTheDocument();
    });

    // Navigate into "projects".
    fireEvent.click(screen.getByText("projects"));
    await waitFor(() => {
      expect(screen.getByText("/home/me/projects")).toBeInTheDocument();
      expect(screen.getByText("my-repo")).toBeInTheDocument();
    });

    // Selecting the current folder pastes the absolute path via onSelect.
    fireEvent.click(screen.getByRole("button", { name: /select this folder/i }));
    await waitFor(() => expect(selected).toEqual(["/home/me/projects"]));
  });

  it("does not enumerate or upload folder contents", async () => {
    const fetchMock = vi.mocked(fetch);
    renderSelector(() => undefined);
    fireEvent.click(screen.getByRole("button", { name: /select folder/i }));

    await waitFor(() => expect(screen.getByText("projects")).toBeInTheDocument());

    // No multipart uploads and no webkitdirectory-style file enumeration —
    // the only request is the directory listing JSON GET.
    for (const call of fetchMock.mock.calls) {
      const init = (call[1] as RequestInit | undefined) ?? {};
      expect(init.body).toBeUndefined();
    }
  });
});
