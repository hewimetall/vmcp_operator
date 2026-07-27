from __future__ import annotations

import pytest

from vmcp_operator.adapters.driven.k8s.ssa import InMemoryApplier, ServerSideApply
from vmcp_operator.adapters.driving.k8s import handlers
from vmcp_operator.adapters.driving.k8s.reconcile import McpReconcile
from vmcp_operator.adapters.driving.k8s.runtime import (
    EmptySkillLoader,
    OperatorRuntime,
    get_runtime,
    set_runtime,
)
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.models.mcp import (
    ContainerImageSource,
    McpEndpoint,
    McpServerDesired,
    NamedPort,
    RemoteHttpSource,
)
from vmcp_operator.domain.usecases.render_mcp_manifests import RenderMcpManifests


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
    )


def _gateway_spec() -> dict:
    return {
        "image": "harbor.example.com/ai/vmcp:1",
        "adminTokenSecretRef": {"name": "tokens"},
        "masterPasswordSecretRef": {"name": "pass", "key": "password"},
        "publicRoute": {
            "hostname": "main.example.com",
            "gatewayRef": {"name": "kgateway"},
        },
    }


@pytest.fixture
def runtime():
    gw = _gateway()
    mcp = McpServerDesired(
        namespace="team-a",
        name="docs",
        gateway_key=gw.key,
        enabled=True,
        description=None,
        source=RemoteHttpSource(url="https://docs.example/mcp"),
    )
    rt = OperatorRuntime.in_memory(
        gateways={gw.key.as_str(): gw},
        mcps={gw.key.as_str(): [mcp]},
    )
    set_runtime(rt)
    yield rt
    set_runtime(None)


@pytest.mark.asyncio
async def test_gateway_delete_blocked_while_children_remain(runtime: OperatorRuntime) -> None:
    result = await handlers.reconcile_gateway(
        namespace="team-a",
        name="main",
        spec=_gateway_spec(),
        meta={
            "deletionTimestamp": "2026-01-01T00:00:00Z",
            "finalizers": ["vmcp.io/gateway-protection"],
        },
    )
    assert result["phase"] == "Deleting"


@pytest.mark.asyncio
async def test_gateway_finalize_when_no_children() -> None:
    gw = _gateway()
    rt = OperatorRuntime.in_memory(gateways={gw.key.as_str(): gw}, mcps={})
    set_runtime(rt)
    try:
        result = await handlers.reconcile_gateway(
            namespace="team-a",
            name="main",
            spec=_gateway_spec(),
            meta={
                "deletionTimestamp": "2026-01-01T00:00:00Z",
                "finalizers": ["vmcp.io/gateway-protection"],
            },
        )
        assert result["phase"] == "Finalized"
        assert "vmcp.io/gateway-protection" in result["removeFinalizers"]
    finally:
        set_runtime(None)


@pytest.mark.asyncio
async def test_mcp_pending_gateway_and_immutable(runtime: OperatorRuntime) -> None:
    set_runtime(
        OperatorRuntime.in_memory(
            gateways={},
            mcps={},
        )
    )
    try:
        result = await handlers.reconcile_mcp(
            namespace="team-a",
            name="docs",
            spec={
                "gatewayRef": {"name": "main"},
                "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
            },
            meta={},
        )
        assert result["phase"] == "PendingGateway"
    finally:
        set_runtime(runtime)

    result = await handlers.reconcile_mcp(
        namespace="team-a",
        name="docs",
        spec={
            "gatewayRef": {"name": "other"},
            "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
        },
        meta={},
        old={
            "spec": {
                "gatewayRef": {"name": "main"},
                "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
            }
        },
    )
    assert result["phase"] == "Invalid"


@pytest.mark.asyncio
async def test_mcp_finalize_on_delete(runtime: OperatorRuntime) -> None:
    result = await handlers.reconcile_mcp(
        namespace="team-a",
        name="docs",
        spec={
            "gatewayRef": {"name": "main"},
            "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
        },
        meta={
            "deletionTimestamp": "2026-01-01T00:00:00Z",
            "finalizers": ["vmcp.io/unregister-before-gc"],
        },
    )
    assert result["phase"] == "Finalized"
    assert "team-a/main" in runtime.pending


@pytest.mark.asyncio
async def test_empty_skill_loader_and_default_runtime() -> None:
    set_runtime(None)
    loader = EmptySkillLoader()
    skills = await loader.load_skills(_gateway(), [])
    assert skills == []
    rt = get_runtime()
    assert isinstance(rt, OperatorRuntime)
    set_runtime(None)


@pytest.mark.asyncio
async def test_mcp_reconcile_applies_container_workload() -> None:
    gw = _gateway()
    mcp = McpServerDesired(
        namespace="team-a",
        name="architect-c4",
        gateway_key=gw.key,
        enabled=True,
        description=None,
        source=ContainerImageSource(
            image="harbor.example.com/ai/architect-c4:1",
            ports=(NamedPort(name="http", container_port=8766),),
            mcp_endpoint=McpEndpoint(port_name="http"),
        ),
    )
    applier = InMemoryApplier()
    result = await McpReconcile(
        manifests=RenderMcpManifests(),
        apply=ServerSideApply(applier=applier),
    ).execute(gw, mcp)
    assert result["phase"] == "Applied"
    assert result["objects"] == 2
