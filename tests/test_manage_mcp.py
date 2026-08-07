from __future__ import annotations

import pytest

from vmcp_operator.adapters.driven.k8s.mcp_catalog import InMemoryMcpCatalog
from vmcp_operator.adapters.driving.dashboard.control_plane import build_control_plane
from vmcp_operator.adapters.driving.k8s.mapping import map_mcp, mcp_to_crd
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.usecases.manage_mcp import (
    McpConflictError,
    McpNotFoundError,
    mcp_from_add_body,
)


class FakeGateways:
    def __init__(self, items: list[GatewayDesired]) -> None:
        self._items = {item.key.as_str(): item for item in items}

    async def get(self, key: GatewayKey) -> GatewayDesired | None:
        return self._items.get(key.as_str())

    async def list_all(self) -> list[GatewayDesired]:
        return list(self._items.values())


def _gateway() -> GatewayDesired:
    return GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )


@pytest.mark.asyncio
async def test_add_update_list_remove_mcp() -> None:
    gateways = FakeGateways([_gateway()])
    catalog = InMemoryMcpCatalog()
    cp = build_control_plane(gateways=gateways, catalog=catalog)
    key = GatewayKey(namespace="team-a", name="main")

    desired = mcp_from_add_body(
        key,
        "docs",
        {
            "source": {"type": "RemoteHttp", "url": "https://docs.example.com/mcp"},
            "description": "docs",
        },
    )
    added = await cp.add_mcp.execute(desired)
    assert added.created is True
    assert added.mcp.name == "docs"

    with pytest.raises(McpConflictError):
        await cp.add_mcp.execute(desired)

    listed = await cp.list_mcps.execute(key)
    assert [m.name for m in listed] == ["docs"]

    updated = await cp.update_mcp.execute(
        key, "docs", fields={"forwardIdentity": True, "url": "https://docs.example.com/v2"}
    )
    assert updated.mcp.forward_identity is True
    assert updated.mcp.source.url == "https://docs.example.com/v2"  # type: ignore[union-attr]

    got = await cp.get_mcp.execute(key, "docs")
    assert got.forward_identity is True

    removed = await cp.remove_mcp.execute(key, "docs")
    assert removed.mcp.name == "docs"
    assert await catalog.list_for_gateway(key) == []

    with pytest.raises(McpNotFoundError):
        await cp.get_mcp.execute(key, "docs")


def test_mcp_to_crd_roundtrip_remote() -> None:
    key = GatewayKey(namespace="team-a", name="main")
    desired = mcp_from_add_body(
        key,
        "stand-api",
        {
            "source": {
                "type": "RemoteHttp",
                "url": "http://stand-api.svc/mcp",
                "bearerSecretRef": {"name": "tok", "key": "token"},
            },
            "forwardIdentity": True,
        },
    )
    crd = mcp_to_crd(desired)
    assert crd["kind"] == "VmcpMcpServer"
    mapped = map_mcp("team-a", "stand-api", crd["spec"])
    assert mapped.forward_identity is True
    assert mapped.source.url == "http://stand-api.svc/mcp"  # type: ignore[union-attr]


def test_mcp_from_add_body_container_image() -> None:
    key = GatewayKey(namespace="team-a", name="main")
    desired = mcp_from_add_body(
        key,
        "architect-c4",
        {"source": {"type": "ContainerImage", "image": "harbor.example.com/ai/architect-c4:1"}},
    )
    crd = mcp_to_crd(desired)
    assert crd["spec"]["source"]["type"] == "ContainerImage"
    assert crd["spec"]["source"]["ports"][0]["containerPort"] == 8080
