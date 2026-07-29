"""FastAPI application factory + lifespan (SPEC §3, §19, §27).

One process runs everything: migrations, startup recovery, queue worker,
webhook worker, SSE bus, REST API, MCP server, and the built frontend.
"""

from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

# Some Windows machines have a broken registry mapping that makes Python's
# mimetypes report ".js" as text/plain. Browsers then refuse to execute the
# module script (strict MIME checking) and the SPA renders a blank page.
# Force-correct the web-critical types process-wide before StaticFiles is used.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/x-icon", ".ico")
mimetypes.add_type("font/woff2", ".woff2")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.errors import install_error_handlers
from app.api.security import CSRFMiddleware
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.instance_lock import DataDirectoryLock
from app.core.logging import configure_logging, get_logger
from app.core.secrets import get_secret_store
from app.db.migrate import run_migrations_async
from app.db.session import dispose_engine, init_engine
from app.mcp.server import build_mcp_server
from app.queue.recovery import run_startup_recovery
from app.queue.worker import QueueWorker, set_current_worker
from app.services.deps import get_git_service, get_ocr_adapter
from app.webhooks.service import WebhookService
from app.webhooks.worker import WebhookWorker, set_current_webhook_worker

logger = get_logger(__name__)

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        settings.log_level,
        log_file=settings.log_file,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    mcp_server = build_mcp_server()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        instance_lock = DataDirectoryLock(settings.resolved_data_dir)
        instance_lock.acquire()
        try:
            init_engine(settings.resolved_database_url)
            await run_migrations_async(settings.resolved_database_url)

            # Seed the built-in Default profile (SPEC §8). Idempotent: adopts an
            # existing "Default" if present, otherwise creates one. Must run after
            # migrations so the ``is_system`` column exists.
            from app.db.session import session_scope
            from app.services.profiles import ProfileService

            async with session_scope() as session:
                default = await ProfileService(session).ensure_default()
            logger.info("default_profile_ensured", id=default.id, name=default.name)

            git = get_git_service()
            adapter = get_ocr_adapter()
            secrets = get_secret_store()

            async def webhook_dispatcher(session, job, event_type):
                await WebhookService(session, settings=settings).dispatch_event(
                    session, job, event_type
                )

            queue_worker = QueueWorker(
                settings, git, adapter, secrets, webhook_dispatcher=webhook_dispatcher
            )
            webhook_worker = WebhookWorker(settings)
            app.state.queue_worker = queue_worker
            app.state.webhook_worker = webhook_worker
            set_current_worker(queue_worker)
            set_current_webhook_worker(webhook_worker)

            recovery = await run_startup_recovery(settings, git)
            if recovery["interrupted_jobs"] or recovery["worktrees_removed"]:
                logger.info("startup_recovery_completed", **recovery)

            await queue_worker.start()
            await webhook_worker.start()
            logger.info(
                "backend_started",
                host=settings.host,
                port=settings.port,
                data_dir=str(settings.resolved_data_dir),
            )
        except BaseException:
            instance_lock.release()
            raise

        try:
            async with mcp_server.session_manager.run():
                yield
        finally:
            try:
                await queue_worker.stop()
                await webhook_worker.stop()
            finally:
                set_current_worker(None)
                set_current_webhook_worker(None)
                try:
                    await dispose_engine()
                finally:
                    instance_lock.release()

    app = FastAPI(
        title="OpenCodeReview Manager",
        version=settings.app_version,
        lifespan=lifespan,
        # Interactive API docs live under /api/docs — the SPA owns /docs.
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
    )
    app.state.mcp_server = mcp_server

    app.add_middleware(CSRFMiddleware, token=settings.csrf_token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(api_router)

    # The SPA has an /mcp page too: browser navigations (Accept: text/html)
    # get index.html; MCP protocol traffic (POST / event-stream GET) passes
    # through to the real MCP app. Starlette Mounts only match "/mcp/…", so
    # the exact "/mcp" path is registered as a plain route that normalizes
    # the scope to the mounted shape the transport expects. (Route treats
    # class instances as raw ASGI apps; plain functions would be wrapped as
    # request→response endpoints.)
    mcp_http_app = mcp_server.streamable_http_app()

    class _McpDispatch:
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                if (
                    scope.get("method") == "GET"
                    and _FRONTEND_DIST.is_dir()
                    and b"text/html"
                    in dict(scope.get("headers") or []).get(b"accept", b"")
                ):
                    await FileResponse(_FRONTEND_DIST / "index.html")(
                        scope, receive, send
                    )
                    return
                if scope.get("path") == "/mcp":
                    scope = dict(scope)
                    scope["path"] = "/mcp/"
                    scope["root_path"] = (scope.get("root_path") or "") + "/mcp"
            await mcp_http_app(scope, receive, send)

    mcp_dispatch = _McpDispatch()
    app.add_route(
        "/mcp", mcp_dispatch, methods=["GET", "POST", "DELETE"],
        include_in_schema=False,
    )
    app.mount("/mcp", mcp_dispatch)

    # Built frontend (SPA) — served when Stage 3 output exists.
    if _FRONTEND_DIST.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=_FRONTEND_DIST / "assets"),
            name="assets",
        )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith(("api/", "mcp")):
                return FileResponse(_FRONTEND_DIST / "index.html", status_code=404)
            candidate = _FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(_FRONTEND_DIST / "index.html")

    return app


app = create_app()
