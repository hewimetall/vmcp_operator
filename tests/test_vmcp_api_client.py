from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from vmcp_operator.adapters.driven.vmcp_api.client import VmcpApiClient, VmcpApiError

_REAL_ASYNC_CLIENT = httpx.AsyncClient


class Transport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.reload_payload: dict[str, Any] = {
            "sha256": "abc",
            "upstreams": ["context7", "architect-c4"],
        }
        self.tokens: set[str] = set()
        self.fail_reload = False
        self.fail_list = False
        self.fail_token = False
        self.token_without_value = False
        self.list_as_array = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = None
        if request.content:
            body = json.loads(request.content.decode())
        self.calls.append((request.method, request.url.path, body))
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return httpx.Response(401, json={"error": "auth"})

        if request.method == "POST" and request.url.path == "/api/v1/registry/reload":
            if self.fail_reload:
                return httpx.Response(500, json={"error": "boom"})
            return httpx.Response(200, json=self.reload_payload)
        if request.method == "GET" and request.url.path == "/api/v1/upstreams":
            if self.list_as_array:
                return httpx.Response(
                    200,
                    json=[{"name": "zulu"}, {"name": "alpha"}],
                )
            if self.fail_list:
                return httpx.Response(500, json={"error": "boom"})
            return httpx.Response(200, json={"upstreams": ["zulu", "alpha"]})
        if request.method == "POST" and request.url.path == "/api/v1/tokens":
            assert body is not None
            name = body["name"]
            if self.fail_token:
                return httpx.Response(500, json={"error": "boom"})
            if self.token_without_value:
                return httpx.Response(201, json={})
            if name in self.tokens:
                return httpx.Response(409, json={"error": "duplicate"})
            self.tokens.add(name)
            assert body["scopes"] == ["mcp:use"]
            return httpx.Response(201, json={"token": f"tok-{name}"})
        return httpx.Response(404, json={"error": "missing"})


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: Transport) -> None:
    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.vmcp_api.client.httpx.AsyncClient",
        factory,
    )


@pytest.mark.asyncio
async def test_reload_and_token_flows(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = Transport()
    _patch_client(monkeypatch, transport)
    client = VmcpApiClient(base_url="http://vmcp.team-a.svc:8080", admin_token="secret")

    status = await client.reload_registry(desired_sha256="abc")
    assert status.matched is True
    assert status.upstream_names == ("architect-c4", "context7")

    names = await client.list_upstream_names()
    assert names == ("alpha", "zulu")

    token = await client.issue_static_token(client_name="cursor")
    assert token == "tok-cursor"
    with pytest.raises(FileExistsError):
        await client.issue_static_token(client_name="cursor")


@pytest.mark.asyncio
async def test_reload_mismatch_and_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = Transport()
    transport.reload_payload = {"sha256": "other", "upstreams": []}
    _patch_client(monkeypatch, transport)
    client = VmcpApiClient(base_url="http://vmcp", admin_token="secret")
    status = await client.reload_registry(desired_sha256="abc")
    assert status.matched is False

    transport.fail_reload = True
    with pytest.raises(VmcpApiError, match="reload failed"):
        await client.reload_registry(desired_sha256="abc")

    transport.fail_reload = False
    transport.fail_list = True
    with pytest.raises(VmcpApiError, match="list upstreams failed"):
        await client.list_upstream_names()

    transport.fail_list = False
    transport.list_as_array = True
    assert await client.list_upstream_names() == ("alpha", "zulu")

    transport.fail_token = True
    with pytest.raises(VmcpApiError, match="issue token failed"):
        await client.issue_static_token(client_name="x")
    transport.fail_token = False
    transport.token_without_value = True
    with pytest.raises(VmcpApiError, match="missing token"):
        await client.issue_static_token(client_name="y")
