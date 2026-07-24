"""Live smoke test — real backend + built frontend + fake OCR executable.

Two phases against a fresh temp data dir:

  A. Server without an OCR binary: health/info/ocr report ``ocr_not_found``
     (or any non-ok status) cleanly.
  B. Server with OCR_CC_OCR_EXECUTABLE pointing at the same fake ``ocr``
     script the pytest suite uses: folder scan (2 projects), project add,
     branch refresh, provider with an ``env:``-backed credential, profile,
     job preview, job submit → terminal state via SSE-persisted events,
     findings (reasoning opt-in), session filters, export without secrets,
     diagnostics bundle, SPA serving.

Usage (from repo root):

    backend/.venv/Scripts/python.exe scripts/smoke.py

Exits non-zero on the first failed check. Leaves no server running.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
if not VENV_PY.is_file():
    VENV_PY = ROOT / "backend" / ".venv" / "bin" / "python"

PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"
SECRET = "sk-SMOKE-SECRET-123"

CHECKS: list[str] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    CHECKS.append(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    print(CHECKS[-1])
    if not cond:
        raise SystemExit(f"smoke test failed: {name} {detail}")


def extract_fake_ocr() -> str:
    """Reuse the pytest fake-ocr script so the smoke test exercises the same
    contract as the automated suite."""

    conftest = (ROOT / "backend" / "tests" / "conftest.py").read_text(encoding="utf-8")
    match = re.search(r"FAKE_OCR_SCRIPT = r'''(.*?)'''", conftest, re.DOTALL)
    if not match:
        raise SystemExit("could not extract FAKE_OCR_SCRIPT from conftest.py")
    return match.group(1)


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=repo, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def make_workspace(base: Path) -> tuple[Path, Path]:
    repos = []
    for name in ("proj-alpha", "proj-beta"):
        repo = base / name
        repo.mkdir(parents=True)
        git(repo, "init", "-b", "main")
        git(repo, "config", "user.email", "smoke@example.com")
        git(repo, "config", "user.name", "Smoke Test")
        git(repo, "config", "commit.gpgsign", "false")
        (repo / "hello.py").write_text("print('hello')\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "initial commit")
        repos.append(repo)
    return repos[0], repos[1]


class Server:
    def __init__(self, data_dir: Path, ocr_executable: Path | None) -> None:
        env = dict(os.environ)
        env["OCR_CC_DATA_DIR"] = str(data_dir)
        env["OCR_CC_PORT"] = str(PORT)
        env["SMOKE_LLM_KEY"] = SECRET
        if ocr_executable is not None:
            env["OCR_CC_OCR_EXECUTABLE"] = str(ocr_executable)
        self.proc = subprocess.Popen(
            [str(VENV_PY), "-m", "app"],
            cwd=ROOT / "backend",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def wait_ready(self, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise SystemExit("server exited during startup")
            try:
                r = httpx.get(f"{BASE}/api/v1/health", timeout=2)
                if r.status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.5)
        raise SystemExit("server did not become ready in time")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


def csrf_headers(client: httpx.Client) -> dict[str, str]:
    return {"X-OCR-CSRF": client.cookies.get("ocrcc_csrf", "")}


def main() -> None:
    if not VENV_PY.is_file():
        raise SystemExit(f"venv python not found: {VENV_PY}")
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit("frontend/dist missing — run `npm run build` in frontend/")

    tmp = Path(tempfile.mkdtemp(prefix="ocrcc-smoke-"))
    data_dir = tmp / "data"
    workspace = tmp / "workspace"
    workspace.mkdir()
    proj_a, _proj_b = make_workspace(workspace)
    fake_ocr = tmp / "fake_ocr.py"
    fake_ocr.write_text(extract_fake_ocr(), encoding="utf-8")

    # ------------------------------------------------------------------ A
    server = Server(data_dir, ocr_executable=None)
    try:
        server.wait_ready()
        with httpx.Client(base_url=BASE, timeout=10) as client:
            r = client.get("/api/v1/health")
            ok("A: /api/v1/health", r.status_code == 200 and r.json()["status"] == "ok")
            r = client.get("/api/v1/system/info")
            ok("A: /api/v1/system/info", r.status_code == 200 and "ocr" in r.json())
            r = client.get("/api/v1/system/ocr")
            body = r.json()
            ok(
                "A: /api/v1/system/ocr reports missing OCR cleanly",
                r.status_code == 200 and body["status"] != "ok",
                f"status={body['status']}",
            )
    finally:
        server.stop()

    # ------------------------------------------------------------------ B
    server = Server(data_dir, ocr_executable=fake_ocr)
    try:
        server.wait_ready()
        with httpx.Client(base_url=BASE, timeout=30) as client:
            client.get("/api/v1/health")  # primes the CSRF cookie
            h = csrf_headers(client)

            r = client.get("/api/v1/system/ocr")
            ok("B: fake OCR detected", r.json()["status"] == "ok", r.json().get("version"))

            # Folder scan across a workspace with 2 git projects.
            r = client.post(
                "/api/v1/folders",
                json={"display_name": "smoke", "absolute_path": str(workspace)},
                headers=h,
            )
            ok("B: folder add", r.status_code == 201, r.text[:200])
            folder_id = r.json()["id"]
            r = client.post(f"/api/v1/folders/{folder_id}/scan", headers=h)
            repos = r.json()["repos"]
            ok(
                "B: folder scan finds 2 projects",
                r.status_code == 200 and len(repos) == 2,
                str([Path(p["path"]).name for p in repos]),
            )

            # Project add + branch refresh.
            r = client.post(
                "/api/v1/projects",
                json={"absolute_path": str(proj_a)},
                headers=h,
            )
            ok("B: project add", r.status_code == 201, r.text[:200])
            project_id = r.json()["id"]
            r = client.post(f"/api/v1/projects/{project_id}/refresh-branches", headers=h)
            ok("B: branch refresh", r.status_code == 200)
            r = client.get(f"/api/v1/projects/{project_id}/branches")
            ok(
                "B: branches include main",
                any(b["name"] == "main" for b in r.json()),
            )

            # Provider with an env:-backed credential + manual model.
            r = client.post(
                "/api/v1/providers",
                json={
                    "name": "SmokeProv",
                    "protocol": "openai",
                    "base_url": "https://api.example.test/v1",
                    "credential": "env:SMOKE_LLM_KEY",
                },
                headers=h,
            )
            ok("B: provider create (env: credential)", r.status_code == 201, r.text[:200])
            ok("B: provider payload has no secret", SECRET not in r.text)
            provider_id = r.json()["id"]
            r = client.post(
                f"/api/v1/providers/{provider_id}/models",
                json={"model_id": "smoke-model"},
                headers=h,
            )
            ok("B: model add", r.status_code == 201)
            model_pk = r.json()["id"]

            # Profile.
            r = client.post(
                "/api/v1/review-profiles",
                json={
                    "name": "SmokeProfile",
                    "provider_profile_id": provider_id,
                    "model_id": model_pk,
                },
                headers=h,
            )
            ok("B: profile create", r.status_code == 201, r.text[:200])
            profile_id = r.json()["id"]

            # Preview.
            r = client.post(
                "/api/v1/jobs/preview",
                json={"project_id": project_id, "mode": "commit", "commit_ref": "HEAD"},
                headers=h,
            )
            ok(
                "B: job preview",
                r.status_code == 200 and r.json()["reviewable_count"] == 1,
                r.text[:200],
            )

            # Submit + wait for terminal state.
            r = client.post(
                "/api/v1/jobs",
                json={
                    "project_id": project_id,
                    "mode": "commit",
                    "commit_ref": "HEAD",
                    "profile_id": profile_id,
                },
                headers=h,
            )
            ok("B: job submit", r.status_code == 201, r.text[:200])
            job_id = r.json()["id"]
            ok(
                "B: generated command redacts token",
                r.json()["generated_command_json"]["env"]["OCR_LLM_TOKEN"] == "***REDACTED***",
            )
            status = ""
            for _ in range(240):
                r = client.get(f"/api/v1/jobs/{job_id}")
                status = r.json()["status"]
                if status in {"completed", "completed_with_warnings", "failed", "cancelled"}:
                    break
                time.sleep(0.5)
            ok("B: job reaches terminal state", status == "completed", f"status={status}")

            # Persisted SSE event history is available (the live stream's backing store).
            r = client.get(f"/api/v1/jobs/{job_id}/events/history")
            events = r.json()
            ok(
                "B: job events recorded",
                r.status_code == 200 and any(
                    e["event_type"] == "job.status"
                    and (e["payload"] or {}).get("to") == "completed"
                    for e in events
                ),
                f"{len(events)} events",
            )

            # Findings: reasoning opt-in.
            r = client.get(f"/api/v1/jobs/{job_id}/findings")
            page = r.json()
            ok("B: findings parsed", page["total"] == 1)
            ok("B: reasoning hidden by default", page["items"][0]["thinking"] is None)
            r = client.get(f"/api/v1/jobs/{job_id}/findings?include_reasoning=true")
            ok(
                "B: reasoning opt-in works",
                r.json()["items"][0]["thinking"] == "secret chain-of-thought",
            )

            # Session inspector server-side filters.
            r = client.get(f"/api/v1/jobs/{job_id}/session?q=hello")
            ok("B: session q filter", r.status_code == 200 and r.json()["total"] == 2)
            r = client.get(f"/api/v1/jobs/{job_id}/session?task_type=plan_task")
            ok("B: session task_type filter", r.status_code == 200 and r.json()["total"] == 0)

            # Export: no secrets, no reasoning by default.
            r = client.get(f"/api/v1/jobs/{job_id}/export?format=md")
            ok(
                "B: export markdown",
                r.status_code == 200 and r.text.startswith("# OpenCodeReview Findings"),
            )
            ok("B: export has no secret", SECRET not in r.text)
            ok("B: export has no reasoning", "secret chain-of-thought" not in r.text)

            # Diagnostics bundle.
            r = client.get("/api/v1/system/diagnostics/bundle")
            ok(
                "B: diagnostics bundle",
                r.status_code == 200 and r.headers["content-type"] == "application/zip",
            )
            ok("B: bundle has no secret", SECRET.encode() not in r.content)

            # SPA served by the same process.
            r = client.get("/")
            ok("B: SPA index served", r.status_code == 200 and "<div id=\"root\">" in r.text)
            r = client.get("/reviews")
            ok("B: SPA fallback route", r.status_code == 200)
    finally:
        server.stop()

    print(f"\n{len(CHECKS)} checks passed. Temp dir: {tmp}")


if __name__ == "__main__":
    main()
