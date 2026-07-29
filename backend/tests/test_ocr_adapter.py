"""OCRAdapter: capabilities, command generation, env/config, parsing."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.core.logging import redact_text
from app.core.security import redact_environment
from app.ocr.adapter import OCRAdapter, ResultParseError, UnsupportedFeatureError
from app.ocr.models import OCRCapabilities, ProviderResolution, ReviewJobContext

# Help text captured from upstream cmd/opencodereview/flags.go printReviewUsage.
REVIEW_HELP = """
Usage:
  ocr review [flags]

Flags:
  --audience string             output audience: human (show progress) or agent (summary only) (default "human")
  -b, --background string       optional requirement/business context for the review
  -B, --background-file string  path to a Markdown file used as review background
  -c, --commit string           single commit hash or tag to review (vs its parent)
  -f, --format string           output format: text or json (default "text")
  --concurrency int             max concurrent file reviews (default 8)
  --max-git-procs int           max concurrent git subprocesses (default 16)
  --from string                 source ref to start diff from (e.g., 'main')
  --max-tools int               max tool call rounds per file (0 = template default; min 10)
  --model string                override LLM model for this review
  -p, --preview                 preview which files will be reviewed without running the LLM
  --repo string                 root directory of the git repository (default: current dir)
  --resume string               resume from a previous review session id
  --rule string                 path to JSON file with system review rules
  --timeout int                 concurrent task timeout in minutes (default 10)
  --to string                   target ref to end diff at (e.g., 'feature-branch')
  --tools string                path to JSON tools config file (default: embedded)
"""

ROOT_HELP = """
Usage:
  ocr <command> [flags]

Commands:
  review       Run a code review
  scan         Scan files
  rules        Manage rules
  config       Manage configuration
  llm          LLM utilities (test, providers)
  viewer       Open the viewer
  version      Show version information
"""

# Help lines exactly as printed by a patched ocr binary that includes
# the planning-controls flags.
PATCHED_HELP_SUFFIX = """
  --plan-mode string            planning behavior: auto (threshold-based), always, never (default "auto")
  --plan-threshold int          changed-line threshold for planning in auto mode (0 = template default)
  --max-tokens int              token budget per file (0 = template default)
  --template string             path to a custom task template JSON file (replaces the embedded template)
"""


# --- capability parsing --------------------------------------------------------


def test_capabilities_from_stock_help() -> None:
    caps = OCRAdapter.parse_capabilities(REVIEW_HELP, ROOT_HELP)
    assert caps.json_output and caps.agent_audience
    assert caps.resume and caps.background_file and caps.exclude_flag
    assert caps.preview and caps.model_override and caps.max_git_procs_flag
    assert caps.llm_test and caps.scan and caps.rules_check and caps.viewer
    assert caps.config_set
    # Planning patch flags are absent on stock upstream builds.
    assert not caps.plan_mode
    assert not caps.plan_threshold
    assert not caps.max_tokens
    assert not caps.template_override


def test_capabilities_from_patched_help() -> None:
    caps = OCRAdapter.parse_capabilities(REVIEW_HELP + PATCHED_HELP_SUFFIX, ROOT_HELP)
    assert caps.plan_mode and caps.plan_threshold
    assert caps.max_tokens and caps.template_override


def test_patched_help_fixture_matches_planning_patch() -> None:
    """The patched-help fixture must match the shipped patch's usage lines,
    so the capability probe is tested against the exact text a patched
    binary prints."""

    patch_path = (
        Path(__file__).resolve().parents[2]
        / "patches"
        / "open-code-review"
        / "0001-planning-controls.patch"
    )
    assert patch_path.is_file(), "planning-controls patch missing"
    added = [
        line[1:]
        for line in patch_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    usage_lines = [line for line in added if line.strip().startswith("--")]
    assert len(usage_lines) == 4, usage_lines
    for flag in ("--plan-mode", "--plan-threshold", "--max-tokens", "--template"):
        assert any(line.strip().startswith(flag) for line in usage_lines), flag
        assert any(line in PATCHED_HELP_SUFFIX for line in usage_lines), (
            "fixture drifted from patch help text"
        )


def test_parse_version() -> None:
    assert OCRAdapter.parse_version("opencodereview version 1.2.3 (abc)") == "1.2.3"
    assert OCRAdapter.parse_version("no version here") is None


# --- command generation ----------------------------------------------------------

STOCK = OCRAdapter.parse_capabilities(REVIEW_HELP, ROOT_HELP)
PATCHED = OCRAdapter.parse_capabilities(REVIEW_HELP + PATCHED_HELP_SUFFIX, ROOT_HELP)


def _ctx(**kwargs) -> ReviewJobContext:
    return ReviewJobContext(repo_path="C:/worktrees/p1/j1", **kwargs)


def test_build_range_command(adapter: OCRAdapter) -> None:
    argv = adapter.build_review_command(
        _ctx(
            mode="range",
            base_ref="main",
            target_ref="feature/x",
            base_sha="a" * 40,
            target_sha="b" * 40,
            concurrency=4,
            per_file_timeout_minutes=15,
            max_tools=20,
            max_git_processes=8,
            exclude_patterns=["*.lock", "dist/**"],
            rule_file_path="C:/rules/custom.json",
            model="qwen3",
            background="focus on auth",
        ),
        STOCK,
    )
    assert argv[0] == "ocr"
    assert argv[1] == "review"
    assert "--from" in argv and "a" * 40 in argv
    assert "--to" in argv and "b" * 40 in argv
    # Forced runner-owned flags.
    assert argv[-4:] == ["--format", "json", "--audience", "agent"]
    # --exclude is a single comma-separated value.
    i = argv.index("--exclude")
    assert argv[i + 1] == "*.lock,dist/**"
    assert "--background" in argv
    assert "--model" in argv


def test_build_commit_command(adapter: OCRAdapter) -> None:
    argv = adapter.build_review_command(
        _ctx(mode="commit", commit_sha="c" * 40), STOCK
    )
    assert "--commit" in argv
    assert "c" * 40 in argv
    assert "--from" not in argv and "--to" not in argv


def test_build_workspace_command(adapter: OCRAdapter) -> None:
    argv = adapter.build_review_command(_ctx(mode="workspace"), STOCK)
    for flag in ("--from", "--to", "--commit"):
        assert flag not in argv
    assert argv[-4:] == ["--format", "json", "--audience", "agent"]


def test_command_requires_mode_inputs(adapter: OCRAdapter) -> None:
    with pytest.raises(ValueError):
        adapter.build_review_command(_ctx(mode="range", base_ref="main"), STOCK)
    with pytest.raises(ValueError):
        adapter.build_review_command(_ctx(mode="commit"), STOCK)


def test_plan_flags_unsupported_on_stock(adapter: OCRAdapter) -> None:
    with pytest.raises(UnsupportedFeatureError) as exc:
        adapter.build_review_command(_ctx(mode="workspace", plan_mode="always"), STOCK)
    assert exc.value.feature == "plan_mode"
    with pytest.raises(UnsupportedFeatureError):
        adapter.build_review_command(_ctx(mode="workspace", plan_threshold_lines=100), STOCK)
    with pytest.raises(UnsupportedFeatureError):
        adapter.build_review_command(_ctx(mode="workspace", max_tokens=10000), STOCK)
    with pytest.raises(UnsupportedFeatureError):
        adapter.build_review_command(_ctx(mode="workspace", template_path="C:/t.json"), STOCK)


def test_plan_flags_emitted_when_patched(adapter: OCRAdapter) -> None:
    argv = adapter.build_review_command(
        _ctx(
            mode="workspace",
            plan_mode="never",
            plan_threshold_lines=120,
            max_tokens=40000,
            template_path="C:/tpl/task.json",
        ),
        PATCHED,
    )
    for flag in ("--plan-mode", "--plan-threshold", "--max-tokens", "--template"):
        assert flag in argv
    i = argv.index("--plan-mode")
    assert argv[i + 1] == "never"


def test_additional_arguments_appended_before_forced(adapter: OCRAdapter) -> None:
    argv = adapter.build_review_command(
        _ctx(mode="workspace", additional_arguments=["--some-future-flag", "v"]),
        STOCK,
    )
    i = argv.index("--some-future-flag")
    assert argv[i + 1] == "v"
    assert argv[-4:] == ["--format", "json", "--audience", "agent"]


def test_resume_requires_capability(adapter: OCRAdapter) -> None:
    no_resume = STOCK.model_copy(update={"resume": False})
    with pytest.raises(UnsupportedFeatureError):
        adapter.build_review_command(
            _ctx(mode="range", base_sha="a" * 40, target_sha="b" * 40,
                 resume_session_id="sess-1"),
            no_resume,
        )
    argv = adapter.build_review_command(
        _ctx(mode="range", base_sha="a" * 40, target_sha="b" * 40,
             resume_session_id="sess-1"),
        STOCK,
    )
    assert "--resume" in argv and "sess-1" in argv


def test_preview_command_inserts_preview_flag(adapter: OCRAdapter) -> None:
    argv = adapter.build_preview_command(_ctx(mode="workspace"), STOCK)
    assert "--preview" in argv
    assert argv[-4:] == ["--format", "json", "--audience", "agent"]


# --- environment + config -------------------------------------------------------

PROVIDER = ProviderResolution(
    base_url="https://llm.example.com/v1",
    token="sk-live-secret-abcdef",
    model="qwen3-35b",
    protocol="openai",
    auth_header="x-api-key",
    http_timeout_seconds=900,
    extra_headers={"X-Tenant": "acme-corp"},
    extra_body={"thinking": {"type": "disabled"}},
    language="English",
)


def test_build_job_environment(adapter: OCRAdapter, tmp_path: Path) -> None:
    home = tmp_path / "jobhome"
    env = adapter.build_job_environment(home, PROVIDER)
    assert env["HOME"] == str(home.resolve())
    assert env["USERPROFILE"] == str(home.resolve())
    assert env["OCR_LLM_URL"] == PROVIDER.base_url
    assert env["OCR_LLM_TOKEN"] == PROVIDER.token
    assert env["OCR_LLM_MODEL"] == PROVIDER.model
    assert env["OCR_LLM_PROTOCOL"] == "openai"
    assert env["OCR_USE_ANTHROPIC"] == "false"
    assert env["OCR_LLM_TIMEOUT"] == "900"
    assert env["OCR_LLM_AUTH_HEADER"] == "x-api-key"
    # Grounded format: K=V,K=V, not JSON.
    assert env["OCR_LLM_EXTRA_HEADERS"] == "X-Tenant=acme-corp"
    # Redacted copy for previews hides the token only.
    shown = redact_environment(env)
    assert shown["OCR_LLM_TOKEN"] == "***REDACTED***"
    assert shown["OCR_LLM_URL"] == PROVIDER.base_url
    # The token is registered with the global log redactor.
    assert PROVIDER.token not in redact_text(f"token={PROVIDER.token}")


def test_build_job_environment_strips_inherited(
    adapter: OCRAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCR_LLM_TOKEN", "stale-token-from-parent")
    env = adapter.build_job_environment(
        tmp_path, ProviderResolution(base_url="http://x", model="m", protocol="anthropic")
    )
    assert "OCR_LLM_TOKEN" not in env  # no token configured -> not set
    assert env["OCR_USE_ANTHROPIC"] == "true"


def test_write_job_config_excludes_secrets(adapter: OCRAdapter, tmp_path: Path) -> None:
    home = tmp_path / "jobhome"
    config_path = adapter.write_job_config(home, PROVIDER)
    assert config_path == home.resolve() / ".opencodereview" / "config.json"
    raw = config_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["llm"]["model"] == "qwen3-35b"
    assert data["llm"]["protocol"] == "openai"
    assert data["llm"]["timeout_sec"] == 900
    assert data["llm"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert data["language"] == "English"
    assert data["telemetry"]["enabled"] is False
    # Token and extra headers never touch disk.
    assert "sk-live-secret-abcdef" not in raw
    assert "auth_token" not in raw
    assert "acme-corp" not in raw
    # Sessions dir is prepared for the job.
    assert (home.resolve() / ".opencodereview" / "sessions").is_dir()


# --- result parsing --------------------------------------------------------------

SAMPLE_RESULT = {
    "status": "success",
    "trace_id": "tr-1",
    "session_id": "sess-42",
    "summary": {
        "files_reviewed": 3,
        "comments": 2,
        "input_tokens": 42000,
        "output_tokens": 3800,
        "cache_read_tokens": 1000,
        "cache_write_tokens": 500,
        "total_tokens": 45800,
        "elapsed": "4m57s",
    },
    "tool_calls": {"total": 7, "by_tool": {"read_file": 5, "grep": 2}},
    "comments": [
        {
            "path": "src/auth.py",
            "content": "Token compared with == instead of hmac.compare_digest",
            "start_line": 42,
            "end_line": 47,
            "existing_code": "if token == expected:",
            "suggestion_code": "if hmac.compare_digest(token, expected):",
            "thinking": "timing attack risk",
        },
        {
            "path": "src/util.py",
            "content": "Unanchored general note",
            "start_line": 0,
            "end_line": 0,
        },
    ],
    "warnings": [
        {"file": "src/big.py", "message": "per-file timeout exceeded", "type": "timeout"}
    ],
    "project_summary": "small project",
    "resume": {"resumed_from": "sess-1", "reused_files": 2, "rerun_files": 1},
}


def test_parse_result_json(adapter: OCRAdapter, tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(SAMPLE_RESULT), encoding="utf-8")
    parsed = adapter.parse_result_json(result_path)
    assert parsed.status == "success"
    assert parsed.session_id == "sess-42"
    assert len(parsed.findings) == 2
    f0 = parsed.findings[0]
    assert f0.path == "src/auth.py"
    assert f0.start_line == 42 and f0.end_line == 47
    assert f0.suggestion_code and "compare_digest" in f0.suggestion_code
    # Severity must NOT be invented when absent.
    assert f0.severity is None
    assert parsed.warnings[0].type == "timeout"
    assert parsed.summary.total_tokens == 45800
    assert parsed.summary.cache_read_tokens == 1000
    assert parsed.tool_calls == {"read_file": 5, "grep": 2}
    assert parsed.resume and parsed.resume["reused_files"] == 2


def test_parse_result_json_severity_passthrough(adapter: OCRAdapter, tmp_path: Path) -> None:
    data = {"status": "success", "comments": [
        {"path": "a.py", "content": "x", "severity": "high", "category": "security"}
    ]}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    parsed = adapter.parse_result_json(p)
    assert parsed.findings[0].severity == "high"
    assert parsed.findings[0].category == "security"


def test_parse_result_json_malformed(adapter: OCRAdapter, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ResultParseError):
        adapter.parse_result_json(bad)
    with pytest.raises(ResultParseError):
        adapter.parse_result_json(tmp_path / "missing.json")


# --- session JSONL tail parsing ---------------------------------------------------

SESSION_LINES = [
    {"type": "session_start", "sessionId": "sess-1", "timestamp": "2026-07-23T09:55:00Z",
     "cwd": "/repo", "gitBranch": "main", "model": "qwen3"},
    {"type": "llm_request", "filePath": "src/a.py", "taskType": "plan_task", "requestNo": 1},
    {"type": "llm_response", "filePath": "src/a.py", "taskType": "plan_task",
     "usage": {"prompt_tokens": 1200, "completion_tokens": 300,
               "cache_read_tokens": 100, "cache_write_tokens": 50},
     "duration_seconds": 2.5},
    {"type": "tool_call", "filePath": "src/a.py", "taskType": "main_task",
     "tool": "read_file", "duration_ms": 12},
    {"type": "review_item_done", "filePath": "src/a.py", "comments": [{"path": "src/a.py"}]},
    {"type": "llm_error", "filePath": "src/b.py", "taskType": "main_task",
     "requestNo": 2, "error": "provider 500"},
]


def test_parse_session_jsonl_full(adapter: OCRAdapter, tmp_path: Path) -> None:
    session = tmp_path / "sess.jsonl"
    session.write_text(
        "\n".join(json.dumps(line) for line in SESSION_LINES) + "\n", encoding="utf-8"
    )
    events, offset = adapter.parse_session_jsonl(session)
    assert len(events) == 6
    assert offset == session.stat().st_size
    assert events[0].record_type == "session_start"
    assert events[0].session_id == "sess-1"
    assert events[0].timestamp is not None
    resp = events[2]
    assert resp.task_type == "plan_task"
    assert resp.prompt_tokens == 1200
    assert resp.cache_read_tokens == 100
    assert resp.duration_ms == 2500
    assert events[3].tool_name == "read_file"
    assert events[4].record_type == "review_item_done"
    assert events[4].comments_count == 1
    assert events[5].error == "provider 500"


def test_parse_session_jsonl_incremental_partial_line(
    adapter: OCRAdapter, tmp_path: Path
) -> None:
    session = tmp_path / "sess.jsonl"
    line1_b = (json.dumps(SESSION_LINES[0]) + "\n").encode()
    # Write bytes: text mode would translate \n to \r\n on Windows.
    session.write_bytes(line1_b + b'{"type": "llm_req')
    events, offset = adapter.parse_session_jsonl(session)
    assert len(events) == 1  # partial trailing line not consumed
    assert offset == len(line1_b)

    # Writer completes the partial line and appends another.
    line2_b = (json.dumps(SESSION_LINES[1]) + "\n").encode()
    with session.open("ab") as fh:
        fh.write(b'uest", "filePath": "x.py"}\n')
        fh.write(line2_b)
    events2, offset2 = adapter.parse_session_jsonl(session, offset=offset)
    assert offset2 == session.stat().st_size
    assert [e.record_type for e in events2] == ["llm_request", "llm_request"]
    assert events2[1].file_path == "src/a.py"


def test_parse_session_jsonl_missing_file(adapter: OCRAdapter, tmp_path: Path) -> None:
    events, offset = adapter.parse_session_jsonl(tmp_path / "nope.jsonl", offset=10)
    assert events == [] and offset == 10


def test_parse_session_jsonl_skips_bad_lines(adapter: OCRAdapter, tmp_path: Path) -> None:
    session = tmp_path / "sess.jsonl"
    session.write_text(
        '{"type":"session_start"}\nnot-json\n[1,2]\n{"type":"session_end"}\n',
        encoding="utf-8",
    )
    events, _ = adapter.parse_session_jsonl(session)
    assert [e.record_type for e in events] == ["session_start", "session_end"]


# --- session file location + absent binary ----------------------------------------


def test_locate_session_file(adapter: OCRAdapter, tmp_path: Path) -> None:
    home = tmp_path / "jobhome"
    sessions = home / ".opencodereview" / "sessions" / "encoded-repo"
    sessions.mkdir(parents=True)
    older = sessions / "s1.jsonl"
    older.write_text("{}\n", encoding="utf-8")
    newer = sessions / "s2.jsonl"
    newer.write_text("{}\n{}\n", encoding="utf-8")
    import os

    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    assert adapter.locate_session_file(home) == newer
    assert adapter.locate_session_file(tmp_path / "empty-home") is None


async def test_detect_graceful_when_binary_absent(adapter: OCRAdapter) -> None:
    if shutil.which("ocr"):
        pytest.skip("ocr is installed on this machine")
    status = await adapter.detect(force=True)
    assert status.status == "ocr_not_found"
    assert status.binary_path is None
    # Downstream entry points degrade instead of raising.
    result = await adapter.test_llm(Path(adapter._settings.data_dir) / "jh", PROVIDER)
    assert result.status == "ocr_not_found" and not result.ok


@pytest.mark.skipif(shutil.which("ocr") is None, reason="ocr binary not installed")
async def test_detect_real_binary(adapter: OCRAdapter) -> None:
    status = await adapter.detect(force=True)
    assert status.status == "ok"
    assert status.version is not None
    assert status.capabilities.json_output
