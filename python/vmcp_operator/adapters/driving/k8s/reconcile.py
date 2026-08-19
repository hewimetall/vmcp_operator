"""Compose domain use cases for Gateway and MCP reconcile passes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from vmcp_operator.adapters.driven.k8s.ssa import ServerSideApply
from vmcp_operator.adapters.driving.k8s.ownership import attach_owner
from vmcp_operator.domain.models.artifacts import SkillDesired
from vmcp_operator.domain.models.gateway import GatewayDesired
from vmcp_operator.domain.models.mcp import McpServerDesired
from vmcp_operator.domain.ports.secrets import SecretValueLoader
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import (
    RenderGatewayManifests,
    plan_early_identity_strip,
    wants_hop_inject,
)
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
        *,
        owner: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        del skills
        bundle = await self.artifacts.execute(gateway, mcps)
        hop_value = await self._load_hop_secret(gateway)
        objects = self.manifests.execute(
            gateway, bundle, mcps, forward_auth_header_value=hop_value
        )
        strip = plan_early_identity_strip(gateway)
        for obj in (*objects, *strip.objects):
            if owner is not None:
                attach_owner(obj, owner)
            await self.apply.apply(obj)
        for attachment in gateway.attachments:
            body = _materialize_attachment(attachment, gateway)
            if owner is not None:
                attach_owner(body, owner)
            await self.apply.apply(body)
        return {
            "phase": "Applied",
            "gateway": gateway.key.as_str(),
            "bundleSha256": bundle.bundle_sha256,
            "objects": len(objects) + len(strip.objects) + len(gateway.attachments),
            "adminHopHeaderInjected": bool(hop_value)
            and _wants_admin_hop_inject(gateway),
            "listenerPolicy": strip.phase,
            "listenerPolicyMessage": strip.message,
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
    """True when any managed admin/extra HTTPRoute should set the hop header."""
    routes = []
    if gateway.admin_route is not None:
        routes.append(gateway.admin_route)
    routes.extend(gateway.extra_routes)
    return any(route.manage and wants_hop_inject(route, gateway) for route in routes)


def _materialize_attachment(
    attachment: Mapping[str, Any], gateway: GatewayDesired
) -> dict[str, Any]:
    """Copy an opaque attachment and force namespace + gateway label."""
    import copy

    body = copy.deepcopy(dict(attachment))
    meta = body.setdefault("metadata", {})
    meta["namespace"] = gateway.key.namespace
    labels = dict(meta.get("labels") or {})
    labels.setdefault("vmcp.io/gateway", gateway.key.name)
    meta["labels"] = labels
    if not body.get("apiVersion") or not body.get("kind") or not meta.get("name"):
        raise ValueError("attachment requires apiVersion, kind, and metadata.name")
    return body


@dataclass(frozen=True, slots=True)
class McpReconcile:
    manifests: RenderMcpManifests
    apply: ServerSideApply

    async def execute(
        self,
        gateway: GatewayDesired,
        mcp: McpServerDesired,
        *,
        owner: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        objects = self.manifests.execute(gateway, mcp)
        for obj in objects:
            if owner is not None:
                attach_owner(obj, owner)
            await self.apply.apply(obj)
        return {
            "phase": "Applied" if objects else "Registered",
            "gateway": gateway.key.as_str(),
            "mcp": mcp.name,
            "objects": len(objects),
        }
