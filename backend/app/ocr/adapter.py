"""OCR compatibility layer (SPEC §35, §38 rules 1-4).

Single point of contact with the ``ocr`` binary. Detects the executable,
probes ``ocr version`` / ``ocr review --help`` / ``ocr --help`` to build a
capabilities object, generates argv arrays, builds isolated per-job
environments and configs, and parses results and session JSONL.

When the binary is absent, every entry point degrades to a structured
``"ocr_not_found"`` status — never an exception escaping into callers.

Grounding: verified against the upstream ocr Go source.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path, PureWindowsPath
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger, redact_text, redactor
from app.core.security import normalize_path
from app.services.ocr_mcp import ocr_user_config_path
from app.ocr.models import (
    LLMTestResult,
    NormalizedFinding,
    NormalizedWarning,
    OCRCapabilities,
    OCRStatus,
    ParsedResult,
    PreviewFile,
    PreviewResult,
    ProviderResolution,
    ResultSummary,
    ReviewJobContext,
    SessionEvent,
)

logger = get_logger(__name__)

IS_WINDOWS = os.name == "nt"

_NPM_CMD_SCRIPT_RE = re.compile(
    r'"%dp0%\\(?P<script>node_modules\\[^"\r\n]+?\.js)"\s+%\*',
    re.IGNORECASE,
)

#: Env overrides the current upstream resolver honors (resolver.go).
KNOWN_ENV_OVERRIDES: tuple[str, ...] = (
    "OCR_LLM_URL",
    "OCR_LLM_TOKEN",
    "OCR_LLM_MODEL",
    "OCR_LLM_PROTOCOL",
    "OCR_LLM_TIMEOUT",
    "OCR_LLM_AUTH_HEADER",
    "OCR_LLM_EXTRA_HEADERS",
    "OCR_USE_ANTHROPIC",
)

#: review --help flag name -> capability field.
_FLAG_CAPABILITY_MAP: dict[str, str] = {
    "format": "json_output",  # refined below by checking the "json" value
    "audience": "agent_audience",
    "resume": "resume",
    "background": "background",
    "background-file": "background_file",
    "exclude": "exclude_flag",
    "preview": "preview",
    "model": "model_override",
    "rule": "rule_flag",
    "tools": "tools_flag",
    "concurrency": "concurrency_flag",
    "timeout": "timeout_flag",
    "max-tools": "max_tools_flag",
    "max-git-procs": "max_git_procs_flag",
    "plan-mode": "plan_mode",
    "plan-threshold": "plan_threshold",
    "max-tokens": "max_tokens",
    "template": "template_override",
}

_SUBCOMMAND_CAPABILITY_MAP: dict[str, str] = {
    "llm": "llm_test",  # refined by checking for the "test" subcommand
    "scan": "scan",
    "rules": "rules_check",
    "viewer": "viewer",
    "config": "config_set",
}

_FLAG_RE = re.compile(r"--([a-z][a-z0-9-]+)")
_VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PREVIEW_TOTAL_RE = re.compile(
    r"^\s*Preview:\s*(\d+)\s+file\(s\)\s+changed\b", re.IGNORECASE
)
_PREVIEW_REVIEWABLE_RE = re.compile(
    r"^\s*Will review\s*\((\d+)\):\s*$", re.IGNORECASE
)
_PREVIEW_SECTION_RE = re.compile(r"^\s*[^:]+\(\d+\):\s*$")
_PREVIEW_FILE_RE = re.compile(r"^\s*\[[^\]]+\]\s+(.+?)\s*$")


class UnsupportedFeatureError(RuntimeError):
    """Raised when a job context requests a flag the binary lacks."""

    def __init__(self, feature: str, detail: str):
        super().__init__(detail)
        self.feature = feature


class ResultParseError(RuntimeError):
    pass


class OCRAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._binary: str | None = None
        self._status: OCRStatus | None = None

    # ------------------------------------------------------------------
    # binary detection + capability probing
    # ------------------------------------------------------------------

    def find_binary(self) -> str | None:
        """Custom configured path first, then PATH lookup."""

        if self._binary:
            return self._binary
        custom = self._settings.ocr_executable
        if custom:
            candidate = Path(str(custom)).expanduser()
            if candidate.is_file():
                self._binary = str(candidate)
                return self._binary
        for name in ("ocr", "ocr.exe"):
            found = shutil.which(name)
            if found:
                self._binary = found
                return found
        return None

    @staticmethod
    def parse_capabilities(
        review_help: str, root_help: str
    ) -> OCRCapabilities:
        """Pure function: build capabilities from help text (unit-testable).

        Upstream's ``printReviewUsage`` is known to be incomplete (e.g. it
        omits ``--exclude`` although the flag exists), so detection starts
        from the stock-default capability set and can only *upgrade* values
        to True. Planning-patch flags default to False and only become True
        when actually observed in the help output.
        """

        flags = set(_FLAG_RE.findall(review_help))
        defaults = OCRAdapter._default_capabilities()
        kwargs: dict[str, bool] = {}
        for flag, field_name in _FLAG_CAPABILITY_MAP.items():
            kwargs[field_name] = getattr(defaults, field_name) or (flag in flags)
        # "json" must be an accepted --format value, not just the flag.
        if "format" in flags:
            kwargs["json_output"] = bool(
                re.search(r"format[^\n]*\bjson\b", review_help, re.IGNORECASE)
            )
        if "audience" in flags:
            kwargs["agent_audience"] = bool(
                re.search(r"audience[^\n]*\bagent\b", review_help, re.IGNORECASE)
            )
        root_lower = root_help.lower()
        for sub, field_name in _SUBCOMMAND_CAPABILITY_MAP.items():
            kwargs[field_name] = getattr(defaults, field_name) or (
                re.search(rf"^\s*{sub}\s", root_lower, re.MULTILINE) is not None
            )
        kwargs["llm_providers"] = getattr(defaults, "llm_providers") or (
            "llm" in root_lower and "providers" in root_lower
        )
        return OCRCapabilities(**kwargs)

    @staticmethod
    def parse_version(output: str) -> str | None:
        match = _VERSION_RE.search(output)
        return match.group(0) if match else None

    def exec_argv(self, argv: list[str]) -> list[str]:
        """Wrap an argv array whose program is the OCR binary.

        Script-based custom executables (``.py``/``.js``) cannot be exec'd
        directly on Windows, so they are launched through their interpreter.
        Everything stays an argv array — never a shell string.
        """

        import sys

        if not argv:
            return argv
        program = argv[0]
        lower = program.lower()
        if lower.endswith(".py"):
            return [sys.executable, program, *argv[1:]]
        if lower.endswith(".js"):
            node = shutil.which("node")
            if node:
                return [node, program, *argv[1:]]
        if IS_WINDOWS and lower.endswith((".cmd", ".bat")):
            npm_argv = self._windows_npm_shim_argv(program)
            if npm_argv:
                return [*npm_argv, *argv[1:]]
        return argv

    @staticmethod
    def _windows_npm_shim_argv(program: str) -> list[str] | None:
        """Resolve a standard npm ``.cmd`` shim to its long-lived Node process.

        A batch launch reports the ``cmd.exe`` wrapper PID rather than the OCR
        runtime. Normalise the recognised npm shim so liveness, diagnostics,
        and cancellation track the Node process directly; otherwise preserve
        the original command.
        """

        shim = Path(program)
        try:
            content = shim.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        match = _NPM_CMD_SCRIPT_RE.search(content)
        if match is None:
            return None

        relative = Path(*PureWindowsPath(match.group("script")).parts)
        script = shim.parent / relative
        if not script.is_file():
            return None

        bundled_node = shim.parent / "node.exe"
        node = str(bundled_node) if bundled_node.is_file() else shutil.which("node")
        if not node:
            return None
        return [node, str(script)]

    async def _run_probe(self, args: list[str]) -> tuple[int, str, str]:
        binary = self._binary
        assert binary is not None
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.exec_argv([binary, *args]),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._base_env(),
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=self._settings.ocr_probe_timeout_seconds
            )
            return (
                proc.returncode or 0,
                stdout_b.decode("utf-8", errors="replace"),
                stderr_b.decode("utf-8", errors="replace"),
            )
        except (OSError, TimeoutError) as exc:
            return (-1, "", f"{type(exc).__name__}: {exc}")

    async def detect(self, *, force: bool = False) -> OCRStatus:
        """Detect binary, version, and capabilities. Cached per adapter.

        Never raises; absence of the binary yields ``ocr_not_found``.
        """

        if self._status is not None and not force:
            return self._status

        binary = self.find_binary()
        if binary is None:
            self._status = OCRStatus(
                status="ocr_not_found",
                message=(
                    "OpenCodeReview CLI (ocr) was not found on PATH. Install it "
                    "(npm i -g @alibaba-group/open-code-review) or configure a "
                    "custom executable path in Settings."
                ),
            )
            return self._status

        rc_v, out_v, err_v = await self._run_probe(["version"])
        if rc_v != 0 and not out_v:
            self._status = OCRStatus(
                status="probe_failed",
                binary_path=binary,
                message=redact_text((err_v or out_v).strip()[:300])
                or "ocr version probe failed",
            )
            return self._status

        version = self.parse_version(out_v or err_v)
        _, review_help, review_help_err = await self._run_probe(["review", "--help"])
        _, root_help, root_help_err = await self._run_probe(["--help"])
        capabilities = self.parse_capabilities(
            review_help or review_help_err, root_help or root_help_err
        )
        self._status = OCRStatus(
            status="ok",
            binary_path=binary,
            version=version,
            capabilities=capabilities,
            honored_env_overrides=list(KNOWN_ENV_OVERRIDES),
        )
        logger.info(
            "ocr_detected",
            binary=binary,
            version=version,
            plan_mode=capabilities.plan_mode,
        )
        return self._status

    async def capabilities(self) -> OCRCapabilities:
        return (await self.detect()).capabilities

    # ------------------------------------------------------------------
    # command generation
    # ------------------------------------------------------------------

    def _require(self, caps: OCRCapabilities, ok: bool, feature: str, detail: str) -> None:
        if not ok:
            raise UnsupportedFeatureError(feature, detail)

    def build_review_command(
        self, ctx: ReviewJobContext, caps: OCRCapabilities | None = None
    ) -> list[str]:
        """Build the OCR argv array for any supported review mode.

        ``--format json --audience human`` are always forced. JSON keeps the
        terminal result machine-readable, while the human audience preserves
        OCR's progress lines for the live log. When ``caps`` is omitted,
        cached capabilities are used if available, else standard upstream
        flags are assumed and planning-patch flags are reported unsupported.
        """

        if caps is None:
            caps = (
                self._status.capabilities
                if self._status and self._status.status == "ok"
                else self._default_capabilities()
            )
        binary = self.find_binary() or "ocr"

        is_scan = ctx.mode == "scan"
        if is_scan:
            self._require(
                caps, caps.scan, "scan",
                "installed OCR does not support full-file scans",
            )
        argv: list[str] = [
            binary,
            "scan" if is_scan else "review",
            "--repo",
            ctx.repo_path,
        ]

        if ctx.mode in ("range", "pr"):
            # PR jobs review PR-head vs PR-base: identical argv to a range
            # review over the SHAs captured immutably at queue time.
            base = ctx.base_sha or ctx.base_ref
            target = ctx.target_sha or ctx.target_ref
            if not base or not target:
                raise ValueError("range mode requires base and target refs/SHAs")
            argv += ["--from", base, "--to", target]
        elif ctx.mode == "commit":
            commit = ctx.commit_sha or ctx.commit_ref
            if not commit:
                raise ValueError("commit mode requires a commit ref/SHA")
            argv += ["--commit", commit]
        elif ctx.mode in ("workspace", "scan"):
            pass  # Both commands need no ref-selection flags.
        else:  # pragma: no cover - pydantic constrains this
            raise ValueError(f"unknown mode: {ctx.mode}")

        if ctx.resume_session_id:
            if is_scan:
                raise UnsupportedFeatureError(
                    "resume", "OCR scan jobs do not support session continuation"
                )
            self._require(
                caps,
                caps.resume,
                "resume",
                "installed OCR does not support --resume session continuation",
            )
            argv += ["--resume", ctx.resume_session_id]
        if ctx.concurrency:
            argv += ["--concurrency", str(ctx.concurrency)]
        if ctx.per_file_timeout_minutes:
            argv += ["--timeout", str(ctx.per_file_timeout_minutes)]
        if ctx.max_tools:
            argv += ["--max-tools", str(ctx.max_tools)]
        if ctx.max_git_processes:
            argv += ["--max-git-procs", str(ctx.max_git_processes)]
        if ctx.rule_file_path:
            argv += ["--rule", ctx.rule_file_path]
        if ctx.tools_file_path:
            argv += ["--tools", ctx.tools_file_path]
        if ctx.model:
            self._require(
                caps, caps.model_override, "model_override",
                "installed OCR does not support --model overrides",
            )
            argv += ["--model", ctx.model]
        if ctx.background:
            argv += ["--background", ctx.background]
        if ctx.background_file:
            if is_scan:
                raise UnsupportedFeatureError(
                    "background_file", "OCR scan does not support --background-file"
                )
            self._require(
                caps, caps.background_file, "background_file",
                "installed OCR does not support --background-file",
            )
            argv += ["--background-file", ctx.background_file]
        if ctx.exclude_patterns:
            self._require(
                caps, caps.exclude_flag, "exclude_flag",
                "installed OCR does not support --exclude",
            )
            # Grounded: --exclude is a single comma-separated list.
            argv += ["--exclude", ",".join(ctx.exclude_patterns)]

        # Planning-control patch set (Stage 4). Only emitted when the binary
        # reports support; otherwise the job context must stay at defaults.
        if is_scan and ctx.plan_mode == "never":
            argv += ["--no-plan"]
        elif not is_scan and ctx.plan_mode != "auto":
            self._require(
                caps, caps.plan_mode, "plan_mode",
                "installed OCR does not support --plan-mode (planning patch not applied)",
            )
            argv += ["--plan-mode", ctx.plan_mode]
        if ctx.plan_threshold_lines is not None:
            if is_scan:
                raise UnsupportedFeatureError(
                    "plan_threshold",
                    "OCR scan plans whole files and does not support --plan-threshold",
                )
            self._require(
                caps, caps.plan_threshold, "plan_threshold",
                "installed OCR does not support --plan-threshold",
            )
            argv += ["--plan-threshold", str(ctx.plan_threshold_lines)]
        if ctx.max_tokens is not None:
            if is_scan:
                argv += ["--max-tokens-budget", str(ctx.max_tokens)]
            else:
                self._require(
                    caps, caps.max_tokens, "max_tokens",
                    "installed OCR does not support --max-tokens",
                )
                argv += ["--max-tokens", str(ctx.max_tokens)]
        if ctx.template_path:
            if is_scan:
                raise UnsupportedFeatureError(
                    "template_override", "OCR scan does not support --template"
                )
            self._require(
                caps, caps.template_override, "template_override",
                "installed OCR does not support --template",
            )
            argv += ["--template", ctx.template_path]

        # Expert escape hatch — pre-validated by core.security.
        argv += ctx.additional_arguments

        # Forced runner-owned flags come last so they always win.
        argv += ["--format", "json", "--audience", "human"]
        return argv

    def build_preview_command(
        self, ctx: ReviewJobContext, caps: OCRCapabilities | None = None
    ) -> list[str]:
        """Like :meth:`build_review_command` but adds ``--preview`` (no LLM)."""

        if caps is None:
            caps = (
                self._status.capabilities
                if self._status and self._status.status == "ok"
                else self._default_capabilities()
            )
        self._require(
            caps, caps.preview, "preview",
            "installed OCR does not support --preview",
        )
        argv = self.build_review_command(ctx, caps)
        # Insert --preview before the forced trailing flags.
        return argv[:-4] + ["--preview"] + argv[-4:]

    @staticmethod
    def _default_capabilities() -> OCRCapabilities:
        """Assumed capabilities of a stock upstream binary (used for command
        previews when no binary has been probed yet)."""

        return OCRCapabilities(
            json_output=True,
            agent_audience=True,
            resume=True,
            background=True,
            background_file=True,
            exclude_flag=True,
            preview=True,
            model_override=True,
            rule_flag=True,
            tools_flag=True,
            concurrency_flag=True,
            timeout_flag=True,
            max_tools_flag=True,
            max_git_procs_flag=True,
            # planning patch flags stay False — the patch is not upstream.
            plan_mode=False,
            plan_threshold=False,
            max_tokens=False,
            template_override=False,
            llm_test=True,
            llm_providers=True,
            scan=True,
            rules_check=True,
            viewer=True,
            config_set=True,
        )

    # ------------------------------------------------------------------
    # per-job environment + config (SPEC §10)
    # ------------------------------------------------------------------

    def _base_env(self) -> dict[str, str]:
        """Copy of the process environment without inherited OCR_LLM_* keys."""

        env = dict(os.environ)
        for key in list(env):
            if key.startswith("OCR_LLM_") or key in {
                "OCR_USE_ANTHROPIC",
                "OCR_CONFIG_PATH",
            }:
                env.pop(key)
        # Custom Python OCR executables and Python helpers must flush progress
        # while stdout/stderr are connected to runner pipes.
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def build_job_environment(
        self,
        job_home: str | Path,
        provider: ProviderResolution,
    ) -> dict[str, str]:
        """Per-job isolated environment (SPEC §10).

        Sets HOME + USERPROFILE to the job home and maps resolved provider
        settings onto OCR_LLM_* variables. Secrets are registered with the
        log redactor and never written to logs; callers must use
        ``core.security.redact_environment`` before displaying the result.
        """

        home = str(normalize_path(job_home))
        env = self._base_env()
        env["HOME"] = home
        env["USERPROFILE"] = home  # Windows

        if provider.base_url:
            env["OCR_LLM_URL"] = provider.base_url
        # Resolve OCR_LLM_TOKEN from credential or auth_header.
        # The OCR binary requires URL/TOKEN/MODEL as a group; if any are
        # set all three must be present. auth_header may contain a bearer
        # token that the binary can use when no credential is stored.
        token = provider.token
        if not token and provider.auth_header:
            hdr = provider.auth_header.strip()
            if hdr.lower().startswith("bearer "):
                token = hdr[7:]  # Extract token from "Bearer <token>"
            elif hdr.lower().startswith("token "):
                token = hdr[6:]
        if token:
            env["OCR_LLM_TOKEN"] = token
            redactor.register(token)
        if provider.model:
            env["OCR_LLM_MODEL"] = provider.model
        if provider.protocol:
            env["OCR_LLM_PROTOCOL"] = provider.protocol
            # Legacy fallback for older binaries (resolver: protocol wins).
            env["OCR_USE_ANTHROPIC"] = (
                "true" if provider.protocol == "anthropic" else "false"
            )
        if provider.http_timeout_seconds:
            env["OCR_LLM_TIMEOUT"] = str(provider.http_timeout_seconds)
        if provider.auth_header:
            env["OCR_LLM_AUTH_HEADER"] = provider.auth_header
        if provider.extra_headers:
            # Grounded format: K=V,K=V (NOT JSON).
            env["OCR_LLM_EXTRA_HEADERS"] = ",".join(
                f"{k}={v}" for k, v in provider.extra_headers.items()
            )
            for value in provider.extra_headers.values():
                redactor.register(value)
        return env

    def write_job_config(
        self,
        job_home: str | Path,
        provider: ProviderResolution,
        *,
        language: str | None = None,
    ) -> Path:
        """Write ``<job_home>/.opencodereview/config.json`` (SPEC §10).

        Only settings not expressible (or not secret-safe) via env vars go
        here. The auth token and extra headers are NEVER written to disk —
        they travel via the process environment only.

        When the provider has no resolved token (tokenless/keyless provider),
        fall back to copying the user's global ``~/.opencodereview/config.json``
        so the OCR binary can find the provider credentials it already knows
        about. This is essential for providers that were configured via the
        OCR CLI rather than this app's SecretStore.
        """

        home = normalize_path(job_home)
        ocr_dir = home / ".opencodereview"
        (ocr_dir / "sessions").mkdir(parents=True, exist_ok=True)

        llm: dict[str, Any] = {}
        if provider.model:
            llm["model"] = provider.model
        if provider.protocol:
            llm["protocol"] = provider.protocol
        if provider.base_url:
            llm["url"] = provider.base_url
        if provider.http_timeout_seconds:
            llm["timeout_sec"] = provider.http_timeout_seconds
        # NOTE: auth_header is intentionally NOT written to the config file.
        # The OCR binary does not recognize ``auth_header`` in the llm block —
        # it expects ``api_key``. A partial llm block without api_key causes
        # the binary to reject the config and ignore env vars entirely.
        # The token travels via OCR_LLM_TOKEN env var instead.
        if provider.extra_body:
            llm["extra_body"] = provider.extra_body

        config: dict[str, Any] = {
            "llm": llm,
            # Local-first privacy default: no telemetry from managed jobs.
            "telemetry": {"enabled": False},
        }
        effective_language = language or provider.language
        if effective_language:
            config["language"] = effective_language

        # Tokenless provider fallback: if we don't have a token to pass via
        # env vars, copy the user's global OCR config so the binary can find
        # provider credentials (e.g. custom_providers with api_key) that were
        # configured via the OCR CLI rather than this app's SecretStore.
        global_config = ocr_user_config_path()
        if not provider.token:
            if global_config.is_file():
                try:
                    global_data = json.loads(
                        global_config.read_text(encoding="utf-8")
                    )
                    # Merge: keep our non-secret settings, but pull in the
                    # provider credentials (custom_providers, providers, etc.)
                    # Provider definitions can supply credentials, but the
                    # global active-provider selector must never leak into a
                    # managed job. The selected review profile's llm block is
                    # authoritative for this invocation.
                    for key in ("providers", "custom_providers"):
                        if key in global_data:
                            config[key] = global_data[key]
                    _inherit_mcp_servers(config, global_data)
                    # If the global config has an llm block with credentials,
                    # use it as the base and let our overrides win.
                    global_llm = global_data.get("llm")
                    if isinstance(global_llm, dict) and global_llm:
                        merged_llm = {**global_llm, **llm}
                        config["llm"] = merged_llm
                except (OSError, json.JSONDecodeError):
                    pass
        else:
            # Even with a token, the OCR binary may not recognize
            # ``auth_header`` in the config's llm block — it needs
            # ``api_key`` or ``custom_providers``. Always merge the global
            # custom_providers so the binary can resolve the provider.
            if global_config.is_file():
                try:
                    global_data = json.loads(
                        global_config.read_text(encoding="utf-8")
                    )
                    # Do not copy the global active-provider selector: it can
                    # override the profile's model and endpoint at OCR config
                    # resolution time.
                    for key in ("providers", "custom_providers"):
                        if key in global_data:
                            config[key] = global_data[key]
                    _inherit_mcp_servers(config, global_data)
                except (OSError, json.JSONDecodeError):
                    pass

        config_path = ocr_dir / "config.json"
        config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return config_path

    # ------------------------------------------------------------------
    # result parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_result_json(path: str | Path) -> ParsedResult:
        """Parse ``result.json`` (``ocr review --format json`` output).

        Findings are read from the upstream ``comments`` key (a ``findings``
        alias is tolerated). Severity/category are passed through only when
        present — never invented.
        """

        result_path = Path(path)
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ResultParseError(f"result file not found: {result_path}") from exc
        except json.JSONDecodeError as exc:
            raise ResultParseError(
                f"result file is not valid JSON: {result_path} ({exc})"
            ) from exc
        if not isinstance(data, dict):
            raise ResultParseError(f"result JSON root must be an object: {result_path}")

        raw_findings = data.get("comments") or data.get("findings") or []
        findings: list[NormalizedFinding] = []
        for item in raw_findings:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            findings.append(
                NormalizedFinding(
                    path=str(item["path"]),
                    content=str(item.get("content", "")),
                    start_line=_opt_int(item.get("start_line")),
                    end_line=_opt_int(item.get("end_line")),
                    existing_code=_opt_str(item.get("existing_code")),
                    suggestion_code=_opt_str(item.get("suggestion_code")),
                    thinking=_opt_str(item.get("thinking")),
                    category=_opt_str(item.get("category")),
                    severity=_opt_str(item.get("severity")),
                )
            )

        warnings: list[NormalizedWarning] = []
        for item in data.get("warnings") or []:
            if isinstance(item, dict):
                warnings.append(
                    NormalizedWarning(
                        file=_opt_str(item.get("file")),
                        message=str(item.get("message", "")),
                        type=_opt_str(item.get("type")),
                    )
                )
            elif isinstance(item, str):
                warnings.append(NormalizedWarning(message=item))

        raw_summary = data.get("summary") or {}
        summary = ResultSummary(
            files_reviewed=_opt_int(raw_summary.get("files_reviewed")),
            comments=_opt_int(raw_summary.get("comments")),
            input_tokens=_opt_int(raw_summary.get("input_tokens")),
            output_tokens=_opt_int(raw_summary.get("output_tokens")),
            cache_read_tokens=_opt_int(raw_summary.get("cache_read_tokens")),
            cache_write_tokens=_opt_int(raw_summary.get("cache_write_tokens")),
            total_tokens=_opt_int(raw_summary.get("total_tokens")),
            elapsed=_opt_str(raw_summary.get("elapsed")),
        )

        raw_tools = data.get("tool_calls") or {}
        tool_calls = {
            str(k): int(v)
            for k, v in (raw_tools.get("by_tool") or {}).items()
            if isinstance(v, (int, float))
        }

        return ParsedResult(
            status=str(data.get("status", "unknown")),
            message=_opt_str(data.get("message")),
            trace_id=_opt_str(data.get("trace_id")),
            session_id=_opt_str(data.get("session_id")),
            findings=findings,
            warnings=warnings,
            summary=summary,
            tool_calls=tool_calls,
            project_summary=_opt_str(data.get("project_summary")),
            resume=data.get("resume") if isinstance(data.get("resume"), dict) else None,
        )

    # ------------------------------------------------------------------
    # session JSONL incremental parsing (SPEC §14)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_session_jsonl(
        path: str | Path, *, offset: int = 0, keep_raw: bool = True
    ) -> tuple[list[SessionEvent], int]:
        """Incrementally parse an append-only session JSONL file.

        Returns ``(events, new_offset)``. A trailing partial line is left
        unconsumed so the next call (with ``offset=new_offset``) re-reads it
        once complete. Unparseable lines are skipped silently.
        """

        session_path = Path(path)
        events: list[SessionEvent] = []
        try:
            with session_path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
        except FileNotFoundError:
            return [], offset

        last_newline = chunk.rfind(b"\n")
        if last_newline == -1:
            return [], offset  # no complete line yet
        complete = chunk[: last_newline + 1]
        new_offset = offset + len(complete)

        seq_base = 0  # caller aggregates by combining with prior counts
        for raw_line in complete.split(b"\n"):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            events.append(_normalize_session_record(record, seq_base, keep_raw))
            seq_base += 1
        return events, new_offset

    @staticmethod
    def locate_session_file(job_home: str | Path) -> Path | None:
        """Find the job's session JSONL under the isolated home (newest wins)."""

        sessions_dir = normalize_path(job_home) / ".opencodereview" / "sessions"
        if not sessions_dir.is_dir():
            return None
        candidates = sorted(
            sessions_dir.rglob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    # ------------------------------------------------------------------
    # llm test + preview execution
    # ------------------------------------------------------------------

    async def _run_process(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float,
    ) -> tuple[int, str, str, float]:
        """Generic argv-array runner with timeout; elapsed in ms."""

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd) if cwd else None,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return (-1, "", f"{type(exc).__name__}: {exc}", 0.0)
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = (time.monotonic() - start) * 1000
            return (-1, "", f"process timed out after {timeout:.0f}s", elapsed)
        elapsed = (time.monotonic() - start) * 1000
        return (
            proc.returncode or 0,
            stdout_b.decode("utf-8", errors="replace"),
            stderr_b.decode("utf-8", errors="replace"),
            elapsed,
        )

    async def test_llm(
        self,
        job_home: str | Path,
        provider: ProviderResolution,
        *,
        timeout: float = 120.0,
    ) -> LLMTestResult:
        """Run ``ocr llm test`` under an isolated config (SPEC §9).

        Never raises; a missing binary yields status ``ocr_not_found``.
        Output is redacted before being returned.
        """

        status = await self.detect()
        if status.status != "ok" or not status.binary_path:
            return LLMTestResult(
                ok=False,
                status="ocr_not_found",
                message=status.message or "ocr binary not found",
            )
        home = normalize_path(job_home)
        self.write_job_config(home, provider)
        env = self.build_job_environment(home, provider)
        rc, stdout, stderr, elapsed = await self._run_process(
            self.exec_argv([status.binary_path, "llm", "test"]),
            env=env,
            cwd=home,
            timeout=timeout,
        )
        return LLMTestResult(
            ok=rc == 0,
            status="ok" if rc == 0 else "failed",
            exit_code=rc,
            elapsed_ms=elapsed,
            stdout=redact_text(stdout)[-4000:],
            stderr=redact_text(stderr)[-4000:],
            message=None if rc == 0 else "ocr llm test failed",
        )

    async def run_preview(
        self,
        ctx: ReviewJobContext,
        *,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> PreviewResult:
        """Execute ``ocr review --preview --format json`` and parse the file list."""

        status = await self.detect()
        if status.status != "ok" or not status.binary_path:
            return PreviewResult(ok=False, message=status.message or "ocr not found")
        try:
            argv = self.build_preview_command(ctx, status.capabilities)
        except UnsupportedFeatureError as exc:
            return PreviewResult(ok=False, message=str(exc))
        rc, stdout, stderr, _elapsed = await self._run_process(
            self.exec_argv(argv), env=env or self._base_env(), timeout=timeout
        )
        if rc != 0:
            return PreviewResult(
                ok=False,
                raw_text=redact_text(stdout)[-2000:],
                message=redact_text(stderr).strip()[:500] or "preview failed",
            )
        return self.parse_preview_output(stdout)

    @staticmethod
    def parse_preview_output(stdout: str) -> PreviewResult:
        """Parse JSON previews and the human text emitted by OCR 1.8.

        OCR 1.8 accepts ``--format json`` for preview commands but still emits
        an ANSI-formatted file inventory. Supporting both shapes keeps the live
        progress denominator accurate across OCR versions.
        """

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            clean = _ANSI_ESCAPE_RE.sub("", stdout).replace("\r\n", "\n")
            lines = clean.splitlines()
            total_files: int | None = None
            reviewable_count: int | None = None
            reviewable_files: list[PreviewFile] = []
            in_reviewable_section = False

            for line in lines:
                total_match = _PREVIEW_TOTAL_RE.match(line)
                if total_match:
                    total_files = int(total_match.group(1))
                    continue

                reviewable_match = _PREVIEW_REVIEWABLE_RE.match(line)
                if reviewable_match:
                    reviewable_count = int(reviewable_match.group(1))
                    in_reviewable_section = True
                    continue

                if in_reviewable_section and _PREVIEW_SECTION_RE.match(line):
                    in_reviewable_section = False
                    continue
                if not in_reviewable_section:
                    continue

                file_match = _PREVIEW_FILE_RE.match(line)
                if not file_match:
                    continue
                # Human preview columns use two or more spaces before stats.
                path = re.split(
                    r"\s{2,}(?=[+-]\d)", file_match.group(1), maxsplit=1
                )[0]
                if path:
                    reviewable_files.append(PreviewFile(path=path))

            if reviewable_count is None:
                return PreviewResult(
                    ok=False,
                    raw_text=redact_text(stdout)[-2000:],
                    message="preview output was not recognized",
                )
            return PreviewResult(
                ok=True,
                files=reviewable_files,
                total_files=total_files,
                reviewable_count=reviewable_count,
                excluded_count=(
                    max(total_files - reviewable_count, 0)
                    if total_files is not None
                    else None
                ),
                raw_text=redact_text(clean).strip()[-64_000:] or None,
            )

        files = [
            PreviewFile(
                path=str(item.get("path", "")),
                status=_opt_str(item.get("status")),
                insertions=_opt_int(item.get("insertions")),
                deletions=_opt_int(item.get("deletions")),
                will_review=bool(item.get("will_review", True)),
                exclude_reason=_opt_str(item.get("exclude_reason")) or None,
            )
            for item in data.get("files", [])
            if isinstance(item, dict)
        ]
        return PreviewResult(
            ok=True,
            files=files,
            total_files=_opt_int(data.get("total_files")),
            reviewable_count=_opt_int(data.get("reviewable_count")),
            excluded_count=_opt_int(data.get("excluded_count")),
            total_insertions=_opt_int(data.get("total_insertions")),
            total_deletions=_opt_int(data.get("total_deletions")),
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _inherit_mcp_servers(
    job_config: dict[str, Any], global_data: dict[str, Any]
) -> None:
    """Copy the user's ``mcp_servers`` into a managed job's config.

    Managed jobs run with an isolated HOME, so without this step the OCR
    binary would never see the MCP servers configured through the CLI or the
    manager's MCP-servers management surface. Header/env secret values are
    registered with the log redactor before use.
    """

    servers = global_data.get("mcp_servers")
    if not isinstance(servers, dict) or not servers:
        return
    job_config["mcp_servers"] = servers
    for server in servers.values():
        if not isinstance(server, dict):
            continue
        headers = server.get("headers")
        if isinstance(headers, dict):
            for value in headers.values():
                redactor.register(str(value))
        env_entries = server.get("env")
        if isinstance(env_entries, list):
            for entry in env_entries:
                redactor.register(str(entry).partition("=")[2])


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_session_record(
    record: dict[str, Any], seq: int, keep_raw: bool
) -> SessionEvent:
    timestamp = None
    raw_ts = record.get("timestamp")
    if isinstance(raw_ts, str):
        try:
            from datetime import datetime

            timestamp = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except ValueError:
            timestamp = None

    usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}

    duration_ms = _opt_int(record.get("duration_ms"))
    if duration_ms is None:
        duration_s = record.get("duration_seconds")
        if isinstance(duration_s, (int, float)):
            duration_ms = int(duration_s * 1000)
    if duration_ms is None:
        duration_ns = record.get("duration_ns")
        if isinstance(duration_ns, (int, float)):
            duration_ms = int(duration_ns / 1_000_000)

    comments = record.get("comments")
    comments_count = len(comments) if isinstance(comments, list) else _opt_int(comments)

    return SessionEvent(
        seq=seq,
        record_type=str(record.get("type", "unknown")),
        timestamp=timestamp,
        session_id=_opt_str(record.get("sessionId") or record.get("session_id")),
        file_path=_opt_str(record.get("filePath") or record.get("file_path")),
        task_type=_opt_str(record.get("taskType") or record.get("task_type")),
        request_no=_opt_int(record.get("requestNo") or record.get("request_no")),
        tool_name=_opt_str(record.get("tool") or record.get("tool_name")),
        error=_opt_str(record.get("error")),
        prompt_tokens=_opt_int(usage.get("prompt_tokens")),
        completion_tokens=_opt_int(usage.get("completion_tokens")),
        cache_read_tokens=_opt_int(usage.get("cache_read_tokens")),
        cache_write_tokens=_opt_int(usage.get("cache_write_tokens")),
        duration_ms=duration_ms,
        comments_count=comments_count,
        raw=record if keep_raw else None,
    )
