/**
 * Shared API error formatting (SPEC §29).
 *
 * The backend error envelope is `{error: {code, message, detail, next_action}}`
 * where `detail` is a string for service errors but a LIST of Pydantic-style
 * `{loc, msg}` entries for 422 payload validation failures. Rendering that
 * list directly as a React child throws and unmounts the whole tree — every
 * surface must go through these formatters instead.
 */

import { ApiError } from "./client";

export interface ApiFieldError {
  field: string;
  message: string;
}

interface DetailEntry {
  loc?: unknown;
  msg?: unknown;
}

/** Format one Pydantic-style `{loc, msg}` entry as `"field.name: msg"`. */
function formatDetailEntry(entry: unknown): string {
  if (entry && typeof entry === "object") {
    const { loc, msg } = entry as DetailEntry;
    const message = typeof msg === "string" ? msg : String(msg ?? "");
    if (Array.isArray(loc)) {
      // Strip the leading "body" segment: ["body","concurrency"] → "concurrency".
      const parts = loc
        .map(String)
        .filter((part, index) => !(index === 0 && part === "body"));
      if (parts.length) return `${parts.join(".")}: ${message}`;
    }
    return message;
  }
  return String(entry);
}

/**
 * Format the raw `detail` value from the error envelope into a safe string.
 * Handles string, `{loc, msg}` lists, and arbitrary shapes without ever
 * returning a non-string (so it is always safe as a React child).
 */
export function formatApiErrorDetail(detail: unknown): string {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(formatDetailEntry).filter(Boolean).join("\n");
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

/**
 * Human-readable multi-line summary of any thrown value.
 *
 * ApiError: string detail → detail; `{loc, msg}` list detail → message plus
 * one `"field: msg"` line per entry; otherwise the body/Error message.
 * `next_action` is appended when present.
 */
export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body;
    const detail = body?.detail;
    let text: string;
    if (typeof detail === "string" && detail.trim()) {
      text = detail;
    } else if (Array.isArray(detail) && detail.length > 0) {
      const lines = formatApiErrorDetail(detail);
      const message = body?.message?.trim();
      text = message ? `${message}\n${lines}` : lines;
    } else {
      text = body?.message ?? err.message;
    }
    const nextAction = body?.next_action?.trim();
    if (nextAction) text = `${text}\nNext: ${nextAction}`;
    return text;
  }
  if (err instanceof Error) return err.message;
  if (err && typeof err === "object" && "message" in err) {
    const message = (err as { message: unknown }).message;
    if (typeof message === "string") return message;
  }
  return String(err ?? "An unexpected error occurred.");
}

/**
 * Per-field messages extracted from a 422 `{loc, msg}` detail list, keyed by
 * the first location segment after "body" (e.g. `concurrency`). Returns an
 * empty list for non-ApiError values or non-list details.
 */
export function apiFieldErrors(err: unknown): ApiFieldError[] {
  if (!(err instanceof ApiError)) return [];
  const detail = err.body?.detail;
  if (!Array.isArray(detail)) return [];
  const out: ApiFieldError[] = [];
  for (const entry of detail) {
    if (!entry || typeof entry !== "object") continue;
    const { loc, msg } = entry as DetailEntry;
    if (!Array.isArray(loc) || typeof msg !== "string") continue;
    const parts = loc
      .map(String)
      .filter((part, index) => !(index === 0 && part === "body"));
    if (parts.length) out.push({ field: parts[0], message: msg });
  }
  return out;
}
