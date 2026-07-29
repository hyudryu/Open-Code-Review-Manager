## Summary

A permanent **Default** review profile, seeded at startup, that is used automatically when a review is submitted without a profile selected. The Default profile **must be configured** (provider + model) before any review that resolves to it can be queued — otherwise a graceful, actionable error is returned (MCP → structured error / UI → toast + inline error state).

## Problem

When an agent or user submits a review with no profile selected, the review has no provider or model to use.

## Solution

- **Seeded at startup** — `ProfileService.ensure_default()` runs after migrations. If a profile named `Default` already exists, it is marked `is_system = true` (preserving all settings). If none exists, a fresh empty Default is created.
- **`is_system` DB column** — a real column (not a name convention), so fallback is keyed on `is_system = true`, deletion is blocked.
- **Configuration guard** — Default must have both a **provider** and a **model** selected. Guard fires on any path resolving to Default (no-`profile_id` fallback OR explicit selection).
  - **MCP**: returns `default_profile_not_configured` error with `code`, `detail`, `next_action`.
  - **UI**: returns 422; New Review page shows inline ErrorState and fires `toast.error()`.
- **Delete protection** — Default cannot be deleted (returns `409 conflict`). Remains editable (provider, model, limits, etc.).

## Changes

### Backend (7 files)
1. `app/db/models.py` — Added `is_system: Mapped[bool]` to `ReviewProfile`.
2. `alembic/versions/0004_default_profile.py` (new) — Migration adding `is_system` column with `server_default=false()`.
3. `app/services/profiles.py` — Added `get_default()`, `ensure_default()`, delete guard for system profiles.
4. `app/services/jobs.py` — Added `_resolve_profile()` (explicit or Default fallback), `_assert_default_configured()` (guard), wired into `create()` and `preview()`. Added `DefaultProfileNotConfiguredError`.
5. `app/services/errors.py` — Added `DefaultProfileNotConfiguredError` with code `default_profile_not_configured`.
6. `app/schemas/providers.py` — Added `is_system: bool` to `ProfileOut`.
7. `app/mcp/server.py` — Updated tool descriptions and server instructions.

### Frontend (3 files)
8. `frontend/src/types/index.ts` — Added `is_system: boolean` to `ReviewProfile`.
9. `frontend/src/pages/ProfilesPage.tsx` — Hide Delete for system profiles, show Default badge.
10. `frontend/src/pages/NewReviewPage.tsx` — Toast on `default_profile_not_configured`.

### Tests (4 files)
11. `backend/tests/test_db.py` — 2 new tests (column exists, seed/adopt).
12. `backend/tests/test_mcp.py` — 3 new tests (unconfigured rejects, configured queues, delete blocked).
13. `backend/tests/test_api.py` — 2 new tests (seeds, non-deletable, fallback uses configured Default). Updated `client` fixture to configure Default.
14. `backend/tests/test_wait_for_terminal.py` — Updated local `client` fixture.

## Tests

**Backend**: 257 tests pass (7 new + all existing). One pre-existing failure: `test_build_range_command` (npm\\ocr.CMD shim — unrelated).
**Frontend**: 52 tests pass (10 files). Typecheck + build succeed.

## Verified End-to-End

Started app on port 8373 with isolated data dir:
1. `GET /api/v1/review-profiles` → Default with `is_system: true`, provider=null, model=null
2. MCP `ocr_submit_review` (no profile_id) → `default_profile_not_configured`
3. Configured Default (provider + model)
4. MCP `ocr_submit_review` (no profile_id) → queued, worker picked up, real ocr v1.8.0 executed
