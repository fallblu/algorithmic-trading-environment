"""Dashboard auth — simple token/password gate middleware."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Simple token-based auth middleware.

    If auth_token is empty or None, authentication is disabled.
    Token can be provided via:
    - Query param: ?token=xxx
    - Header: Authorization: Bearer xxx
    - Cookie: auth_token=xxx
    """

    def __init__(self, app, auth_token: str = "") -> None:
        super().__init__(app)
        self._token = auth_token

    async def dispatch(self, request: Request, call_next):
        if not self._token:
            return await call_next(request)

        # Allow static files without auth
        if request.url.path.startswith("/static"):
            return await call_next(request)

        # Check token from various sources
        token = (
            request.query_params.get("token")
            or _extract_bearer(request.headers.get("authorization", ""))
            or request.cookies.get("auth_token")
        )

        if token != self._token:
            if request.url.path.startswith("/api"):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return JSONResponse(
                {"error": "Unauthorized. Provide token via ?token=xxx"},
                status_code=401,
            )

        response = await call_next(request)
        return response


def _extract_bearer(auth_header: str) -> str | None:
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None
