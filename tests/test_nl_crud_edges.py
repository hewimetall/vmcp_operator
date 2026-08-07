from __future__ import annotations

import pytest

from vmcp_operator.adapters.driven.k8s.mcp_catalog import InMemoryMcpCatalog
from vmcp_operator.adapters.driving.dashboard.control_plane import build_control_plane
from vmcp_operator.domain.models.control_plane import McpMutation, NlIntent
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


def _gw() -> GatewayDesired:
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


def test_nl_get_and_field_parsing() -> None:
    cp = build_control_plane(gateways=FakeGateways([_gw()]), catalog=InMemoryMcpCatalog())
    intent = cp.nl_crud.parse(
        'update mcp docs on team-a/main set description="hello world" forwardIdentity=да'
    )
    assert intent.fields == {"description": "hello world", "forwardIdentity": True}
    with_desc = cp.nl_crud.parse(
        "add mcp docs to team-a/main url https://docs.example.com/mcp "
        "forwardIdentity=false description handy docs"
    )
    assert with_desc.fields is not None
    assert with_desc.fields["forwardIdentity"] is False
    assert with_desc.fields["description"] == "handy docs"
    with pytest.raises(ValueError, match="non-empty"):
        cp.nl_crud.parse("   ")
    with pytest.raises(ValueError, match="key=value"):
        cp.nl_crud.parse("update mcp docs on team-a/main set ???")
    with pytest.raises(ValueError, match="namespace/name"):
        cp.nl_crud.intent_from_structured({"action": "list", "gateway": "nogateway"})
    with pytest.raises(ValueError, match="namespace/name"):
        cp.nl_crud.intent_from_structured({"action": "list", "gateway": "/only"})
    with pytest.raises(ValueError, match="invalid boolean"):
        cp.nl_crud.parse("update mcp docs on team-a/main set enabled=maybe")
    quoted = cp.nl_crud.parse(
        "update mcp docs on team-a/main set description='hello' enabled=нет"
    )
    assert quoted.fields == {"description": "hello", "enabled": False}


@pytest.mark.asyncio
async def test_nl_get_and_errors() -> None:
    catalog = InMemoryMcpCatalog()
    cp = build_control_plane(gateways=FakeGateways([_gw()]), catalog=catalog)
    await cp.nl_crud.execute(
        cp.nl_crud.parse("add mcp docs to team-a/main url https://docs.example.com/mcp")
    )
    got = await cp.nl_crud.execute(cp.nl_crud.parse("get mcp docs on team-a/main"))
    assert got.mcp is not None
    assert got.mcp.name == "docs"
    with pytest.raises(LookupError):
        await cp.nl_crud.execute(cp.nl_crud.parse("get mcp missing on team-a/main"))
    with pytest.raises(ValueError, match="already exists"):
        await cp.nl_crud.execute(
            cp.nl_crud.parse("add mcp docs to team-a/main url https://docs.example.com/mcp")
        )
    with pytest.raises(ValueError, match="name is required"):
        await cp.nl_crud.execute(
            NlIntent(mutation=McpMutation.GET, gateway=GatewayKey("team-a", "main"))
        )
    with pytest.raises(ValueError, match="gateway is required"):
        await cp.nl_crud.execute(NlIntent(mutation=McpMutation.LIST))
