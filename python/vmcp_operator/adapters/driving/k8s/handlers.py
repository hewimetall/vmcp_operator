"""Eager Kopf handlers for VmcpGateway / VmcpMcpServer."""

from __future__ import annotations

import logging
from typing import Any

import kopf

from vmcp_operator.adapters.driving.k8s.mapping import map_gateway, map_mcp
from vmcp_operator.domain.models.gateway import GatewayKey

LOGGER = logging.getLogger(__name__)

# Per-gateway serialization markers (in-process MVP, replicaCount=1).
# Keyed by event-loop id so unit tests do not reuse locks across loops.
_GATEWAY_LOCKS: dict[tuple[int, str], Any] = {}


def _lock_for(key: GatewayKey) -> Any:
    import asyncio

    loop = asyncio.get_running_loop()
    slot = (id(loop), key.as_str())
    lock = _GATEWAY_LOCKS.get(slot)
    if lock is None:
        lock = asyncio.Lock()
        _GATEWAY_LOCKS[slot] = lock
    return lock


@kopf.on.startup()
async def configure(settings: kopf.OperatorSettings, **_: Any) -> None:
    settings.posting.enabled = True
    settings.watching.server_timeout = 60


@kopf.on.create("vmcp.io", "v1alpha1", "vmcpgateways")
@kopf.on.update("vmcp.io", "v1alpha1", "vmcpgateways")
@kopf.on.resume("vmcp.io", "v1alpha1", "vmcpgateways")
async def reconcile_gateway(
    namespace: str,
    name: str,
    spec: dict[str, Any],
    **_: Any,
) -> dict[str, str]:
    gateway = map_gateway(namespace, name, spec)
    async with _lock_for(gateway.key):
        LOGGER.info("reconcile gateway %s image=%s", gateway.key.as_str(), gateway.image)
        return {"phase": "Observed", "gateway": gateway.key.as_str()}


@kopf.on.create("vmcp.io", "v1alpha1", "vmcpmcpservers")
@kopf.on.update("vmcp.io", "v1alpha1", "vmcpmcpservers")
@kopf.on.resume("vmcp.io", "v1alpha1", "vmcpmcpservers")
async def reconcile_mcp(
    namespace: str,
    name: str,
    spec: dict[str, Any],
    **_: Any,
) -> dict[str, str]:
    mcp = map_mcp(namespace, name, spec)
    async with _lock_for(mcp.gateway_key):
        LOGGER.info(
            "reconcile mcp %s/%s -> gateway %s source=%s",
            namespace,
            name,
            mcp.gateway_key.as_str(),
            type(mcp.source).__name__,
        )
        return {"phase": "Observed", "gateway": mcp.gateway_key.as_str()}
