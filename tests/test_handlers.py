from __future__ import annotations

from types import SimpleNamespace

import pytest

from fake_patch import FakePatch
from vmcp_operator.adapters.driving.k8s import handlers
from vmcp_operator.adapters.driving.k8s.finalizer_patch import apply_fns_to_body
from vmcp_operator.adapters.driving.k8s.runtime import OperatorRuntime, set_runtime
from vmcp_operator.domain.models.artifacts import SkillDesired
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.models.mcp import McpServerDesired, RemoteHttpSource


class FakeSkills:
    async def load_skills(self, gateway, mcps) -> list[SkillDesired]:
        return [SkillDesired(name="research_docs", description="d", template="t")]


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


def _mcp_spec() -> dict:
    return {
        "gatewayRef": {"name": "main"},
        "source": {"type": "RemoteHttp", "url": "https://docs.example/mcp"},
    }


def _meta(**extra: object) -> dict:
    base = {"uid": "gw-uid-1", "generation": 3}
    base.update(extra)
    return base


@pytest.fixture
def runtime():
    gw = _gateway()
    mcp = McpServerDesired(
        namespace="team-a",
        name="docs",
        gateway_key=gw.key,
        enabled=True,
        description="docs",
        source=RemoteHttpSource(url="https://docs.example/mcp"),
    )
    rt = OperatorRuntime.in_memory(
        gateways={gw.key.as_str(): gw},
        mcps={gw.key.as_str(): [mcp]},
        skill_loader=FakeSkills(),
    )
    set_runtime(rt)
    yield rt
    set_runtime(None)


@pytest.mark.asyncio
async def test_configure_startup_settings() -> None:
    settings = SimpleNamespace(
        posting=SimpleNamespace(enabled=False),
        watching=SimpleNamespace(server_timeout=0),
    )
    await handlers.configure(settings)
    assert settings.posting.enabled is True
    assert settings.watching.server_timeout == 60


@pytest.mark.asyncio
async def test_reconcile_gateway_applies_bundle(runtime: OperatorRuntime) -> None:
    patch = FakePatch()
    result = await handlers.reconcile_gateway(
        namespace="team-a",
        name="main",
        spec=_gateway_spec(),
        meta=_meta(),
        patch=patch,
        body={
            "apiVersion": "vmcp.io/v1alpha1",
            "kind": "VmcpGateway",
            "metadata": _meta(),
        },
    )
    assert result is None
    assert patch.status["phase"] == "Applied"
    assert patch.status["observedGeneration"] == 3
    assert patch.status["artifactSha256"]
    body: dict = {"metadata": {"finalizers": []}}
    apply_fns_to_body(patch.fns, body)
    assert "vmcp.io/gateway-protection" in body["metadata"]["finalizers"]
    applied = runtime.applier.applied  # type: ignore[attr-defined]
    assert applied
    for item in applied:
        refs = item["body"]["metadata"].get("ownerReferences") or []
        assert refs
        assert refs[0]["uid"] == "gw-uid-1"
        assert refs[0]["kind"] == "VmcpGateway"


@pytest.mark.asyncio
async def test_reconcile_mcp_updates_gateway_aggregate(runtime: OperatorRuntime) -> None:
    patch = FakePatch()
    result = await handlers.reconcile_mcp(
        namespace="team-a",
        name="docs",
        spec=_mcp_spec(),
        meta={"uid": "mcp-uid-1", "generation": 2},
        patch=patch,
        body={
            "apiVersion": "vmcp.io/v1alpha1",
            "kind": "VmcpMcpServer",
            "metadata": {"uid": "mcp-uid-1", "generation": 2},
        },
    )
    assert result is None
    assert patch.status["phase"] in {"Applied", "Registered"}
    body: dict = {"metadata": {"finalizers": []}}
    apply_fns_to_body(patch.fns, body)
    assert "vmcp.io/unregister-before-gc" in body["metadata"]["finalizers"]
    assert "team-a/main" in runtime.toucher.touches  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_immutable_gateway_storage_class_rejected(runtime: OperatorRuntime) -> None:
    patch = FakePatch()
    await handlers.reconcile_gateway(
        namespace="team-a",
        name="main",
        spec={
            **_gateway_spec(),
            "persistence": {"storageClassName": "fast", "size": "5Gi"},
        },
        meta=_meta(),
        patch=patch,
        old={
            "spec": {
                **_gateway_spec(),
                "persistence": {"storageClassName": "slow", "size": "5Gi"},
            }
        },
    )
    assert patch.status["phase"] == "Invalid"
    assert patch.status["conditions"][0]["reason"] == "ImmutableField"


@pytest.mark.asyncio
async def test_reconcile_gateway_skips_finalizer_add_when_present(
    runtime: OperatorRuntime,
) -> None:
    patch = FakePatch()
    await handlers.reconcile_gateway(
        namespace="team-a",
        name="main",
        spec=_gateway_spec(),
        meta=_meta(finalizers=["vmcp.io/gateway-protection"]),
        patch=patch,
        body={
            "apiVersion": "vmcp.io/v1alpha1",
            "kind": "VmcpGateway",
            "metadata": _meta(finalizers=["vmcp.io/gateway-protection"]),
        },
    )
    assert patch.status["phase"] == "Applied"
    assert patch.fns == []


@pytest.mark.asyncio
async def test_reconcile_mcp_skips_finalizer_add_when_present(
    runtime: OperatorRuntime,
) -> None:
    patch = FakePatch()
    await handlers.reconcile_mcp(
        namespace="team-a",
        name="docs",
        spec=_mcp_spec(),
        meta={"uid": "mcp-uid-1", "generation": 2, "finalizers": ["vmcp.io/unregister-before-gc"]},
        patch=patch,
        body={
            "apiVersion": "vmcp.io/v1alpha1",
            "kind": "VmcpMcpServer",
            "metadata": {
                "uid": "mcp-uid-1",
                "generation": 2,
                "finalizers": ["vmcp.io/unregister-before-gc"],
            },
        },
    )
    assert patch.status["phase"] in {"Applied", "Registered"}
    assert patch.fns == []


@pytest.mark.asyncio
async def test_reconcile_gateway_without_uid_skips_owner(runtime: OperatorRuntime) -> None:
    patch = FakePatch()
    await handlers.reconcile_gateway(
        namespace="team-a",
        name="main",
        spec=_gateway_spec(),
        meta={"generation": 1},  # no uid
        patch=patch,
    )
    assert patch.status["phase"] == "Applied"
    for item in runtime.applier.applied:  # type: ignore[attr-defined]
        assert "ownerReferences" not in item["body"].get("metadata", {})


@pytest.mark.asyncio
async def test_child_event_enqueues_gateway(runtime: OperatorRuntime) -> None:
    await handlers.enqueue_from_child(
        namespace="team-a",
        name="main",
        body={
            "metadata": {
                "namespace": "team-a",
                "name": "main",
                "labels": {"vmcp.io/gateway": "main"},
            }
        },
    )
    assert "team-a/main" in runtime.pending


@pytest.mark.asyncio
async def test_child_event_without_gateway_label_is_ignored(
    runtime: OperatorRuntime,
) -> None:
    await handlers.enqueue_from_child(
        namespace="team-a",
        name="orphan",
        body={"metadata": {"namespace": "team-a", "name": "orphan", "labels": {}}},
    )
    assert runtime.pending == set()
