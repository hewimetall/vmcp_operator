from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vmcp_operator.adapters.driven.k8s.mcp_catalog import InMemoryMcpCatalog
from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.adapters.driving.dashboard.control_plane import build_control_plane
from vmcp_operator.adapters.driving.k8s.mapping import map_mcp, mcp_to_crd, mcp_to_public_dict
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    ProxyDesired,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.models.mcp import McpServerDesired, VmcpProxySource
from vmcp_operator.domain.usecases.manage_mcp import apply_mcp_fields, mcp_from_add_body
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests
from vmcp_operator.domain.usecases.render_mcp_manifests import RenderMcpManifests


class FakeGateways:
    def __init__(self, items: list[GatewayDesired]) -> None:
        self._items = {item.key.as_str(): item for item in items}

    async def get(self, key: GatewayKey) -> GatewayDesired | None:
        return self._items.get(key.as_str())

    async def list_all(self) -> list[GatewayDesired]:
        return list(self._items.values())


class FakeSkills:
    async def load_skills(self, gateway, mcps):
        del gateway, mcps
        return []


def _gw(
    name: str,
    *,
    ns: str = "team-a",
    proxy: bool = False,
    path: str = "/mcp-proxy",
) -> GatewayDesired:
    return GatewayDesired(
        key=GatewayKey(namespace=ns, name=name),
        image="harbor.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname=f"{name}.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
        proxy=ProxyDesired(enabled=proxy, path=path),
    )


def test_map_sample_vmcp_proxy_and_cluster_url() -> None:
    doc = yaml.safe_load(
        (Path("deploy/samples/mcp-vmcp-proxy.yaml")).read_text(encoding="utf-8")
    )
    mcp = map_mcp(doc["metadata"]["namespace"], doc["metadata"]["name"], doc["spec"])
    assert isinstance(mcp.source, VmcpProxySource)
    assert mcp.source.peer.as_str() == "team-a/code"
    assert mcp.source.cluster_url() == "http://code.team-a.svc:8080/mcp-proxy"
    assert mcp.forward_identity is True
    crd = mcp_to_crd(mcp)
    assert crd["spec"]["source"]["type"] == "VmcpProxy"
    assert crd["spec"]["source"]["peerGatewayRef"]["name"] == "code"
    public = mcp_to_public_dict(mcp)
    assert public["source"]["clusterUrl"].endswith("/mcp-proxy")


def test_map_vmcp_proxy_requires_peer_and_serializes_bearer() -> None:
    with pytest.raises(ValueError, match="peerGatewayRef"):
        map_mcp(
            "team-a",
            "x",
            {
                "gatewayRef": {"name": "main"},
                "source": {"type": "VmcpProxy"},
            },
        )
    mcp = map_mcp(
        "team-a",
        "code-peer",
        {
            "gatewayRef": {"name": "main"},
            "source": {
                "type": "VmcpProxy",
                "peerGatewayRef": {"name": "code", "namespace": "team-b"},
                "path": "custom",
                "port": 9090,
                "bearerSecretRef": {"name": "peer-tok", "key": "token"},
            },
        },
    )
    assert isinstance(mcp.source, VmcpProxySource)
    assert mcp.source.peer.as_str() == "team-b/code"
    assert mcp.source.cluster_url() == "http://code.team-b.svc:9090/custom"
    crd = mcp_to_crd(mcp)
    assert crd["spec"]["source"]["peerGatewayRef"]["namespace"] == "team-b"
    assert crd["spec"]["source"]["bearerSecretRef"]["name"] == "peer-tok"
    public = mcp_to_public_dict(mcp)
    assert public["source"]["bearerSecretRef"]["name"] == "peer-tok"


@pytest.mark.asyncio
async def test_reconcile_vmcp_proxy_upstream() -> None:
    main = _gw("main")
    mcp = McpServerDesired(
        namespace="team-a",
        name="code-peer",
        gateway_key=main.key,
        enabled=True,
        description="peer",
        source=VmcpProxySource(
            peer=GatewayKey(namespace="team-a", name="code"),
            bearer_secret_ref=SecretRef(name="peer-tok"),
        ),
        forward_identity=True,
    )
    bundle = await ReconcileGatewayArtifacts(
        renderer=RegistryEngine(), skill_loader=FakeSkills()
    ).execute(main, [mcp])
    registry = bundle.files["registry.json"].data
    assert "http://code.team-a.svc:8080/mcp-proxy" in registry
    assert '"forward_identity": true' in registry
    assert "VMCP_BEARER_CODE_PEER" in registry
    assert RenderMcpManifests().execute(main, mcp) == []
    manifests = RenderGatewayManifests().execute(main, bundle, [mcp])
    deploy = next(m for m in manifests if m.get("kind") == "Deployment")
    env_names = {e["name"] for e in deploy["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert "VMCP_BEARER_CODE_PEER" in env_names


@pytest.mark.asyncio
async def test_add_vmcp_proxy_requires_peer_proxy_enabled() -> None:
    main = _gw("main")
    code = _gw("code", proxy=True, path="/custom-proxy")
    no_proxy = _gw("other")
    cp = build_control_plane(
        gateways=FakeGateways([main, code, no_proxy]),
        catalog=InMemoryMcpCatalog(),
    )
    desired = mcp_from_add_body(
        main.key,
        "code-peer",
        {"source": {"type": "VmcpProxy", "peerGateway": "team-a/code"}},
    )
    added = await cp.add_mcp.execute(desired)
    assert isinstance(added.mcp.source, VmcpProxySource)
    # Inherits peer proxy path when default /mcp-proxy was supplied.
    assert added.mcp.source.path == "/custom-proxy"
    assert added.mcp.source.cluster_url() == "http://code.team-a.svc:8080/custom-proxy"

    nl = await cp.nl_crud.execute(
        cp.nl_crud.parse(
            "подключи mcp other-peer к team-a/main через vmcp-proxy team-a/code"
        )
    )
    assert nl.mcp is not None
    assert isinstance(nl.mcp.source, VmcpProxySource)

    with pytest.raises(ValueError, match=r"proxy\.enabled"):
        await cp.add_mcp.execute(
            mcp_from_add_body(
                main.key,
                "broken",
                {
                    "source": {
                        "type": "VmcpProxy",
                        "peerGatewayRef": {"name": "other"},
                    }
                },
            )
        )

    with pytest.raises(ValueError, match="itself"):
        await cp.add_mcp.execute(
            McpServerDesired(
                namespace="team-a",
                name="loop",
                gateway_key=main.key,
                enabled=True,
                description=None,
                source=VmcpProxySource(peer=main.key),
            )
        )

    with pytest.raises(LookupError, match="peer gateway"):
        await cp.add_mcp.execute(
            mcp_from_add_body(
                main.key,
                "missing-peer",
                {
                    "source": {
                        "type": "VmcpProxy",
                        "peerGatewayRef": {"name": "nope"},
                    }
                },
            )
        )


@pytest.mark.asyncio
async def test_mcp_from_add_body_vmcp_proxy_edges() -> None:
    key = GatewayKey(namespace="team-a", name="main")
    with pytest.raises(ValueError, match="peerGatewayRef"):
        mcp_from_add_body(key, "x", {"source": {"type": "VmcpProxy"}})
    mcp = mcp_from_add_body(
        key,
        "peer",
        {
            "source": {
                "type": "VmcpProxy",
                "peerGatewayRef": {"name": "code"},
                "path": "/p",
                "port": 1,
            }
        },
    )
    assert isinstance(mcp.source, VmcpProxySource)
    assert mcp.source.port == 1
    patched = apply_mcp_fields(mcp, {"path": "/other"})
    assert isinstance(patched.source, VmcpProxySource)
    assert patched.source.path == "/other"
    with pytest.raises(ValueError, match="path"):
        apply_mcp_fields(mcp, {"path": "  "})

    cp = build_control_plane(
        gateways=FakeGateways([_gw("main"), _gw("code", proxy=True)]),
        catalog=InMemoryMcpCatalog(),
    )
    with pytest.raises(ValueError, match="path"):
        await cp.add_mcp.execute(
            McpServerDesired(
                namespace="team-a",
                name="bad-path",
                gateway_key=key,
                enabled=True,
                description=None,
                source=VmcpProxySource(
                    peer=GatewayKey(namespace="team-a", name="code"),
                    path=" ",
                ),
            )
        )
    with pytest.raises(ValueError, match="port"):
        await cp.add_mcp.execute(
            McpServerDesired(
                namespace="team-a",
                name="bad-port",
                gateway_key=key,
                enabled=True,
                description=None,
                source=VmcpProxySource(
                    peer=GatewayKey(namespace="team-a", name="code"),
                    port=0,
                ),
            )
        )


def test_nl_parse_vmcp_proxy_en() -> None:
    cp = build_control_plane(
        gateways=FakeGateways([_gw("main"), _gw("code", proxy=True)]),
        catalog=InMemoryMcpCatalog(),
    )
    intent = cp.nl_crud.parse(
        "add mcp code-peer to team-a/main via vmcp-proxy team-a/code forward identity"
    )
    assert intent.fields is not None
    assert intent.fields["source"]["type"] == "VmcpProxy"
    assert intent.fields["forwardIdentity"] is True
    intent_fi = cp.nl_crud.parse(
        "add mcp p to team-a/main via vmcp-proxy team-a/code forwardIdentity=true "
        "description x"
    )
    assert intent_fi.fields is not None
    assert intent_fi.fields["forwardIdentity"] is True
    assert intent_fi.fields["description"] == "x"


@pytest.mark.asyncio
async def test_reconcile_rejects_self_peer() -> None:
    main = _gw("main", proxy=True)
    mcp = McpServerDesired(
        namespace="team-a",
        name="loop",
        gateway_key=main.key,
        enabled=True,
        description=None,
        source=VmcpProxySource(peer=main.key),
    )
    with pytest.raises(ValueError, match="itself"):
        await ReconcileGatewayArtifacts(
            renderer=RegistryEngine(), skill_loader=FakeSkills()
        ).execute(main, [mcp])
