import { describe, expect, it } from "vitest";
import { buildCommandPreview } from "../src/lib/command";
import { newReviewSchema } from "../src/pages/NewReviewPage";

const validForm = {
  project_id: "project-1",
  mode: "scan",
  profile_id: "",
  background: "",
  background_file: "",
  rule_file: "",
  excludes: "",
  priority: 50,
  webhook_endpoint_id: "",
};

describe("scan review mode", () => {
  it("passes new-review form validation so Queue review can submit", () => {
    expect(newReviewSchema.safeParse(validForm).success).toBe(true);
  });

  it("previews the OCR scan command instead of a diff review", () => {
    const preview = buildCommandPreview(
      { mode: "scan", repoPath: "C:/worktrees/project/job" },
      undefined,
    );

    expect(preview.argv.slice(1, 4)).toEqual([
      "scan",
      "--repo",
      "C:/worktrees/project/job",
    ]);
    expect(preview.argv).not.toContain("--from");
    expect(preview.argv).not.toContain("--commit");
  });
});
