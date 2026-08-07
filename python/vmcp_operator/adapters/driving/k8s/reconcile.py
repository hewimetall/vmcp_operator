"""Compose domain use cases for Gateway and MCP reconcile passes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vmcp_operator.adapters.driven.k8s.ssa import ServerSideApply
from vmcp_operator.domain.models.artifacts import SkillDesired
from vmcp_operator.domain.models.gateway import GatewayDesired
from vmcp_operator.domain.models.mcp import McpServerDesired
from vmcp_operator.domain.ports.secrets import SecretValueLoader
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests
from vmcp_operator.domain.usecases.render_mcp_manifests import RenderMcpManifests


@dataclass(frozen=True, slots=True)
class GatewayReconcile:
    artifacts: ReconcileGatewayArtifacts
    manifests: RenderGatewayManifests
    apply: ServerSideApply
    secrets: SecretValueLoader | None = None

    async def execute(
        self,
        gateway: GatewayDesired,
        mcps: list[McpServerDesired],
        skills: list[SkillDesired] | None = None,
    ) -> dict[str, Any]:
        del skills
        bundle = await self.artifacts.execute(gateway, mcps)
        hop_value = await self._load_hop_secret(gateway)
        objects = self.manifests.execute(
            gateway, bundle, mcps, forward_auth_header_value=hop_value
        )
        for obj in objects:
            await self.apply.apply(obj)
        return {
            "phase": "Applied",
            "gateway": gateway.key.as_str(),
            "bundleSha256": bundle.bundle_sha256,
            "objects": len(objects),
            "adminHopHeaderInjected": bool(hop_value)
            and _wants_admin_hop_inject(gateway),
        }

    async def _load_hop_secret(self, gateway: GatewayDesired) -> str | None:
        if self.secrets is None or not _wants_admin_hop_inject(gateway):
            return None
        ref = gateway.auth.authentik.forward_auth_secret_ref
        if ref is None:
            return None
        value = await self.secrets.get(gateway.key.namespace, ref)
        if value is None or not str(value).strip():
            return None
        return str(value)


def _wants_admin_hop_inject(gateway: GatewayDesired) -> bool:
    route = gateway.admin_route
    if route is None:
        return False
    want = route.inject_forward_auth_header
    if want is None:
        return gateway.auth.authentik.forward_auth_secret_ref is not None
    return want


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
