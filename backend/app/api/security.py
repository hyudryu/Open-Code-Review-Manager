"""CSRF double-submit protection + localhost binding (SPEC §27 API Security).

The server issues a token at startup. Safe (GET/HEAD/OPTIONS) responses set
the ``ocrcc_csrf`` cookie; state-changing requests to ``/api/`` must echo
the token in the ``X-OCR-CSRF`` header, and both must match the server
token. The MCP endpoint is not browser-served and is exempt.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import generate_csrf_token

CSRF_COOKIE = "ocrcc_csrf"
CSRF_HEADER = "x-ocr-csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str | None = None) -> None:  # noqa: ANN001
        super().__init__(app)
        self.token = token or generate_csrf_token()

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        path = request.url.path
        if path.startswith("/api/") and request.method not in SAFE_METHODS:
            header = request.headers.get(CSRF_HEADER)
            cookie = request.cookies.get(CSRF_COOKIE)
            if not header or not cookie or header != cookie or header != self.token:
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "csrf_failed",
                            "message": "The request failed the anti-CSRF check.",
                            "detail": "The X-OCR-CSRF header must match the ocrcc_csrf cookie.",
                            "next_action": "Retry from the application UI.",
                        }
                    },
                )
        response = await call_next(request)
        if (
            path.startswith("/api/")
            and request.method in SAFE_METHODS
            and CSRF_COOKIE not in request.cookies
        ):
            response.set_cookie(
                CSRF_COOKIE, self.token, httponly=False, samesite="strict"
            )
        return response
