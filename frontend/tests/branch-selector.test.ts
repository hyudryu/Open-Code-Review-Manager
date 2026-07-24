import { describe, expect, it } from "vitest";
import { groupBranches } from "../src/features/reviews/BranchSelector";
import type { Branch } from "../src/types";

function branch(partial: Partial<Branch> & Pick<Branch, "id" | "name" | "kind">): Branch {
  return {
    full_ref: `refs/heads/${partial.name}`,
    remote_name: null,
    commit_sha: "abcdef0123456789",
    commit_subject: "subject",
    commit_timestamp: new Date().toISOString(),
    is_default: false,
    is_current: false,
    ...partial,
  };
}

const branches: Branch[] = [
  branch({ id: "1", name: "main", kind: "local", is_default: true }),
  branch({ id: "2", name: "feature/auth", kind: "local", is_current: true }),
  branch({ id: "3", name: "main", kind: "remote", remote_name: "origin" }),
  branch({ id: "4", name: "feature/auth", kind: "remote", remote_name: "origin" }),
  branch({ id: "5", name: "v1.2.0", kind: "tag" }),
];

describe("groupBranches", () => {
  it("groups branches into Local, Remote, and Tags in that order", () => {
    const groups = groupBranches(branches, "");
    expect(groups.map((g) => g.label)).toEqual(["Local", "Remote", "Tags"]);
    expect(groups[0].items.map((b) => b.id)).toEqual(["1", "2"]);
    expect(groups[1].items.map((b) => b.id)).toEqual(["3", "4"]);
    expect(groups[2].items.map((b) => b.id)).toEqual(["5"]);
  });

  it("filters by name substring across all groups", () => {
    const groups = groupBranches(branches, "auth");
    expect(groups.map((g) => g.label)).toEqual(["Local", "Remote"]);
    expect(groups[0].items.map((b) => b.name)).toEqual(["feature/auth"]);
    expect(groups[1].items.map((b) => b.name)).toEqual(["feature/auth"]);
  });

  it("matches against the commit subject as well", () => {
    const groups = groupBranches(branches, "subject");
    expect(groups.reduce((n, g) => n + g.items.length, 0)).toBe(branches.length);
  });

  it("omits empty groups", () => {
    const onlyLocal = branches.filter((b) => b.kind === "local");
    const groups = groupBranches(onlyLocal, "");
    expect(groups.map((g) => g.label)).toEqual(["Local"]);
  });

  it("returns no groups when nothing matches", () => {
    expect(groupBranches(branches, "zzz-no-match")).toEqual([]);
  });
});
