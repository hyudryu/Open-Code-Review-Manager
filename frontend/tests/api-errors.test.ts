import { describe, expect, it } from "vitest";
import { ApiError } from "../src/api/client";
import {
  apiFieldErrors,
  formatApiError,
  formatApiErrorDetail,
} from "../src/api/errors";

function apiError(detail: unknown, nextAction?: string | null): ApiError {
  return new ApiError(
    422,
    {
      code: "validation_failed",
      message: "The request payload is not valid.",
      detail,
      next_action: nextAction ?? null,
    },
    "",
  );
}

describe("formatApiError", () => {
  it("uses a string detail verbatim and appends next_action", () => {
    const err = new ApiError(
      409,
      {
        code: "conflict",
        message: "A review profile named 'x' already exists.",
        detail: "Name must be unique.",
        next_action: "Pick a different name.",
      },
      "",
    );
    expect(formatApiError(err)).toBe("Name must be unique.\nNext: Pick a different name.");
  });

  it("maps a {loc, msg} list to field lines, stripping the leading 'body'", () => {
    const err = apiError([
      { loc: ["body", "concurrency"], msg: "Input should be less than or equal to 64" },
      { loc: ["body", "max_tools"], msg: "Input should be greater than or equal to 1" },
    ]);
    expect(formatApiError(err)).toBe(
      "The request payload is not valid.\n" +
        "concurrency: Input should be less than or equal to 64\n" +
        "max_tools: Input should be greater than or equal to 1",
    );
  });

  it("keeps nested loc segments dotted", () => {
    const err = apiError([
      { loc: ["body", "settings", "concurrency"], msg: "too small" },
    ]);
    expect(formatApiError(err)).toContain("settings.concurrency: too small");
  });

  it("handles entries without a loc as bare messages", () => {
    const err = apiError([{ msg: "payload unreadable" }]);
    expect(formatApiError(err)).toContain("payload unreadable");
  });

  it("appends next_action for list details too", () => {
    const err = apiError(
      [{ loc: ["body", "concurrency"], msg: "too big" }],
      "Fix the highlighted fields and retry.",
    );
    expect(formatApiError(err)).toContain("Next: Fix the highlighted fields and retry.");
  });

  it("falls back to the body message when detail is null", () => {
    const err = apiError(null);
    expect(formatApiError(err)).toBe("The request payload is not valid.");
  });

  it("falls back to err.message for non-ApiError values", () => {
    expect(formatApiError(new Error("boom"))).toBe("boom");
    expect(formatApiError("plain string")).toBe("plain string");
    expect(formatApiError({ message: "object message" })).toBe("object message");
    expect(formatApiError(undefined)).toBe("An unexpected error occurred.");
  });

  it("never throws on bizarre detail shapes", () => {
    expect(() => formatApiError(apiError({ weird: true }))).not.toThrow();
    expect(() => formatApiError(apiError(42))).not.toThrow();
    expect(() => formatApiError(apiError(["a", 1, null]))).not.toThrow();
  });
});

describe("formatApiErrorDetail", () => {
  it("passes strings through", () => {
    expect(formatApiErrorDetail("oops")).toBe("oops");
  });

  it("serializes lists and objects to strings (React-child safe)", () => {
    const out = formatApiErrorDetail([{ loc: ["body", "x"], msg: "bad" }]);
    expect(typeof out).toBe("string");
    expect(out).toBe("x: bad");
    expect(typeof formatApiErrorDetail({ a: 1 })).toBe("string");
  });

  it("returns empty string for nullish detail", () => {
    expect(formatApiErrorDetail(null)).toBe("");
    expect(formatApiErrorDetail(undefined)).toBe("");
  });
});

describe("apiFieldErrors", () => {
  it("extracts per-field messages from a 422 list", () => {
    const err = apiError([
      { loc: ["body", "concurrency"], msg: "too big" },
      { loc: ["body", "max_tokens"], msg: "too small" },
    ]);
    expect(apiFieldErrors(err)).toEqual([
      { field: "concurrency", message: "too big" },
      { field: "max_tokens", message: "too small" },
    ]);
  });

  it("returns an empty list for string details and non-ApiError values", () => {
    expect(
      apiFieldErrors(
        new ApiError(400, { code: "x", message: "m", detail: "string detail" }, ""),
      ),
    ).toEqual([]);
    expect(apiFieldErrors(new Error("nope"))).toEqual([]);
  });
});
