import {
  initialLiveJobState,
  liveJobReducer,
} from "../src/hooks/useJobEvents";

describe("live job event state", () => {
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
  });
});
