from __future__ import annotations

from typing import cast

import pytest

from vmcp_operator.adapters.driven.k8s.mcp_catalog import InMemoryMcpCatalog
from vmcp_operator.adapters.driving.dashboard.control_plane import build_control_plane
from vmcp_operator.adapters.driving.k8s.mapping import mcp_to_crd, mcp_to_public_dict
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
    SkillRef,
)
from vmcp_operator.domain.models.mcp import (
    ContainerImageSource,
    McpEndpoint,
    McpServerDesired,
    NamedPort,
    RemoteHttpSource,
    ToolOverrideDesired,
    WebExposureDesired,
)
from vmcp_operator.domain.usecases.manage_mcp import (
    McpNotFoundError,
    apply_mcp_fields,
    mcp_from_add_body,
)


class FakeGateways:
    def __init__(self, items: list[GatewayDesired]) -> None:
        self._items = {item.key.as_str(): item for item in items}

    async def get(self, key: GatewayKey) -> GatewayDesired | None:
        return self._items.get(key.as_str())

    async def list_all(self) -> list[GatewayDesired]:
        return list(self._items.values())


def _gateway(ns: str = "team-a", name: str = "main") -> GatewayDesired:
    return GatewayDesired(
        key=GatewayKey(namespace=ns, name=name),
        image="harbor.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname=f"{name}.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )


def test_mcp_from_add_body_validation() -> None:
    key = GatewayKey(namespace="team-a", name="main")
    with pytest.raises(ValueError, match="lowercase"):
        mcp_from_add_body(key, "Bad_Name", {"url": "https://x/mcp"})
    with pytest.raises(ValueError, match="url"):
        mcp_from_add_body(key, "docs", {"source": {"type": "RemoteHttp"}})
    with pytest.raises(ValueError, match="image"):
        mcp_from_add_body(key, "x", {"source": {"type": "ContainerImage"}})
    with pytest.raises(ValueError, match="unsupported"):
        mcp_from_add_body(key, "x", {"source": {"type": "Stdio"}})


def test_apply_mcp_fields_and_unknown() -> None:
    mcp = mcp_from_add_body(
        GatewayKey(namespace="team-a", name="main"),
        "docs",
        {"source": {"type": "RemoteHttp", "url": "https://a/mcp"}},
    )
    patched = apply_mcp_fields(
        mcp,
        {
            "description": "n",
            "enabled": False,
            "bearerSecretRef": {"name": "b", "key": "token"},
        },
    )
    assert patched.description == "n"
    assert patched.enabled is False
    assert isinstance(patched.source, RemoteHttpSource)
    assert patched.source.bearer_secret_ref is not None
    cleared = apply_mcp_fields(patched, {"bearerSecretRef": None})
    assert cleared.source.bearer_secret_ref is None  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="at least one"):
        apply_mcp_fields(mcp, {})
    with pytest.raises(ValueError, match="unsupported update"):
        apply_mcp_fields(mcp, {"nope": 1})
    container = mcp_from_add_body(
        GatewayKey(namespace="team-a", name="main"),
        "c4",
        {"source": {"type": "ContainerImage", "image": "img:1"}},
    )
    with pytest.raises(ValueError, match="url can only"):
        apply_mcp_fields(container, {"url": "https://x"})
    bumped = apply_mcp_fields(container, {"image": "img:2"})
    assert bumped.source.image == "img:2"  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="image can only"):
        apply_mcp_fields(mcp, {"image": "img:2"})


def test_mcp_to_crd_rich_fields() -> None:
    mcp = McpServerDesired(
        namespace="team-a",
        name="rich",
        gateway_key=GatewayKey(namespace="team-a", name="main"),
        enabled=True,
        description="d",
        source=ContainerImageSource(
            image="img:1",
            ports=(NamedPort(name="http", container_port=9),),
            mcp_endpoint=McpEndpoint(port_name="http", path="/mcp"),
            env=(("A", "1"),),
        ),
        tool_overrides=(ToolOverrideDesired(name="t", read_only=True, task_support="optional"),),
        skill_refs=(SkillRef(name="s", key="k.yaml"),),
        web_exposures=(
            WebExposureDesired(
                name="viewer",
                port_name="http",
                hostname="v.example.com",
                paths=("/",),
                gateway_ref=GatewayParentRef(name="kgateway", namespace="gw", section_name="https"),
                annotations=(("a", "b"),),
                public_base_url_env="PUBLIC",
            ),
        ),
        forward_identity=True,
    )
    crd = mcp_to_crd(mcp)
    assert crd["spec"]["toolOverrides"][0]["taskSupport"] == "optional"
    assert crd["spec"]["webExposures"][0]["publicBaseUrlEnv"] == "PUBLIC"
    assert crd["spec"]["source"]["env"] == [{"name": "A", "value": "1"}]
    public = mcp_to_public_dict(mcp)
    assert public["source"]["type"] == "ContainerImage"


@pytest.mark.asyncio
async def test_update_remove_missing_and_wrong_gateway() -> None:
    catalog = InMemoryMcpCatalog()
    cp = build_control_plane(
        gateways=FakeGateways([_gateway()]),
        catalog=catalog,
    )
    key = GatewayKey(namespace="team-a", name="main")
    with pytest.raises(McpNotFoundError):
        await cp.update_mcp.execute(key, "missing", fields={"enabled": False})
    with pytest.raises(McpNotFoundError):
        await cp.remove_mcp.execute(key, "missing")
    with pytest.raises(LookupError, match="gateway"):
        await cp.list_mcps.execute(GatewayKey(namespace="x", name="y"))

    # Force-store an MCP pointing at another gateway name in same ns.
    await catalog.upsert(
        McpServerDesired(
            namespace="team-a",
            name="docs",
            gateway_key=GatewayKey(namespace="team-a", name="other"),
            enabled=True,
            description=None,
            source=RemoteHttpSource(url="https://a/mcp"),
        )
    )
    with pytest.raises(McpNotFoundError):
        await cp.get_mcp.execute(key, "docs")
    with pytest.raises(McpNotFoundError):
        await cp.update_mcp.execute(key, "docs", fields={"enabled": False})
    with pytest.raises(McpNotFoundError):
        await cp.remove_mcp.execute(key, "docs")

    class FlakyCatalog(InMemoryMcpCatalog):
        async def delete(self, namespace: str, name: str) -> bool:
            del namespace, name
            return False

    flaky_catalog = FlakyCatalog()
    await flaky_catalog.upsert(
        mcp_from_add_body(key, "gone", {"source": {"type": "RemoteHttp", "url": "https://a/mcp"}})
    )
    flaky_cp = build_control_plane(gateways=FakeGateways([_gateway()]), catalog=flaky_catalog)
    with pytest.raises(McpNotFoundError):
        await flaky_cp.remove_mcp.execute(key, "gone")

    with pytest.raises(ValueError, match="url must be non-empty"):
        apply_mcp_fields(
            mcp_from_add_body(key, "x", {"source": {"type": "RemoteHttp", "url": "https://a"}}),
            {"url": "  "},
        )
    with pytest.raises(ValueError, match="image must be non-empty"):
        apply_mcp_fields(
            mcp_from_add_body(
                key, "c", {"source": {"type": "ContainerImage", "image": "img:1"}}
            ),
            {"image": ""},
        )
    with pytest.raises(ValueError, match="bearerSecretRef can only"):
        apply_mcp_fields(
            mcp_from_add_body(
                key, "c", {"source": {"type": "ContainerImage", "image": "img:1"}}
            ),
            {"bearerSecretRef": {"name": "b"}},
        )
    with pytest.raises(ValueError, match="path can only"):
        apply_mcp_fields(
            mcp_from_add_body(key, "r", {"source": {"type": "RemoteHttp", "url": "https://a"}}),
            {"path": "/x"},
        )
    with pytest.raises(ValueError, match="must match gateway namespace"):
        mcp_to_crd(
            McpServerDesired(
                namespace="team-a",
                name="x",
                gateway_key=GatewayKey(namespace="other", name="main"),
                enabled=True,
                description=None,
                source=RemoteHttpSource(url="https://a/mcp"),
            )
        )
    with pytest.raises(ValueError, match="must live in the same namespace"):
        await cp.add_mcp.execute(
            McpServerDesired(
                namespace="team-a",
                name="cross",
                gateway_key=GatewayKey(namespace="other", name="main"),
                enabled=True,
                description=None,
                source=RemoteHttpSource(url="https://a/mcp"),
            )
        )
    with pytest.raises(ValueError, match="RemoteHttp url"):
        await cp.add_mcp.execute(
            McpServerDesired(
                namespace="team-a",
                name="empty-url",
                gateway_key=key,
                enabled=True,
                description=None,
                source=RemoteHttpSource(url="  "),
            )
        )
    with pytest.raises(ValueError, match="ContainerImage image"):
        await cp.add_mcp.execute(
            McpServerDesired(
                namespace="team-a",
                name="empty-img",
                gateway_key=key,
                enabled=True,
                description=None,
                source=ContainerImageSource(
                    image="",
                    ports=(NamedPort(name="http", container_port=1),),
                    mcp_endpoint=McpEndpoint(port_name="http"),
                ),
            )
        )
    with pytest.raises(ValueError, match="non-empty"):
        await cp.add_mcp.execute(
            McpServerDesired(
                namespace="team-a",
                name="  ",
                gateway_key=key,
                enabled=True,
                description=None,
                source=RemoteHttpSource(url="https://a/mcp"),
            )
        )
    with pytest.raises(TypeError, match="unsupported source"):
        mcp_to_crd(
            McpServerDesired(
                namespace="team-a",
                name="x",
                gateway_key=key,
                enabled=True,
                description=None,
                source=cast(RemoteHttpSource, object()),
            )
        )
