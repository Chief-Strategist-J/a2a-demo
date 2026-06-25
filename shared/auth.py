"""Bearer-token authentication middleware for A2A agents.

Public paths (/.well-known/agent.json, /health, /ui*) bypass auth.
All other paths require: Authorization: Bearer <token>
"""
from __future__ import annotations

import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_PUBLIC_PREFIXES = (
    "/.well-known/",
    "/health",
    "/ui",
    "/docs",
    "/openapi",
)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, valid_tokens: set[str]) -> None:
        super().__init__(app)
        self._tokens = valid_tokens

    async def dispatch(self, request: Request, call_next) -> Response:
        if any(request.url.path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return _error(401, -32001, "Missing Authorization header", "Bearer")

        token = auth[7:].strip()
        if token not in self._tokens:
            return _error(401, -32001, "Invalid token", "Bearer")

        return await call_next(request)


def _error(status: int, code: int, msg: str, realm: str) -> Response:
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": code, "message": msg},
    })
    headers = {
        "Content-Type": "application/json",
        "WWW-Authenticate": f'Bearer realm="{realm}"',
    }
    return Response(body, status_code=status, headers=headers)
