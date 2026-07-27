"""Eager Kopf handlers for VmcpGateway / VmcpMcpServer and child enqueue."""

from __future__ import annotations

import logging
from typing import Any

import kopf

from vmcp_operator.adapters.driving.k8s.enqueue import GATEWAY_LABEL, should_enqueue_child
from vmcp_operator.adapters.driving.k8s.mapping import map_gateway, map_mcp
from vmcp_operator.adapters.driving.k8s.runtime import get_runtime
from vmcp_operator.domain.models.gateway import GatewayKey
from vmcp_operator.domain.usecases.finalizers import (
    MCP_FINALIZER,
    plan_gateway_finalizer,
    plan_mcp_finalizer,
)
from vmcp_operator.domain.usecases.immutable import (
    check_gateway_immutables,
    check_mcp_immutables,
)

LOGGER = logging.getLogger(__name__)

# Per-gateway serialization markers (in-process MVP, replicaCount=1).
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
    meta: dict[str, Any],
    old: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    if old and "spec" in old:
        violations = check_gateway_immutables(old["spec"], spec)
        if violations:
            return {
                "phase": "Invalid",
                "gateway": f"{namespace}/{name}",
                "reason": violations[0].reason,
                "message": violations[0].message,
            }

    gateway = map_gateway(namespace, name, spec)
    runtime = get_runtime()
    deleting = bool(meta.get("deletionTimestamp"))
    finalizers = tuple(meta.get("finalizers") or [])
    async with _lock_for(gateway.key):
        mcps = await runtime.list_mcps(gateway.key)
        decision = plan_gateway_finalizer(
            existing=finalizers,
            deleting=deleting,
            children_remaining=len(mcps) if deleting else 0,
        )
        if decision.block_delete:
            return {
                "phase": "Deleting",
                "gateway": gateway.key.as_str(),
                "reason": decision.reason or "blocked",
            }
        if deleting and decision.remove:
            return {
                "phase": "Finalized",
                "gateway": gateway.key.as_str(),
                "removeFinalizers": list(decision.remove),
            }
        result = await runtime.gateway_reconcile.execute(gateway, mcps)
        if decision.add:
            result = {**result, "addFinalizers": list(decision.add)}
        return result


@kopf.on.create("vmcp.io", "v1alpha1", "vmcpmcpservers")
@kopf.on.update("vmcp.io", "v1alpha1", "vmcpmcpservers")
@kopf.on.resume("vmcp.io", "v1alpha1", "vmcpmcpservers")
async def reconcile_mcp(
    namespace: str,
    name: str,
    spec: dict[str, Any],
    meta: dict[str, Any],
    old: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    if old and "spec" in old:
        violations = check_mcp_immutables(old["spec"], spec)
        if violations:
            return {
                "phase": "Invalid",
                "gateway": f"{namespace}/{spec.get('gatewayRef', {}).get('name', '')}",
                "reason": violations[0].reason,
                "message": violations[0].message,
            }

    mcp = map_mcp(namespace, name, spec)
    runtime = get_runtime()
    deleting = bool(meta.get("deletionTimestamp"))
    finalizers = tuple(meta.get("finalizers") or [])
    async with _lock_for(mcp.gateway_key):
        gateway = await runtime.get_gateway(mcp.gateway_key)
        decision = plan_mcp_finalizer(
            existing=finalizers,
            deleting=deleting,
            unregistered_from_vmcp=deleting,  # unregister step lands with live API client
        )
        if decision.block_delete:
            return {
                "phase": "Deleting",
                "gateway": mcp.gateway_key.as_str(),
                "reason": decision.reason or "blocked",
            }
        if deleting and decision.remove:
            runtime.enqueue(mcp.gateway_key)
            return {
                "phase": "Finalized",
                "gateway": mcp.gateway_key.as_str(),
                "removeFinalizers": list(decision.remove),
            }
        if gateway is None:
            runtime.enqueue(mcp.gateway_key)
            return {
                "phase": "PendingGateway",
                "gateway": mcp.gateway_key.as_str(),
                "addFinalizers": list(decision.add) if decision.add else [MCP_FINALIZER],
            }
        mcp_result = await runtime.mcp_reconcile.execute(gateway, mcp)
        mcps = await runtime.list_mcps(mcp.gateway_key)
        # Keep gateway aggregate registry in sync when MCP changes.
        gateway_result = await runtime.gateway_reconcile.execute(gateway, mcps)
        result = {
            **mcp_result,
            "bundleSha256": gateway_result.get("bundleSha256", ""),
            "gatewayObjects": gateway_result.get("objects", 0),
        }
        if decision.add:
            result["addFinalizers"] = list(decision.add)
        return result


@kopf.on.event("apps", "v1", "deployments", labels={GATEWAY_LABEL: kopf.PRESENT})
@kopf.on.event("", "v1", "configmaps", labels={GATEWAY_LABEL: kopf.PRESENT})
@kopf.on.event("", "v1", "secrets", labels={GATEWAY_LABEL: kopf.PRESENT})
async def enqueue_from_child(
    namespace: str,
    name: str,
    body: dict[str, Any],
    **_: Any,
) -> None:
    key = should_enqueue_child(body)
    if key is None:
        return
    runtime = get_runtime()
    runtime.enqueue(key)
    LOGGER.info("enqueued gateway %s from child %s/%s", key.as_str(), namespace, name)


__all__ = [
    "configure",
    "enqueue_from_child",
    "reconcile_gateway",
    "reconcile_mcp",
]
