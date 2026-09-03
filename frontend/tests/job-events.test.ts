import {
  initialLiveJobState,
  liveFileProgress,
  liveProgressTotal,
  liveJobReducer,
  unseenJobEvents,
} from "../src/hooks/useJobEvents";

describe("live job event state", () => {
  it("keeps an unknown scope unknown until inventory or file activity arrives", () => {
    expect(liveProgressTotal(null, 0)).toBeNull();
    expect(liveProgressTotal(null, 3)).toBe(3);
    expect(liveProgressTotal(8, 3)).toBe(8);
  });

  it("keeps a stable inventory total while file activity advances", () => {
    const inventoried = liveJobReducer(initialLiveJobState, {
      type: "event",
      eventType: "job.inventory",
      payload: { files: ["src/a.ts", "src/b.ts"], total_files: 2 },
      id: 1,
    });

    expect(inventoried.totalFiles).toBe(2);
    expect(Array.from(inventoried.files.values())).toEqual([
      { path: "src/a.ts", state: "pending", comments: null },
      { path: "src/b.ts", state: "pending", comments: null },
    ]);

    const started = liveJobReducer(inventoried, {
      type: "event",
      eventType: "job.file_started",
      payload: { file: "src/a.ts" },
      id: 2,
    });
    const failed = liveJobReducer(started, {
      type: "event",
      eventType: "job.file_completed",
      payload: { file: "src/a.ts", failed: true },
      id: 3,
    });

    expect(failed.totalFiles).toBe(2);
    expect(failed.files.get("src/a.ts")?.state).toBe("failed");
    expect(failed.files.get("src/b.ts")?.state).toBe("pending");
    expect(liveFileProgress(failed)).toMatchObject({
      completed: 1,
      total: 2,
      percent: 50,
    });
  });

  it("reconciles persisted events in order without replaying seen events", () => {
    const events = [
      { id: 12, event_type: "job.log", payload: { text: "later" }, created_at: null },
      { id: 10, event_type: "job.inventory", payload: { total_files: 1 }, created_at: null },
      { id: 11, event_type: "job.log", payload: { text: "seen" }, created_at: null },
    ];

    expect(unseenJobEvents(events, new Set([11])).map((event) => event.id)).toEqual([10, 12]);
  });

  it("refreshes live input and output token totals from cumulative usage events", () => {
    const first = liveJobReducer(initialLiveJobState, {
      type: "event",
      eventType: "job.usage",
      payload: { input_tokens: 1200, output_tokens: 300 },
      id: 20,
    });
    const refreshed = liveJobReducer(first, {
      type: "event",
      eventType: "job.usage",
      payload: { input_tokens: 2000, output_tokens: 425 },
      id: 21,
    });

    expect(refreshed.inputTokens).toBe(2000);
    expect(refreshed.outputTokens).toBe(425);
  });

  it("bumps progress by a small amount for each model request", () => {
    // Planning/grouping requests run before any file completes: each one is
    // itself a small unit of progress, so the bar must not sit at 0%.
    let state = liveJobReducer(initialLiveJobState, {
      type: "event",
      eventType: "job.inventory",
      payload: { total_files: 18 },
      id: 1,
    });
    for (let count = 1; count <= 3; count += 1) {
      state = liveJobReducer(state, {
        type: "event",
        eventType: "job.model_request",
        payload: { count },
        id: count + 1,
      });
    }
    expect(state.modelRequests).toBe(3);
    expect(liveFileProgress(state)).toMatchObject({
      completed: 0,
      total: 18,
      percent: 2, // 3 * 0.1 files / 18 → 1.7% rounds to 2
    });

    // The counter follows the backend's cumulative count, and the credit is
    // capped so request chatter never dominates real completions.
    const capped = liveJobReducer(state, {
      type: "event",
      eventType: "job.model_request",
      payload: { count: 500 },
      id: 9,
    });
    expect(liveFileProgress(capped).percent).toBe(11); // (0 + 2.0 cap) / 18

    // Completions add on top of the capped credit.
    const done = liveJobReducer(capped, {
      type: "event",
      eventType: "job.file_completed",
      payload: { file: "src/a.ts", comments: 0 },
      id: 10,
    });
    expect(done.files.get("src/a.ts")?.state).toBe("completed");
    expect(liveFileProgress(done).percent).toBe(17); // (1 + 2.0 cap) / 18 → 16.7
  });
});
