"""Compose domain use cases for a Gateway reconcile pass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vmcp_operator.adapters.driven.k8s.ssa import ServerSideApply
from vmcp_operator.domain.models.artifacts import SkillDesired
from vmcp_operator.domain.models.gateway import GatewayDesired
from vmcp_operator.domain.models.mcp import McpServerDesired
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests


@dataclass(frozen=True, slots=True)
class GatewayReconcile:
    artifacts: ReconcileGatewayArtifacts
    manifests: RenderGatewayManifests
    apply: ServerSideApply

    async def execute(
        self,
        gateway: GatewayDesired,
        mcps: list[McpServerDesired],
        skills: list[SkillDesired] | None = None,
    ) -> dict[str, Any]:
        # SkillLoader is already inside artifacts; optional skills unused here.
        del skills
        bundle = await self.artifacts.execute(gateway, mcps)
        objects = self.manifests.execute(gateway, bundle)
        for obj in objects:
            await self.apply.apply(obj)
        return {
            "phase": "Applied",
            "gateway": gateway.key.as_str(),
            "bundleSha256": bundle.bundle_sha256,
            "objects": len(objects),
        }
