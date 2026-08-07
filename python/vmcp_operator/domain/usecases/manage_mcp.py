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
    NamedPort,
    RemoteHttpSource,
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
    if source_type == "RemoteHttp":
        url = str(source_raw.get("url") or body.get("url") or "").strip()
        if not url:
            raise ValueError("RemoteHttp source requires url")
        bearer = source_raw.get("bearerSecretRef") or body.get("bearerSecretRef")
        source: ContainerImageSource | RemoteHttpSource = RemoteHttpSource(
            url=url,
            bearer_secret_ref=(
                SecretRef(name=str(bearer["name"]), key=str(bearer.get("key", "token")))
                if bearer
                else None
            ),
        )
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
        if not isinstance(source, RemoteHttpSource):
            raise ValueError("bearerSecretRef can only be set on RemoteHttp sources")
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

    unknown = set(fields) - {
        "enabled",
        "description",
        "forwardIdentity",
        "url",
        "image",
        "bearerSecretRef",
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


async def _require_gateway(gateways: GatewayRepository, key: GatewayKey) -> None:
    if await gateways.get(key) is None:
        raise LookupError(f"gateway `{key.as_str()}` not found")
