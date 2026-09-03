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
 * a separator is a form error, not silently dropped input.
 */
export function parseHeaderLines(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of parseLines(text)) {
    const idx = line.indexOf(":");
    if (idx <= 0) {
      throw new Error(`Header line "${line}" must be "Name: value".`);
    }
    headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  }
  return headers;
}

/** Parse KEY=VALUE env lines. The value may be empty; the key may not. */
export function parseEnvLines(text: string): string[] {
  return parseLines(text).map((line) => {
    const idx = line.indexOf("=");
    if (idx <= 0) {
      throw new Error(`Env line "${line}" must be "KEY=VALUE".`);
    }
    return line;
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
