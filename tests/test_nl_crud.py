from __future__ import annotations

import pytest

from vmcp_operator.adapters.driven.k8s.mcp_catalog import InMemoryMcpCatalog
from vmcp_operator.adapters.driving.dashboard.control_plane import build_control_plane
from vmcp_operator.domain.models.control_plane import McpMutation
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
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
async def test_nl_add_list_update_remove_en_and_ru() -> None:
    cp = build_control_plane(
        gateways=FakeGateways([_gateway()]),
        catalog=InMemoryMcpCatalog(),
    )
    nl = cp.nl_crud

    dry = nl.parse(
        "add mcp docs to team-a/main url https://docs.example.com/mcp",
        dry_run=True,
    )
    assert dry.mutation == McpMutation.ADD
    assert dry.dry_run is True
    dry_result = await nl.execute(dry)
    assert dry_result.applied is False

    added = await nl.execute(
        nl.parse("add mcp docs to team-a/main url https://docs.example.com/mcp forward identity")
    )
    assert added.applied is True
    assert added.mcp is not None
    assert added.mcp.forward_identity is True

    listed = await nl.execute(nl.parse("list mcps on team-a/main"))
    assert listed.message == "1 mcp(s)"
    assert listed.mcps[0].name == "docs"

    updated = await nl.execute(
        nl.parse("update mcp docs on team-a/main set enabled=false url=https://docs.example.com/v2")
    )
    assert updated.mcp is not None
    assert updated.mcp.enabled is False

    removed = await nl.execute(nl.parse("удали mcp docs из team-a/main"))
    assert removed.message == "removed"

    empty = await nl.execute(nl.parse("список mcps для team-a/main"))
    assert empty.mcps == ()


def test_nl_parse_image_and_structured() -> None:
    cp = build_control_plane(
        gateways=FakeGateways([_gateway()]),
        catalog=InMemoryMcpCatalog(),
    )
    intent = cp.nl_crud.parse(
        "добавь mcp architect-c4 в team-a/main image harbor.example.com/ai/architect-c4:1"
    )
    assert intent.fields is not None
    assert intent.fields["source"]["type"] == "ContainerImage"

    structured = cp.nl_crud.intent_from_structured(
        {
            "action": "get",
            "gateway": "team-a/main",
            "name": "docs",
        }
    )
    assert structured.mutation == McpMutation.GET


def test_nl_rejects_unknown() -> None:
    cp = build_control_plane(
        gateways=FakeGateways([_gateway()]),
        catalog=InMemoryMcpCatalog(),
    )
    with pytest.raises(ValueError, match="unrecognized"):
        cp.nl_crud.parse("please invent a gateway")
