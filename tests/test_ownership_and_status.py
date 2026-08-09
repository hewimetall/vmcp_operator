from __future__ import annotations

import pytest

from fake_patch import FakePatch
from vmcp_operator.adapters.driven.k8s.gateway_toucher import RecordingGatewayToucher
from vmcp_operator.adapters.driven.k8s.ssa import InMemoryApplier, ServerSideApply
from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.adapters.driving.k8s.finalizer_patch import (
    apply_fns_to_body,
    schedule_finalizer_adds,
    schedule_finalizer_removes,
)
from vmcp_operator.adapters.driving.k8s.ownership import attach_owner, build_owner_reference
from vmcp_operator.adapters.driving.k8s.reconcile import GatewayReconcile
from vmcp_operator.adapters.driving.k8s.runtime import EmptySkillLoader
from vmcp_operator.adapters.driving.k8s.status_patch import apply_status, generation_of
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests


def test_build_and_attach_owner_idempotent() -> None:
    owner = {
        "apiVersion": "vmcp.io/v1alpha1",
        "kind": "VmcpGateway",
        "metadata": {"name": "main", "namespace": "team-a", "uid": "u1"},
    }
    ref = build_owner_reference(owner)
    assert ref["controller"] is True
    obj: dict = {"metadata": {"name": "main"}}
    attach_owner(obj, owner)
    attach_owner(obj, owner)
    assert len(obj["metadata"]["ownerReferences"]) == 1
    assert obj["metadata"]["ownerReferences"][0]["uid"] == "u1"


def test_build_owner_requires_uid() -> None:
    with pytest.raises(ValueError):
        build_owner_reference({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "x"}})


def test_status_and_finalizer_patch_helpers() -> None:
    patch = FakePatch()
    apply_status(
        patch,
        phase="Applied",
        generation=4,
        artifact_sha256="abc",
        reason="Applied",
        message="ok",
    )
    assert patch.status["phase"] == "Applied"
    assert patch.status["observedGeneration"] == 4
    assert patch.status["artifactSha256"] == "abc"
    assert patch.status["conditions"][0]["type"] == "Ready"
    schedule_finalizer_adds(patch, ("vmcp.io/gateway-protection",))
    schedule_finalizer_removes(patch, ("vmcp.io/gateway-protection",))
    body: dict = {"metadata": {"finalizers": []}}
    apply_fns_to_body(patch.fns, body)
    assert body["metadata"]["finalizers"] == []
    assert generation_of({"generation": 9}) == 9
    assert generation_of({}, {"metadata": {"generation": 2}}) == 2
    assert generation_of(None, None) == 0

    # Plain-dict patch surface (no .status attribute).
    as_dict: dict = {}
    apply_status(as_dict, phase="Deleting", generation=None, ready=False)
    assert as_dict["status"]["phase"] == "Deleting"
    assert "observedGeneration" not in as_dict["status"]
    schedule_finalizer_adds(as_dict, ("f1",))
    schedule_finalizer_removes(as_dict, ("f1",))
    body2: dict = {"metadata": {"finalizers": ["f1"]}}
    apply_fns_to_body(as_dict["fns"], body2)
    assert body2["metadata"]["finalizers"] == []

    # ensure is idempotent when already present
    from vmcp_operator.adapters.driving.k8s.finalizer_patch import ensure_finalizer

    body3: dict = {"metadata": {"finalizers": ["keep"]}}
    ensure_finalizer("keep")(body3)
    assert body3["metadata"]["finalizers"] == ["keep"]

    with pytest.raises(TypeError):
        apply_status(object(), phase="x", generation=1)
    with pytest.raises(TypeError):
        schedule_finalizer_adds(object(), ("x",))

    class _BadStatus:
        status = "not-a-mapping"

    # Kopf-like object whose .status is not a mapping still returns it.
    from vmcp_operator.adapters.driving.k8s import status_patch as sp

    assert sp._status_mapping(_BadStatus()) == "not-a-mapping"

    bad: dict = {"status": []}
    with pytest.raises(TypeError):
        apply_status(bad, phase="x", generation=1)
    bad_fns: dict = {"fns": "nope"}
    with pytest.raises(TypeError):
        schedule_finalizer_adds(bad_fns, ("x",))


@pytest.mark.asyncio
async def test_recording_toucher_and_gateway_attachments() -> None:
    toucher = RecordingGatewayToucher()
    await toucher.touch(GatewayKey(namespace="team-a", name="main"))
    assert toucher.touches == ["team-a/main"]

    gateway = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            manage=False,
        ),
        attachments=(
            {
                "apiVersion": "gateway.kgateway.dev/v1alpha1",
                "kind": "TrafficPolicy",
                "metadata": {"name": "main-extauth"},
                "spec": {"targetRefs": [{"kind": "HTTPRoute", "name": "byo"}]},
            },
        ),
    )
    applier = InMemoryApplier()
    owner = {
        "apiVersion": "vmcp.io/v1alpha1",
        "kind": "VmcpGateway",
        "metadata": {"name": "main", "namespace": "team-a", "uid": "gw"},
    }
    result = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(),
            skill_loader=EmptySkillLoader(),
        ),
        manifests=RenderGatewayManifests(),
        apply=ServerSideApply(applier=applier),
    ).execute(gateway, [], owner=owner)
    assert result["phase"] == "Applied"
    # PVC+CM+Svc+Deploy + attachment; no public HTTPRoute (manage=false)
    kinds = [item["body"]["kind"] for item in applier.applied]
    assert "HTTPRoute" not in kinds
    assert "TrafficPolicy" in kinds
    policy = next(item["body"] for item in applier.applied if item["body"]["kind"] == "TrafficPolicy")
    assert policy["metadata"]["ownerReferences"][0]["uid"] == "gw"
    assert policy["metadata"]["labels"]["vmcp.io/gateway"] == "main"

    with pytest.raises(ValueError):
        await GatewayReconcile(
            artifacts=ReconcileGatewayArtifacts(
                renderer=RegistryEngine(),
                skill_loader=EmptySkillLoader(),
            ),
            manifests=RenderGatewayManifests(),
            apply=ServerSideApply(applier=InMemoryApplier()),
        ).execute(
            GatewayDesired(
                key=gateway.key,
                image=gateway.image,
                admin_token_secret_ref=gateway.admin_token_secret_ref,
                master_password_secret_ref=gateway.master_password_secret_ref,
                public_route=gateway.public_route,
                attachments=({"kind": "ConfigMap"},),
            ),
            [],
        )
