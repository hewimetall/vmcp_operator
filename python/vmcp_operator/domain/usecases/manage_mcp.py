"""Operator-level MCP catalog mutations (above per-instance vmcp CLI)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from vmcp_operator.domain.models.control_plane import McpMutation, McpWriteResult
from vmcp_operator.domain.models.gateway import GatewayKey, SecretRef
from vmcp_operator.domain.models.mcp import (
    ContainerImageSource,
    McpEndpoint,
    McpServerDesired,
    McpSource,
    NamedPort,
    RemoteHttpSource,
    VmcpProxySource,
)
from vmcp_operator.domain.ports import GatewayRepository, McpCatalog


class McpConflictError(RuntimeError):
    """Raised when add targets an existing MCP name."""


class McpNotFoundError(LookupError):
    """Raised when update/remove/get cannot find the MCP."""


@dataclass(frozen=True, slots=True)
class ListMcps:
    catalog: McpCatalog
    gateways: GatewayRepository

    async def execute(self, gateway: GatewayKey) -> list[McpServerDesired]:
        await _require_gateway(self.gateways, gateway)
        rows = await self.catalog.list_for_gateway(gateway)
        rows.sort(key=lambda item: item.name)
        return rows


@dataclass(frozen=True, slots=True)
class GetMcp:
    catalog: McpCatalog
    gateways: GatewayRepository

    async def execute(self, gateway: GatewayKey, name: str) -> McpServerDesired:
        await _require_gateway(self.gateways, gateway)
        mcp = await self.catalog.get(gateway.namespace, name)
        if mcp is None or mcp.gateway_key != gateway:
            raise McpNotFoundError(f"mcp `{gateway.namespace}/{name}` not found")
        return mcp


@dataclass(frozen=True, slots=True)
class AddMcp:
    catalog: McpCatalog
    gateways: GatewayRepository

    async def execute(self, mcp: McpServerDesired) -> McpWriteResult:
        _validate_mcp(mcp)
        await _require_gateway(self.gateways, mcp.gateway_key)
        mcp = await _resolve_vmcp_proxy(self.gateways, mcp)
        existing = await self.catalog.get(mcp.namespace, mcp.name)
        if existing is not None:
            raise McpConflictError(f"mcp `{mcp.namespace}/{mcp.name}` already exists")
        stored = await self.catalog.upsert(mcp)
        return McpWriteResult(mutation=McpMutation.ADD, mcp=stored, created=True)


@dataclass(frozen=True, slots=True)
class UpdateMcp:
    catalog: McpCatalog
    gateways: GatewayRepository

    async def execute(
        self,
        gateway: GatewayKey,
        name: str,
        *,
        fields: dict[str, Any],
    ) -> McpWriteResult:
        await _require_gateway(self.gateways, gateway)
        current = await self.catalog.get(gateway.namespace, name)
        if current is None or current.gateway_key != gateway:
            raise McpNotFoundError(f"mcp `{gateway.namespace}/{name}` not found")
        updated = apply_mcp_fields(current, fields)
        _validate_mcp(updated)
        updated = await _resolve_vmcp_proxy(self.gateways, updated)
        stored = await self.catalog.upsert(updated)
        return McpWriteResult(mutation=McpMutation.UPDATE, mcp=stored, created=False)


@dataclass(frozen=True, slots=True)
class RemoveMcp:
    catalog: McpCatalog
    gateways: GatewayRepository

    async def execute(self, gateway: GatewayKey, name: str) -> McpWriteResult:
        await _require_gateway(self.gateways, gateway)
        current = await self.catalog.get(gateway.namespace, name)
        if current is None or current.gateway_key != gateway:
            raise McpNotFoundError(f"mcp `{gateway.namespace}/{name}` not found")
        deleted = await self.catalog.delete(gateway.namespace, name)
        if not deleted:
            raise McpNotFoundError(f"mcp `{gateway.namespace}/{name}` not found")
        return McpWriteResult(mutation=McpMutation.REMOVE, mcp=current, created=False)


def mcp_from_add_body(gateway: GatewayKey, name: str, body: dict[str, Any]) -> McpServerDesired:
    """Build desired MCP from control-plane JSON (add)."""
    if not name or name != name.strip() or "/" in name or name != name.lower():
        raise ValueError("mcp name must be a lowercase DNS label without '/'")
    source_raw = body.get("source") or {}
    source_type = str(source_raw.get("type", "RemoteHttp"))
    bearer = source_raw.get("bearerSecretRef") or body.get("bearerSecretRef")
    bearer_ref = (
        SecretRef(name=str(bearer["name"]), key=str(bearer.get("key", "token")))
        if bearer
        else None
    )
    if source_type == "RemoteHttp":
        url = str(source_raw.get("url") or body.get("url") or "").strip()
        if not url:
            raise ValueError("RemoteHttp source requires url")
        source: McpSource = RemoteHttpSource(url=url, bearer_secret_ref=bearer_ref)
    elif source_type == "ContainerImage":
        image = str(source_raw.get("image") or body.get("image") or "").strip()
        if not image:
            raise ValueError("ContainerImage source requires image")
        ports_raw = source_raw.get("ports") or [{"name": "http", "containerPort": 8080}]
        ports = tuple(
            NamedPort(
                name=str(p["name"]),
                container_port=int(p["containerPort"]),
                protocol=str(p.get("protocol", "TCP")),
            )
            for p in ports_raw
        )
        endpoint = source_raw.get("mcpEndpoint") or {}
        source = ContainerImageSource(
            image=image,
            ports=ports,
            mcp_endpoint=McpEndpoint(
                port_name=str(endpoint.get("portName", "http")),
                path=str(endpoint.get("path", "/mcp")),
            ),
        )
    elif source_type == "VmcpProxy":
        peer_raw = source_raw.get("peerGatewayRef") or {}
        peer_name = str(
            peer_raw.get("name")
            or source_raw.get("peer")
            or source_raw.get("peerGateway")
            or body.get("peerGateway")
            or ""
        ).strip()
        if not peer_name:
            raise ValueError("VmcpProxy source requires peerGatewayRef.name")
        if "/" in peer_name:
            peer_ns, peer_name = peer_name.split("/", 1)
        else:
            peer_ns = str(peer_raw.get("namespace") or gateway.namespace)
        source = VmcpProxySource(
            peer=GatewayKey(namespace=peer_ns, name=peer_name),
            path=str(source_raw.get("path") or body.get("path") or "/mcp-proxy"),
            port=int(source_raw.get("port") or body.get("port") or 8080),
            bearer_secret_ref=bearer_ref,
        )
    else:
        raise ValueError(f"unsupported source.type `{source_type}`")

    return McpServerDesired(
        namespace=gateway.namespace,
        name=name,
        gateway_key=gateway,
        enabled=bool(body.get("enabled", True)),
        description=body.get("description"),
        source=source,
        forward_identity=bool(body.get("forwardIdentity", False)),
    )


def apply_mcp_fields(mcp: McpServerDesired, fields: dict[str, Any]) -> McpServerDesired:
    """Apply a sparse patch dict onto an existing MCP desired state."""
    if not fields:
        raise ValueError("update requires at least one field")
    enabled = mcp.enabled
    description = mcp.description
    forward_identity = mcp.forward_identity
    source = mcp.source

    if "enabled" in fields:
        enabled = bool(fields["enabled"])
    if "description" in fields:
        description = fields["description"]
    if "forwardIdentity" in fields:
        forward_identity = bool(fields["forwardIdentity"])
    if "url" in fields:
        if not isinstance(source, RemoteHttpSource):
            raise ValueError("url can only be set on RemoteHttp sources")
        url = str(fields["url"]).strip()
        if not url:
            raise ValueError("url must be non-empty")
        source = replace(source, url=url)
    if "image" in fields:
        if not isinstance(source, ContainerImageSource):
            raise ValueError("image can only be set on ContainerImage sources")
        image = str(fields["image"]).strip()
        if not image:
            raise ValueError("image must be non-empty")
        source = replace(source, image=image)
    if "bearerSecretRef" in fields:
        if not isinstance(source, (RemoteHttpSource, VmcpProxySource)):
            raise ValueError(
                "bearerSecretRef can only be set on RemoteHttp/VmcpProxy sources"
            )
        bearer = fields["bearerSecretRef"]
        if bearer is None:
            source = replace(source, bearer_secret_ref=None)
        else:
            source = replace(
                source,
                bearer_secret_ref=SecretRef(
                    name=str(bearer["name"]),
                    key=str(bearer.get("key", "token")),
                ),
            )
    if "path" in fields:
        if not isinstance(source, VmcpProxySource):
            raise ValueError("path can only be set on VmcpProxy sources")
        path = str(fields["path"]).strip()
        if not path:
            raise ValueError("path must be non-empty")
        source = replace(source, path=path)

    unknown = set(fields) - {
        "enabled",
        "description",
        "forwardIdentity",
        "url",
        "image",
        "bearerSecretRef",
        "path",
    }
    if unknown:
        raise ValueError(f"unsupported update fields: {sorted(unknown)}")

    return replace(
        mcp,
        enabled=enabled,
        description=description,
        forward_identity=forward_identity,
        source=source,
    )


def _validate_mcp(mcp: McpServerDesired) -> None:
    if mcp.gateway_key.namespace != mcp.namespace:
        raise ValueError("mcp must live in the same namespace as its gateway")
    if not mcp.name or mcp.name != mcp.name.strip():
        raise ValueError("mcp name must be non-empty")
    if isinstance(mcp.source, RemoteHttpSource) and not mcp.source.url.strip():
        raise ValueError("RemoteHttp url must be non-empty")
    if isinstance(mcp.source, ContainerImageSource) and not mcp.source.image.strip():
        raise ValueError("ContainerImage image must be non-empty")
    if isinstance(mcp.source, VmcpProxySource):
        if mcp.source.peer == mcp.gateway_key:
            raise ValueError("cannot attach a gateway to itself via VmcpProxy")
        if not mcp.source.path.strip():
            raise ValueError("VmcpProxy path must be non-empty")
        if mcp.source.port < 1 or mcp.source.port > 65535:
            raise ValueError("VmcpProxy port out of range")


async def _require_gateway(gateways: GatewayRepository, key: GatewayKey) -> None:
    if await gateways.get(key) is None:
        raise LookupError(f"gateway `{key.as_str()}` not found")


async def _resolve_vmcp_proxy(
    gateways: GatewayRepository, mcp: McpServerDesired
) -> McpServerDesired:
    """Validate peer Gateway and inherit proxy.path when still at default."""
    if not isinstance(mcp.source, VmcpProxySource):
        return mcp
    peer = await gateways.get(mcp.source.peer)
    if peer is None:
        raise LookupError(f"peer gateway `{mcp.source.peer.as_str()}` not found")
    if not peer.proxy.enabled:
        raise ValueError(
            f"peer gateway `{mcp.source.peer.as_str()}` must have proxy.enabled=true "
            "(vmcp-proxy surface)"
        )
    path = mcp.source.path
    # Inherit peer path when caller left the CRD/API default.
    if path in {"", "/mcp-proxy"} and peer.proxy.path:
        path = peer.proxy.path
    return replace(mcp, source=replace(mcp.source, path=path))
