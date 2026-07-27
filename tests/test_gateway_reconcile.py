from __future__ import annotations

import pytest

from vmcp_operator.adapters.driven.k8s.ssa import InMemoryApplier, ServerSideApply
from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.adapters.driving.k8s.reconcile import GatewayReconcile
from vmcp_operator.domain.models.artifacts import SkillDesired
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.models.mcp import McpServerDesired, RemoteHttpSource
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests


class FakeSkills:
    async def load_skills(self, gateway, mcps) -> list[SkillDesired]:
        return [
            SkillDesired(name="research_docs", description="d", template="t"),
        ]


@pytest.mark.asyncio
async def test_gateway_reconcile_applies_manifest_set() -> None:
    gateway = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )
    mcps = [
        McpServerDesired(
            namespace="team-a",
            name="context7",
            gateway_key=gateway.key,
            enabled=True,
            description="docs",
            source=RemoteHttpSource(url="https://context7.example/mcp"),
        )
    ]
    applier = InMemoryApplier()
    result = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(),
            skill_loader=FakeSkills(),
        ),
        manifests=RenderGatewayManifests(),
        apply=ServerSideApply(applier=applier),
    ).execute(gateway, mcps)
    assert result["phase"] == "Applied"
    assert result["objects"] == 5
    assert applier.applied is not None
    assert len(applier.applied) == 5
    kinds = [item["body"]["kind"] for item in applier.applied]
    assert kinds == [
        "PersistentVolumeClaim",
        "ConfigMap",
        "Service",
        "Deployment",
        "HTTPRoute",
    ]
