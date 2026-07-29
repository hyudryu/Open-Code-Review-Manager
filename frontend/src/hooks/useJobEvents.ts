/**
 * SSE hook for live job events (SPEC §14).
 *
 * Connects to GET /api/v1/jobs/{id}/events. The browser EventSource sends
 * Last-Event-ID automatically on reconnect, so missed persisted events are
 * replayed by the server. The stream closes at terminal state.
 */

import { useEffect, useReducer, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { qk } from "../api/hooks";
import type { JobEventRecord } from "../types";

export interface LiveFileProgress {
  path: string;
  state: "pending" | "started" | "completed" | "failed";
  comments: number | null;
}

export interface LiveLogLine {
  stream: string;
  text: string;
}

export interface LiveJobState {
  connected: boolean;
  status: string | null;
  phase: string | null;
  totalFiles: number | null;
  files: Map<string, LiveFileProgress>;
  log: LiveLogLine[];
  warnings: string[];
  summary: Record<string, unknown> | null;
  terminal: boolean;
  lastEventId: number;
}

const MAX_LOG_LINES = 400;
const MAX_FILES = 600;
const MAX_WARNINGS = 100;

const TERMINAL_EVENTS = new Set(["job.completed", "job.failed", "job.cancelled"]);
const TERMINAL_STATUSES = new Set([
  "completed",
  "completed_with_warnings",
  "failed",
  "cancelled",
  "interrupted",
]);

export type LiveJobAction =
  | { type: "connected"; value: boolean }
  | { type: "event"; eventType: string; payload: Record<string, unknown>; id: number | null }
  | { type: "reset" };

export const initialLiveJobState: LiveJobState = {
  connected: false,
  status: null,
  phase: null,
  totalFiles: null,
  files: new Map(),
  log: [],
  warnings: [],
  summary: null,
  terminal: false,
  lastEventId: 0,
};

export function liveProgressTotal(
  inventoryTotal: number | null,
  observedFileCount: number,
): number | null {
  return inventoryTotal ?? (observedFileCount > 0 ? observedFileCount : null);
}

export function liveFileProgress(state: LiveJobState) {
  const files = Array.from(state.files.values());
  const completed = files.filter(
    (file) => file.state === "completed" || file.state === "failed",
  ).length;
  const total = liveProgressTotal(state.totalFiles, files.length);
  const percent = total && total > 0
    ? Math.min(100, Math.round((completed / total) * 100))
    : 0;
  return { files, completed, total, percent };
}

export function unseenJobEvents(
  events: JobEventRecord[],
  seenIds: ReadonlySet<number>,
): JobEventRecord[] {
  return [...events]
    .sort((a, b) => a.id - b.id)
    .filter((event) => !seenIds.has(event.id));
}

export function liveJobReducer(
  state: LiveJobState,
  action: LiveJobAction,
): LiveJobState {
  switch (action.type) {
    case "reset":
      return { ...initialLiveJobState };
    case "connected":
      return { ...state, connected: action.value };
    case "event": {
      const { eventType, payload, id } = action;
      const next: LiveJobState = {
        ...state,
        lastEventId: id && id > state.lastEventId ? id : state.lastEventId,
      };
      let terminal = false;

      switch (eventType) {
        case "job.status": {
          const to = typeof payload.to === "string" ? payload.to : null;
          next.status = to;
          if (to && TERMINAL_STATUSES.has(to)) terminal = true;
          break;
        }
        case "job.phase": {
          next.phase = typeof payload.phase === "string" ? payload.phase : null;
          break;
        }
        case "job.inventory": {
          const inventory = Array.isArray(payload.files)
            ? payload.files.filter((file): file is string => typeof file === "string")
            : [];
          const files = new Map(state.files);
          for (const file of inventory.slice(0, MAX_FILES)) {
            if (!files.has(file)) {
              files.set(file, { path: file, state: "pending", comments: null });
            }
          }
          next.files = files;
          next.totalFiles =
            typeof payload.total_files === "number" ? payload.total_files : inventory.length;
          break;
        }
        case "job.file_started": {
          const file = typeof payload.file === "string" ? payload.file : null;
          if (file) {
            const files = new Map(state.files);
            if (files.size >= MAX_FILES && !files.has(file)) {
              const first = files.keys().next().value;
              if (first !== undefined) files.delete(first);
            }
            files.set(file, { path: file, state: "started", comments: null });
            next.files = files;
          }
          break;
        }
        case "job.file_completed": {
          const file = typeof payload.file === "string" ? payload.file : null;
          if (file) {
            const files = new Map(state.files);
            files.set(file, {
              path: file,
              state: payload.failed === true ? "failed" : "completed",
              comments: typeof payload.comments === "number" ? payload.comments : null,
            });
            next.files = files;
          }
          break;
        }
        case "job.log": {
          const text = typeof payload.text === "string" ? payload.text : "";
          const stream = typeof payload.stream === "string" ? payload.stream : "stdout";
          if (text) {
            next.log = [...state.log.slice(-(MAX_LOG_LINES - 1)), { stream, text }];
          }
          break;
        }
        case "job.warning": {
          const message =
            typeof payload.message === "string" ? payload.message : JSON.stringify(payload);
          next.warnings = [...state.warnings.slice(-(MAX_WARNINGS - 1)), message];
          break;
        }
        case "job.summary": {
          next.summary =
            (payload.summary as Record<string, unknown> | undefined) ?? payload;
          break;
        }
        default:
          break;
      }
      if (TERMINAL_EVENTS.has(eventType)) terminal = true;
      next.terminal = state.terminal || terminal;
      return next;
    }
    default:
      return state;
  }
}

export function useJobEvents(jobId: string | undefined, enabled = true) {
  const [state, dispatch] = useReducer(liveJobReducer, initialLiveJobState);
  const qc = useQueryClient();
  const sourceRef = useRef<EventSource | null>(null);
  const seenEventIdsRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!jobId || !enabled) return undefined;
    dispatch({ type: "reset" });
    seenEventIdsRef.current = new Set();

    const source = new EventSource(`/api/v1/jobs/${jobId}/events`);
    sourceRef.current = source;

    source.onopen = () => dispatch({ type: "connected", value: true });
    source.onerror = () => dispatch({ type: "connected", value: false });

    const applyEvent = (
      eventType: string,
      payload: Record<string, unknown>,
      id: number | null,
    ) => {
      if (id !== null) {
        if (seenEventIdsRef.current.has(id)) return;
        seenEventIdsRef.current.add(id);
      }
      dispatch({ type: "event", eventType, payload, id });
      if (
        TERMINAL_EVENTS.has(eventType) ||
        (eventType === "job.status" &&
          typeof payload.to === "string" &&
          TERMINAL_STATUSES.has(payload.to))
      ) {
        source.close();
        dispatch({ type: "connected", value: false });
        void qc.invalidateQueries({ queryKey: qk.job(jobId) });
        void qc.invalidateQueries({ queryKey: qk.jobs() });
        void qc.invalidateQueries({ queryKey: qk.queue });
        void qc.invalidateQueries({ queryKey: ["jobs", jobId, "findings"] });
      } else if (eventType === "job.status") {
        void qc.invalidateQueries({ queryKey: qk.job(jobId) });
        void qc.invalidateQueries({ queryKey: qk.queue });
      }
    };

    const handle = (eventType: string) => (event: MessageEvent<string>) => {
      let payload: Record<string, unknown> = {};
      try {
        payload = event.data ? (JSON.parse(event.data) as Record<string, unknown>) : {};
      } catch {
        return;
      }
      const parsedId = event.lastEventId
        ? Number.parseInt(event.lastEventId, 10)
        : Number.NaN;
      applyEvent(eventType, payload, Number.isNaN(parsedId) ? null : parsedId);
    };

    const types = [
      "job.status",
      "job.log",
      "job.phase",
      "job.inventory",
      "job.file_started",
      "job.file_completed",
      "job.warning",
      "job.finding",
      "job.summary",
      "job.completed",
      "job.failed",
      "job.cancelled",
    ];
    for (const type of types) source.addEventListener(type, handle(type));

    const pollHistory = async () => {
      try {
        const events = await api.get<JobEventRecord[]>(
          `/api/v1/jobs/${jobId}/events/history`,
          { limit: 1000 },
        );
        for (const event of unseenJobEvents(events, seenEventIdsRef.current)) {
          applyEvent(event.event_type, event.payload ?? {}, event.id);
        }
      } catch {
        // SSE remains the primary transport; the next poll retries reconciliation.
      }
    };
    void pollHistory();
    const pollTimer = window.setInterval(() => void pollHistory(), 2_000);

    return () => {
      window.clearInterval(pollTimer);
      source.close();
      sourceRef.current = null;
    };
  }, [jobId, enabled, qc]);

  return state;
}
