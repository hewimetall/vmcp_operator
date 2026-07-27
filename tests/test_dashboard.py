from __future__ import annotations

import base64

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from vmcp_operator.adapters.driving.dashboard.app import DashboardAuth, RateLimiter, create_app
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.usecases.issue_use_token import IssueUseToken
from vmcp_operator.domain.usecases.list_environments import ListEnvironments


class FakeGateways:
    def __init__(self, items: list[GatewayDesired]) -> None:
        self._items = {item.key.as_str(): item for item in items}

    async def get(self, key: GatewayKey) -> GatewayDesired | None:
        return self._items.get(key.as_str())

    async def list_all(self) -> list[GatewayDesired]:
        return list(self._items.values())


class FakeIssuer:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    async def issue_use_token(self, key: GatewayKey, client_name: str) -> str:
        marker = f"{key.as_str()}:{client_name}"
        if marker in self.seen:
            raise FileExistsError("duplicate")
        self.seen.add(marker)
        return "secret-token-value"


def _auth_header(user: str = "admin", password: str = "secret") -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _gateway() -> GatewayDesired:
    return GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
        admin_route=RouteDesired(
            hostname="admin-main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )


@pytest_asyncio.fixture
async def client() -> TestClient:
    gateways = FakeGateways([_gateway()])
    app = create_app(
        auth=DashboardAuth(username="admin", password="secret"),
        list_environments=ListEnvironments(gateways=gateways, phases={"team-a/main": "Ready"}),
        issue_use_token=IssueUseToken(gateways=gateways, issuer=FakeIssuer()),
        rate_limiter=RateLimiter(limit=5, window=60),
    )
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


@pytest.mark.asyncio
async def test_dashboard_requires_auth(client: TestClient) -> None:
    resp = await client.get("/api/environments")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_dashboard_lists_environments_and_issues_token(client: TestClient) -> None:
    headers = _auth_header()
    resp = await client.get("/api/environments", headers=headers)
    assert resp.status == 200
    assert resp.headers["Cache-Control"] == "no-store"
    body = await resp.json()
    assert body[0]["key"] == "team-a/main"
    assert body[0]["adminUrl"] == "https://admin-main.example.com/admin"

    resp = await client.post(
        "/api/tokens",
        headers=headers,
        json={"gateway": "team-a/main", "clientName": "cursor"},
    )
    assert resp.status == 200
    payload = await resp.json()
    assert payload["scope"] == "mcp:use"
    assert payload["token"] == "secret-token-value"

    resp = await client.post(
        "/api/tokens",
        headers=headers,
        json={"gateway": "team-a/main", "clientName": "cursor"},
    )
    assert resp.status == 409


@pytest.mark.asyncio
async def test_dashboard_rate_limit(client: TestClient) -> None:
    headers = _auth_header()
    for idx in range(5):
        resp = await client.post(
            "/api/tokens",
            headers=headers,
            json={"gateway": "team-a/main", "clientName": f"c{idx}"},
        )
        assert resp.status == 200
    resp = await client.post(
        "/api/tokens",
        headers=headers,
        json={"gateway": "team-a/main", "clientName": "overflow"},
    )
    assert resp.status == 429


@pytest.mark.asyncio
async def test_dashboard_index_and_bad_origin(client: TestClient) -> None:
    headers = _auth_header()
    resp = await client.get("/", headers=headers)
    assert resp.status == 200
    assert "vmcp environments" in await resp.text()
    resp = await client.post(
        "/api/tokens",
        headers={**headers, "Origin": "https://evil.example"},
        json={"gateway": "team-a/main", "clientName": "x"},
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_rate_limiter_expires_old_hits() -> None:
    limiter = RateLimiter(limit=1, window=0.01)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    import time

    time.sleep(0.02)
    assert limiter.allow("a") is True


@pytest.mark.asyncio
async def test_dashboard_validation_errors(client: TestClient) -> None:
    headers = _auth_header()
    resp = await client.post(
        "/api/tokens",
        headers=headers,
        json={"gateway": "noslash", "clientName": "x"},
    )
    assert resp.status == 400
    resp = await client.post(
        "/api/tokens",
        headers=headers,
        json={"gateway": "missing/gw", "clientName": "x"},
    )
    assert resp.status == 404
    resp = await client.post(
        "/api/tokens",
        headers=headers,
        json={"gateway": "team-a/main", "clientName": "  "},
    )
    assert resp.status == 400
    resp = await client.get("/api/environments", headers=_auth_header("admin", "wrong"))
    assert resp.status == 401
    resp = await client.get(
        "/api/environments",
        headers={"Authorization": "Basic !!!"},
    )
    assert resp.status == 401
    resp = await client.get("/static/dashboard.css", headers=headers)
    assert resp.status == 200
