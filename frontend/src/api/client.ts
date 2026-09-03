/**
 * Typed fetch client with CSRF double-submit handling (SPEC §27).
 *
 * The backend sets an `ocrcc_csrf` cookie on any safe /api/ response; every
 * state-changing request must echo it in the `X-OCR-CSRF` header.
 */

export interface ApiErrorDetail {
  code: string;
  message: string;
  /**
   * String for service errors; a Pydantic-style `{loc, msg}` LIST for 422
   * payload validation failures. Always format via `formatApiError` /
   * `formatApiErrorDetail` (src/api/errors.ts) before rendering.
   */
  detail?: unknown;
  next_action?: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorDetail | null;

  constructor(status: number, body: ApiErrorDetail | null, raw: string) {
    super(body?.message ?? raw ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  get code(): string {
    return this.body?.code ?? "unknown_error";
  }
  get detail(): unknown {
    return this.body?.detail ?? null;
  }
  get nextAction(): string | null {
    return this.body?.next_action ?? null;
  }
}

const CSRF_COOKIE = "ocrcc_csrf";

function readCsrfCookie(): string | null {
  const match = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${CSRF_COOKIE}=`));
  return match ? decodeURIComponent(match.slice(CSRF_COOKIE.length + 1)) : null;
}

/** Prime the CSRF cookie by fetching the health endpoint. */
async function primeCsrf(): Promise<void> {
  try {
    await fetch("/api/v1/health", { credentials: "same-origin" });
  } catch {
    // Prime failed – the defensive retry will handle stale 403s.
  }
}

export type QueryParams = Record<
  string,
  string | number | boolean | null | undefined
>;

export function buildQuery(params?: QueryParams): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const out = search.toString();
  return out ? `?${out}` : "";
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  params?: QueryParams,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && method !== "HEAD") {
    // Always prime before mutations so a backend restart can replace any
    // stale CSRF cookie before the mutation is sent.
    await primeCsrf();
    const token = readCsrfCookie();
    if (token) headers["X-OCR-CSRF"] = token;
  }

  let response: Response;
  try {
    response = await fetch(`${path}${buildQuery(params)}`, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      0,
      {
        code: "network_error",
        message: "Could not reach the control center backend.",
        detail: "The request never reached the server.",
        next_action: "Check that the backend is running, then retry.",
      },
      "",
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  // Defensive CSRF retry: if we get a 403 csrf_failed, the cookie may not
  // have been set (e.g. CORS stripping Set-Cookie for cross-origin Vite dev).
  // Prime the cookie with a GET and retry the original request once.
  if (
    response.status === 403 &&
    parsed &&
    typeof parsed === "object" &&
    "error" in parsed &&
    (parsed as { error: { code: string } }).error?.code === "csrf_failed"
  ) {
    try {
      const prime = await fetch("/api/v1/health", {
        credentials: "same-origin",
      });
      if (prime.ok) {
        const retryToken = readCsrfCookie();
        if (retryToken) {
          headers["X-OCR-CSRF"] = retryToken;
          const retryResp = await fetch(`${path}${buildQuery(params)}`, {
            method,
            headers,
            credentials: "same-origin",
            body: body === undefined ? undefined : JSON.stringify(body),
          });

          if (!retryResp.ok) {
            const retryText = await retryResp.text();
            let retryParsed: unknown = null;
            try {
              retryParsed = JSON.parse(retryText);
            } catch {
              retryParsed = null;
            }
            const retryBody =
              retryParsed && typeof retryParsed === "object" && "error" in retryParsed
                ? ((retryParsed as { error: ApiErrorDetail }).error ?? null)
                : retryParsed && typeof retryParsed === "object" && "detail" in retryParsed
                  ? ({
                      code: "request_failed",
                      message:
                        typeof (retryParsed as { detail: unknown }).detail === "string"
                          ? ((retryParsed as { detail: string }).detail ?? "")
                          : "The request failed.",
                      detail:
                        typeof (retryParsed as { detail: unknown }).detail === "string"
                          ? null
                          : (retryParsed as { detail: unknown }).detail,
                    } satisfies ApiErrorDetail)
                  : null;
            throw new ApiError(retryResp.status, retryBody, retryText.slice(0, 200));
          }

          if (retryResp.status === 204) return undefined as T;

          const retryText = await retryResp.text();
          let retryParsed2: unknown = null;
          try {
            retryParsed2 = JSON.parse(retryText);
          } catch {
            retryParsed2 = null;
          }
          return retryParsed2 as T;
        }
      }
    } catch {
      // Prime failed – fall through to original error.
    }
  }

  if (!response.ok) {
    const body =
      parsed && typeof parsed === "object" && "error" in parsed
        ? ((parsed as { error: ApiErrorDetail }).error ?? null)
        : parsed && typeof parsed === "object" && "detail" in parsed
          ? ({
              code: "request_failed",
              message:
                typeof (parsed as { detail: unknown }).detail === "string"
                  ? ((parsed as { detail: string }).detail ?? "")
                  : "The request failed.",
              // Preserve non-string details (e.g. Pydantic {loc, msg} lists)
              // so formatters can render them instead of crashing.
              detail:
                typeof (parsed as { detail: unknown }).detail === "string"
                  ? null
                  : (parsed as { detail: unknown }).detail,
            } satisfies ApiErrorDetail)
          : null;
    throw new ApiError(response.status, body, text.slice(0, 200));
  }

  return parsed as T;
}

/** Fetch a text/binary export (downloads). Throws ApiError on failure. */
export async function requestText(path: string, params?: QueryParams): Promise<string> {
  const response = await fetch(`${path}${buildQuery(params)}`, {
    credentials: "same-origin",
    headers: { Accept: "text/plain, application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status, null, `Export failed (${response.status})`);
  }
  return response.text();
}

export const api = {
  get: <T>(path: string, params?: QueryParams, signal?: AbortSignal) =>
    request<T>("GET", path, undefined, params, signal),
  post: <T>(path: string, body?: unknown, params?: QueryParams) =>
    request<T>("POST", path, body, params),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};
