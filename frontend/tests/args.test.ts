import { describe, expect, it } from "vitest";
import { parseAdditionalArgs } from "../src/lib/args";

describe("parseAdditionalArgs", () => {
  it("parses simple flag/value pairs into an argv array", () => {
    const result = parseAdditionalArgs("--some-flag value --other");
    expect(result.ok).toBe(true);
    expect(result.argv).toEqual(["--some-flag", "value", "--other"]);
  });

  it("respects single and double quotes", () => {
    const result = parseAdditionalArgs(`--name "hello world" --path 'a b'`);
    expect(result.ok).toBe(true);
    expect(result.argv).toEqual(["--name", "hello world", "--path", "a b"]);
  });

  it("returns empty argv for blank input", () => {
    expect(parseAdditionalArgs("   ").argv).toEqual([]);
    expect(parseAdditionalArgs("").ok).toBe(true);
  });

  it("rejects shell metacharacters", () => {
    for (const input of [
      "--flag; rm -rf /",
      "--flag $(whoami)",
      "--flag `id`",
      "--flag | tee out",
      "--flag > /tmp/x",
      "--flag a && b",
      "--flag *",
    ]) {
      const result = parseAdditionalArgs(input);
      expect(result.ok).toBe(false);
      expect(result.error).toBeTruthy();
    }
  });

  it("rejects control-plane-owned flags", () => {
    for (const flag of ["--repo", "--from", "--to", "--format", "--audience", "--resume", "--model", "--exclude", "--concurrency"]) {
      const result = parseAdditionalArgs(`${flag} value`);
      expect(result.ok).toBe(false);
      expect(result.error).toContain(flag);
    }
  });

  it("rejects unterminated quotes", () => {
    const result = parseAdditionalArgs(`--name "unterminated`);
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/unterminated/i);
  });

  it("rejects bundled short flags", () => {
    const result = parseAdditionalArgs("-abc");
    expect(result.ok).toBe(false);
  });
});
