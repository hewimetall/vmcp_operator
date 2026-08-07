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

from vmcp_operator.adapters.driving.k8s.mapping import mcp_to_public_dict
from vmcp_operator.domain.models.gateway import GatewayKey
from vmcp_operator.domain.usecases.issue_use_token import DuplicateTokenError, IssueUseToken
from vmcp_operator.domain.usecases.list_environments import ListEnvironments
from vmcp_operator.domain.usecases.manage_mcp import (
    AddMcp,
    GetMcp,
    ListMcps,
    McpConflictError,
    McpNotFoundError,
    RemoveMcp,
    UpdateMcp,
    mcp_from_add_body,
)
from vmcp_operator.domain.usecases.nl_crud import NlCrud

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


def _parse_gateway(raw: str) -> GatewayKey | None:
    if "/" not in raw:
        return None
    ns, name = raw.split("/", 1)
    if not ns or not name:
        return None
    return GatewayKey(namespace=ns, name=name)


def create_app(
    *,
    auth: DashboardAuth,
    list_environments: ListEnvironments,
    issue_use_token: IssueUseToken,
    list_mcps: ListMcps,
    get_mcp: GetMcp,
    add_mcp: AddMcp,
    update_mcp: UpdateMcp,
    remove_mcp: RemoveMcp,
    nl_crud: NlCrud,
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
        del request
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
        key = _parse_gateway(gateway)
        if key is None:
            return _security_headers(web.json_response({"error": "gateway"}, status=400))
        try:
            issued = await issue_use_token.execute(key, client_name)
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

    async def mcp_collection(request: web.Request) -> web.Response:
        key = GatewayKey(
            namespace=request.match_info["namespace"],
            name=request.match_info["gateway"],
        )
        if request.method == "GET":
            try:
                rows = await list_mcps.execute(key)
            except LookupError:
                return _security_headers(web.json_response({"error": "not_found"}, status=404))
            return _security_headers(
                web.json_response([mcp_to_public_dict(item) for item in rows])
            )

        body = await request.json()
        name = str(body.get("name") or "").strip()
        try:
            desired = mcp_from_add_body(key, name, body)
            result = await add_mcp.execute(desired)
        except McpConflictError:
            return _security_headers(web.json_response({"error": "conflict"}, status=409))
        except LookupError:
            return _security_headers(web.json_response({"error": "not_found"}, status=404))
        except (ValueError, TypeError) as exc:
            return _security_headers(web.json_response({"error": str(exc)}, status=400))
        return _security_headers(
            web.json_response(mcp_to_public_dict(result.mcp), status=201)
        )

    async def mcp_item(request: web.Request) -> web.Response:
        key = GatewayKey(
            namespace=request.match_info["namespace"],
            name=request.match_info["gateway"],
        )
        name = request.match_info["mcp"]
        if request.method == "GET":
            try:
                mcp = await get_mcp.execute(key, name)
            except McpNotFoundError:
                return _security_headers(web.json_response({"error": "not_found"}, status=404))
            except LookupError:
                return _security_headers(web.json_response({"error": "not_found"}, status=404))
            return _security_headers(web.json_response(mcp_to_public_dict(mcp)))

        if request.method == "DELETE":
            try:
                result = await remove_mcp.execute(key, name)
            except McpNotFoundError:
                return _security_headers(web.json_response({"error": "not_found"}, status=404))
            except LookupError:
                return _security_headers(web.json_response({"error": "not_found"}, status=404))
            return _security_headers(
                web.json_response(
                    {"removed": True, "mcp": mcp_to_public_dict(result.mcp)}
                )
            )

        body = await request.json()
        try:
            result = await update_mcp.execute(key, name, fields=body)
        except McpNotFoundError:
            return _security_headers(web.json_response({"error": "not_found"}, status=404))
        except LookupError:
            return _security_headers(web.json_response({"error": "not_found"}, status=404))
        except ValueError as exc:
            return _security_headers(web.json_response({"error": str(exc)}, status=400))
        return _security_headers(web.json_response(mcp_to_public_dict(result.mcp)))

    async def nl_endpoint(request: web.Request) -> web.Response:
        body = await request.json()
        dry_run = bool(body.get("dryRun", False))
        try:
            if utterance := body.get("utterance") or body.get("text"):
                intent = nl_crud.parse(str(utterance), dry_run=dry_run)
            else:
                intent = nl_crud.intent_from_structured({**body, "dryRun": dry_run})
            result = await nl_crud.execute(intent)
        except LookupError as exc:
            return _security_headers(
                web.json_response({"error": "not_found", "message": str(exc)}, status=404)
            )
        except ValueError as exc:
            return _security_headers(
                web.json_response({"error": "bad_request", "message": str(exc)}, status=400)
            )

        payload: dict[str, Any] = {
            "applied": result.applied,
            "message": result.message,
            "intent": {
                "action": result.intent.mutation.value,
                "gateway": (
                    result.intent.gateway.as_str() if result.intent.gateway else None
                ),
                "name": result.intent.name,
                "fields": result.intent.fields,
                "dryRun": result.intent.dry_run,
            },
        }
        if result.mcp is not None:
            payload["mcp"] = mcp_to_public_dict(result.mcp)
        if result.mcps:
            payload["mcps"] = [mcp_to_public_dict(item) for item in result.mcps]
        return _security_headers(web.json_response(payload))

    app.router.add_get("/", index)
    app.router.add_get("/api/environments", environments)
    app.router.add_post("/api/tokens", issue_token)
    app.router.add_get("/api/gateways/{namespace}/{gateway}/mcps", mcp_collection)
    app.router.add_post("/api/gateways/{namespace}/{gateway}/mcps", mcp_collection)
    app.router.add_get("/api/gateways/{namespace}/{gateway}/mcps/{mcp}", mcp_item)
    app.router.add_put("/api/gateways/{namespace}/{gateway}/mcps/{mcp}", mcp_item)
    app.router.add_delete("/api/gateways/{namespace}/{gateway}/mcps/{mcp}", mcp_item)
    app.router.add_post("/api/nl", nl_endpoint)
    app.router.add_static("/static/", STATIC_ROOT)
    return app
