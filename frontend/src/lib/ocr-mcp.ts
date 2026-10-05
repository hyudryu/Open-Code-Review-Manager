/**
 * Parsing/serialization helpers for the OCR MCP server editor form. The OCR
 * config stores `args`/`tools`/`env` as string arrays and `headers` as an
 * object; the form edits them as line-based text.
 */

/** Split a textarea blob into trimmed, non-empty lines. */
export function parseLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** Join an optional string list back into newline-separated text. */
export function listToText(items?: string[] | null): string {
  return (items ?? []).join("\n");
}

/**
 * Parse "Name: value" header lines into an object. The value may be empty
 * (OCR then expands `$VAR` references at connection time); a line without
 * a separator is a form error, not silently dropped input. Error messages
 * reference the line number only — the raw line may hold a credential.
 */
export function parseHeaderLines(text: string): Record<string, string> {
  const headers: Record<string, string> = Object.create(null);
  parseLines(text).forEach((line, index) => {
    const idx = line.indexOf(":");
    if (idx <= 0) {
      throw new Error(
        `Header line ${index + 1} is malformed; expected "Name: value".`,
      );
    }
    headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  });
  return headers;
}

/** Parse KEY=VALUE env lines, normalizing whitespace around the separator.
 * The value may be empty; the key may not. Error messages reference the
 * line number only — the raw line may hold a credential. */
export function parseEnvLines(text: string): string[] {
  return parseLines(text).map((line, index) => {
    const idx = line.indexOf("=");
    if (idx <= 0) {
      throw new Error(
        `Env line ${index + 1} is malformed; expected "KEY=VALUE".`,
      );
    }
    return `${line.slice(0, idx).trim()}=${line.slice(idx + 1).trim()}`;
  });
}

/** Join a headers object back into "Name: value" lines. */
export function headersToText(headers?: Record<string, string> | null): string {
  return Object.entries(headers ?? {})
    .map(([name, value]) => `${name}: ${value}`)
    .join("\n");
}

/** Split a comma-separated tool allowlist into names. */
export function parseToolList(text: string): string[] {
  return text
    .split(",")
    .map((name) => name.trim())
    .filter((name) => name.length > 0);
}

/** Server-name constraint shared with the backend schema (no dots — they are
 * the `ocr config set` key separator). */
export const OCR_MCP_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

export function isValidMcpServerName(name: string): boolean {
  return OCR_MCP_NAME_PATTERN.test(name);
}
