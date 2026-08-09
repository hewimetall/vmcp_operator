from __future__ import annotations

import pytest

from fake_patch import FakePatch
from vmcp_operator.adapters.driven.k8s.ssa import InMemoryApplier, ServerSideApply
from vmcp_operator.adapters.driving.k8s import handlers
from vmcp_operator.adapters.driving.k8s.finalizer_patch import apply_fns_to_body
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
    patch = FakePatch()
    await handlers.reconcile_gateway(
        namespace="team-a",
        name="main",
        spec=_gateway_spec(),
        meta={
            "uid": "gw-1",
            "generation": 1,
            "deletionTimestamp": "2026-01-01T00:00:00Z",
            "finalizers": ["vmcp.io/gateway-protection"],
        },
        patch=patch,
    )
    assert patch.status["phase"] == "Deleting"
    assert patch.fns == []


@pytest.mark.asyncio
async def test_gateway_finalize_when_no_children() -> None:
    gw = _gateway()
    rt = OperatorRuntime.in_memory(gateways={gw.key.as_str(): gw}, mcps={})
    set_runtime(rt)
    try:
        patch = FakePatch()
        await handlers.reconcile_gateway(
            namespace="team-a",
            name="main",
            spec=_gateway_spec(),
            meta={
                "uid": "gw-1",
                "generation": 1,
                "deletionTimestamp": "2026-01-01T00:00:00Z",
                "finalizers": ["vmcp.io/gateway-protection"],
            },
            patch=patch,
        )
        assert patch.status["phase"] == "Finalized"
        body: dict = {"metadata": {"finalizers": ["vmcp.io/gateway-protection"]}}
        apply_fns_to_body(patch.fns, body)
        assert body["metadata"]["finalizers"] == []
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
        patch = FakePatch()
        await handlers.reconcile_mcp(
            namespace="team-a",
            name="docs",
            spec={
                "gatewayRef": {"name": "main"},
                "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
            },
            meta={"uid": "mcp-1", "generation": 1},
            patch=patch,
        )
        assert patch.status["phase"] == "PendingGateway"
    finally:
        set_runtime(runtime)

    patch = FakePatch()
    await handlers.reconcile_mcp(
        namespace="team-a",
        name="docs",
        spec={
            "gatewayRef": {"name": "other"},
            "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
        },
        meta={"uid": "mcp-1", "generation": 1},
        patch=patch,
        old={
            "spec": {
                "gatewayRef": {"name": "main"},
                "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
            }
        },
    )
    assert patch.status["phase"] == "Invalid"


@pytest.mark.asyncio
async def test_mcp_finalize_on_delete(runtime: OperatorRuntime) -> None:
    patch = FakePatch()
    await handlers.reconcile_mcp(
        namespace="team-a",
        name="docs",
        spec={
            "gatewayRef": {"name": "main"},
            "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
        },
        meta={
            "uid": "mcp-1",
            "generation": 1,
            "deletionTimestamp": "2026-01-01T00:00:00Z",
            "finalizers": ["vmcp.io/unregister-before-gc"],
        },
        patch=patch,
    )
    assert patch.status["phase"] == "Finalized"
    assert "team-a/main" in runtime.pending
    assert "team-a/main" in runtime.toucher.touches  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_mcp_delete_blocks_when_unregister_fails(runtime: OperatorRuntime) -> None:
    async def _fail(key, name: str) -> bool:
        return False

    runtime.unregister_upstream = _fail
    patch = FakePatch()
    await handlers.reconcile_mcp(
        namespace="team-a",
        name="docs",
        spec={
            "gatewayRef": {"name": "main"},
            "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
        },
        meta={
            "uid": "mcp-1",
            "generation": 1,
            "deletionTimestamp": "2026-01-01T00:00:00Z",
            "finalizers": ["vmcp.io/unregister-before-gc"],
        },
        patch=patch,
    )
    assert patch.status["phase"] == "Deleting"


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
    owner = {
        "apiVersion": "vmcp.io/v1alpha1",
        "kind": "VmcpMcpServer",
        "metadata": {"name": "architect-c4", "namespace": "team-a", "uid": "mcp-uid"},
    }
    result = await McpReconcile(
        manifests=RenderMcpManifests(),
        apply=ServerSideApply(applier=applier),
    ).execute(gw, mcp, owner=owner)
    assert result["phase"] == "Applied"
    assert result["objects"] == 2
    for item in applier.applied:
        refs = item["body"]["metadata"]["ownerReferences"]
        assert refs[0]["uid"] == "mcp-uid"
