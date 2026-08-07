"""Compose domain use cases for Gateway and MCP reconcile passes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vmcp_operator.adapters.driven.k8s.ssa import ServerSideApply
from vmcp_operator.domain.models.artifacts import SkillDesired
from vmcp_operator.domain.models.gateway import GatewayDesired
from vmcp_operator.domain.models.mcp import McpServerDesired
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests
from vmcp_operator.domain.usecases.render_mcp_manifests import RenderMcpManifests


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
        del skills
        bundle = await self.artifacts.execute(gateway, mcps)
        objects = self.manifests.execute(gateway, bundle, mcps)
        for obj in objects:
            await self.apply.apply(obj)
        return {
            "phase": "Applied",
            "gateway": gateway.key.as_str(),
            "bundleSha256": bundle.bundle_sha256,
            "objects": len(objects),
        }


@dataclass(frozen=True, slots=True)
class McpReconcile:
    manifests: RenderMcpManifests
    apply: ServerSideApply

    async def execute(
        self,
        gateway: GatewayDesired,
        mcp: McpServerDesired,
    ) -> dict[str, Any]:
        objects = self.manifests.execute(gateway, mcp)
        for obj in objects:
            await self.apply.apply(obj)
        return {
            "phase": "Applied" if objects else "Registered",
            "gateway": gateway.key.as_str(),
            "mcp": mcp.name,
            "objects": len(objects),
        }
