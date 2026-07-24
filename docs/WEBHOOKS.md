# Webhooks

The control center delivers signed webhook notifications when a review job
changes state. Administration endpoints are under `/api/v1/webhooks` (see
[API.md](API.md)); this document is the receiver-side reference.

## Events

```text
review.queued
review.started
review.completed
review.completed_with_warnings
review.failed
review.cancelled
```

An endpoint may subscribe to a subset (`allowed_events`); by default all
events are delivered. Every job transition to one of these states dispatches
exactly one delivery per subscribed endpoint.

## Payload

`POST` with `Content-Type: application/json`:

```json
{
  "id": "0192…",                       // delivery id — the idempotency key
  "event": "review.completed",
  "created_at": "2026-07-24T09:30:00Z",
  "job": {
    "id": "…", "source": "web", "status": "completed",
    "project_id": "…", "project_name": "my-repo",
    "mode": "range",
    "base_ref": "main", "target_ref": "feature/x",
    "base_sha": "…", "target_sha": "…",
    "provider": "Anthropic", "model": "claude-opus-4-6",
    "queued_at": "…", "started_at": "…", "completed_at": "…"
  },
  "summary": {
    "files_reviewed": 12, "comments": 4, "warnings": 0,
    "input_tokens": 81234, "output_tokens": 4021,
    "total_tokens": 85255, "elapsed_ms": 93000
  },
  "findings": [
    {
      "path": "src/app.py", "start_line": 42, "end_line": 47,
      "content": "…", "existing_code": "…", "suggestion_code": "…"
    }
  ],
  "warnings": [],
  "metadata": {}
}
```

Payloads never contain credentials, auth headers, or raw model reasoning
(`thinking`).

## Headers and signing

```text
X-OCR-Event: review.completed
X-OCR-Delivery: 0192…                  // == payload.id
X-OCR-Timestamp: 1721800200            // unix seconds
X-OCR-Signature-256: sha256=<hex>      // only when the endpoint has a secret
```

Signature algorithm:

```text
X-OCR-Signature-256 = "sha256=" + HMAC_SHA256(secret, timestamp + "." + raw_body)
```

Sign over the **raw request body bytes** — do not re-serialize the JSON.
Reject timestamps outside a ±5 minute window to defeat replay.

### Verification — Python

```python
import hashlib, hmac, time

def verify(secret: str, headers: dict, raw_body: bytes, tolerance: int = 300) -> bool:
    ts = headers.get("X-OCR-Timestamp", "")
    sig = headers.get("X-OCR-Signature-256", "")
    if not ts.isdigit() or abs(time.time() - int(ts)) > tolerance:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), ts.encode() + b"." + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)
```

### Verification — Node.js

```js
const crypto = require("crypto");

function verify(secret, headers, rawBody, tolerance = 300) {
  const ts = headers["x-ocr-timestamp"] ?? "";
  const sig = headers["x-ocr-signature-256"] ?? "";
  if (!/^\d+$/.test(ts) || Math.abs(Date.now() / 1000 - Number(ts)) > tolerance)
    return false;
  const expected =
    "sha256=" +
    crypto.createHmac("sha256", secret).update(ts + ".").update(rawBody).digest("hex");
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig));
}
// With Express, capture the raw body: express.raw({ type: "application/json" })
```

### Verification — curl (manual check)

```bash
SECRET='whsec_…'; TS='1721800200'
BODY=$(cat payload.json)   # exact bytes that were POSTed
printf '%s' "$TS.$BODY" | openssl dgst -sha256 -hmac "$SECRET"
# → sha256=<hex> — compare with the X-OCR-Signature-256 header value
```

## Delivery policy

- **Success** — any 2xx. The delivery is marked `succeeded`.
- **No retry** — 400, 401, 403, 404, 410: marked `failed` permanently.
- **Retry** — everything else (408/409/425/429/5xx, network errors,
  timeouts). A `Retry-After` response header (seconds or HTTP-date) overrides
  the schedule for that attempt.
- **Retry schedule** — fixed backoff after attempts 1…7 fail:
  `0s, 60s, 5m, 30m, 2h, 12h, 24h` plus up to 20% random jitter. After the
  schedule is exhausted the delivery is marked `failed`.
- **Timeouts/limits** — 15 s request timeout, redirects capped at 3, response
  bodies read at most 64 KB and stored as a 500-character redacted excerpt.
- **SSRF guards** — HTTPS is required by default and private/loopback targets
  are rejected unless explicitly enabled in settings
  (`webhooks.require_https`, `webhooks.allow_private_networks`).

## Idempotency and replay

`X-OCR-Delivery` (== `payload.id`) is the idempotency key: receivers should
store seen ids and drop duplicates. Replays triggered from the UI or
`POST /api/v1/webhook-deliveries/{id}/replay` keep the **same** delivery id,
so idempotent receivers safely ignore them.

Failed and succeeded deliveries are inspectable via
`GET /api/v1/webhooks/{id}/deliveries` (status, http_status, attempt count,
next attempt time, redacted response excerpt).
