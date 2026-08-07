"""Aggregate Gateway MCP desired state into one atomic artifact bundle."""

from __future__ import annotations

from dataclasses import dataclass

from vmcp_operator.domain.models.artifacts import (
    ArtifactBundle,
    ToolOverrideArtifact,
    UpstreamArtifactsDesired,
    UpstreamDesired,
)
from vmcp_operator.domain.models.gateway import GatewayDesired
from vmcp_operator.domain.models.mcp import (
    ContainerImageSource,
    McpServerDesired,
    RemoteHttpSource,
    VmcpProxySource,
)
from vmcp_operator.domain.ports import ArtifactRenderer, SkillLoader


@dataclass(frozen=True, slots=True)
class ReconcileGatewayArtifacts:
    renderer: ArtifactRenderer
    skill_loader: SkillLoader

    async def execute(
        self,
        gateway: GatewayDesired,
        mcps: list[McpServerDesired],
    ) -> ArtifactBundle:
        enabled = [m for m in mcps if m.enabled and m.gateway_key == gateway.key]
        upstreams: list[UpstreamArtifactsDesired] = []
        for mcp in sorted(enabled, key=lambda item: item.name):
            upstreams.append(
                UpstreamArtifactsDesired(
                    upstream=_to_upstream(gateway, mcp),
                    tool_overrides=tuple(
                        ToolOverrideArtifact(
                            name=ov.name,
                            read_only=ov.read_only,
                            task_support=ov.task_support,
                        )
                        for ov in mcp.tool_overrides
                    ),
                )
            )
        skills = await self.skill_loader.load_skills(gateway, enabled)
        return self.renderer.render_bundle(upstreams, skills)


def _to_upstream(gateway: GatewayDesired, mcp: McpServerDesired) -> UpstreamDesired:
    source = mcp.source
    if isinstance(source, RemoteHttpSource):
        bearer_env = None
        if source.bearer_secret_ref is not None:
            bearer_env = f"VMCP_BEARER_{mcp.name.upper().replace('-', '_')}"
        return UpstreamDesired(
            name=mcp.name,
            url=source.url,
            bearer_env=bearer_env,
            description=mcp.description,
            enabled=True,
            forward_identity=mcp.forward_identity,
        )
    if isinstance(source, VmcpProxySource):
        if source.peer == gateway.key:
            msg = f"mcp `{mcp.name}` cannot peer a gateway to itself via VmcpProxy"
            raise ValueError(msg)
        bearer_env = None
        if source.bearer_secret_ref is not None:
            bearer_env = f"VMCP_BEARER_{mcp.name.upper().replace('-', '_')}"
        return UpstreamDesired(
            name=mcp.name,
            url=source.cluster_url(),
            bearer_env=bearer_env,
            description=mcp.description,
            enabled=True,
            forward_identity=mcp.forward_identity,
        )
    if isinstance(source, ContainerImageSource):
        port = next(
            (p for p in source.ports if p.name == source.mcp_endpoint.port_name),
            None,
        )
        if port is None:
            msg = f"mcp `{mcp.name}` mcpEndpoint.portName not found in ports"
            raise ValueError(msg)
        url = (
            f"http://{gateway.key.name}-{mcp.name}.{gateway.key.namespace}"
            f".svc:{port.container_port}{source.mcp_endpoint.path}"
        )
        return UpstreamDesired(
            name=mcp.name,
            url=url,
            description=mcp.description,
            enabled=True,
            forward_identity=mcp.forward_identity,
        )
    msg = f"unsupported source for mcp `{mcp.name}`"
    raise TypeError(msg)
