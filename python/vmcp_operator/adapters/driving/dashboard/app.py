"""Fleet dashboard HTTP adapter (aiohttp + vendored static assets)."""

from __future__ import annotations

import base64
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from vmcp_operator.domain.models.gateway import GatewayKey
from vmcp_operator.domain.usecases.issue_use_token import DuplicateTokenError, IssueUseToken
from vmcp_operator.domain.usecases.list_environments import ListEnvironments

STATIC_ROOT = Path(__file__).resolve().parents[3] / "static"


@dataclass(frozen=True, slots=True)
class DashboardAuth:
    username: str
    password: str


class RateLimiter:
    def __init__(self, limit: int = 10, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


def _unauthorized() -> web.Response:
    return web.Response(
        status=401,
        text="Unauthorized",
        headers={"WWW-Authenticate": 'Basic realm="vmcp-operator"'},
    )


def _check_basic(request: web.Request, auth: DashboardAuth) -> bool:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False
    return secrets.compare_digest(username, auth.username) and secrets.compare_digest(
        password, auth.password
    )


def _security_headers(response: web.Response) -> web.Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def create_app(
    *,
    auth: DashboardAuth,
    list_environments: ListEnvironments,
    issue_use_token: IssueUseToken,
    rate_limiter: RateLimiter | None = None,
) -> web.Application:
    app = web.Application()
    limiter = rate_limiter or RateLimiter()

    @web.middleware
    async def auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.path.startswith("/static/"):
            return await handler(request)
        if not _check_basic(request, auth):
            return _security_headers(_unauthorized())
        return await handler(request)

    app.middlewares.append(auth_middleware)

    async def index(_: web.Request) -> web.Response:
        html = (STATIC_ROOT / "dashboard.html").read_text(encoding="utf-8")
        return _security_headers(web.Response(text=html, content_type="text/html"))

    async def environments(request: web.Request) -> web.Response:
        rows = await list_environments.execute()
        payload = [
            {
                "key": row.key.as_str(),
                "phase": row.phase,
                "publicHostname": row.public_hostname,
                "adminUrl": row.admin_url,
            }
            for row in rows
        ]
        return _security_headers(web.json_response(payload))

    async def issue_token(request: web.Request) -> web.Response:
        origin = request.headers.get("Origin")
        expected = f"{request.scheme}://{request.host}"
        # Same-origin only; missing Origin is allowed for non-browser clients.
        if origin is not None and origin != expected:
            return _security_headers(web.json_response({"error": "origin"}, status=403))
        client_key = request.remote or "unknown"
        if not limiter.allow(client_key):
            return _security_headers(web.json_response({"error": "rate_limited"}, status=429))
        body = await request.json()
        gateway = str(body.get("gateway", ""))
        client_name = str(body.get("clientName", ""))
        if "/" not in gateway:
            return _security_headers(web.json_response({"error": "gateway"}, status=400))
        ns, name = gateway.split("/", 1)
        try:
            issued = await issue_use_token.execute(GatewayKey(namespace=ns, name=name), client_name)
        except DuplicateTokenError:
            return _security_headers(web.json_response({"error": "duplicate"}, status=409))
        except LookupError:
            return _security_headers(web.json_response({"error": "not_found"}, status=404))
        except ValueError as exc:
            return _security_headers(web.json_response({"error": str(exc)}, status=400))
        return _security_headers(
            web.json_response(
                {
                    "gateway": issued.gateway.as_str(),
                    "clientName": issued.client_name,
                    "scope": issued.scope,
                    "token": issued.token,
                }
            )
        )

    app.router.add_get("/", index)
    app.router.add_get("/api/environments", environments)
    app.router.add_post("/api/tokens", issue_token)
    app.router.add_static("/static/", STATIC_ROOT)
    return app
