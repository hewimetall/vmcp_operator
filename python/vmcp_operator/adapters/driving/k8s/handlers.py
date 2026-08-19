"""Eager Kopf handlers for VmcpGateway / VmcpMcpServer and child enqueue."""

from __future__ import annotations

import logging
from typing import Any

import kopf

from vmcp_operator.adapters.driving.k8s.enqueue import GATEWAY_LABEL, should_enqueue_child
from vmcp_operator.adapters.driving.k8s.finalizer_patch import (
    schedule_finalizer_adds,
    schedule_finalizer_removes,
)
from vmcp_operator.adapters.driving.k8s.mapping import map_gateway, map_mcp
from vmcp_operator.adapters.driving.k8s.runtime import get_runtime
from vmcp_operator.adapters.driving.k8s.status_patch import apply_status, generation_of
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


def _owner_body(
    *,
    api_version: str,
    kind: str,
    namespace: str,
    name: str,
    meta: dict[str, Any],
    body: dict[str, Any] | None,
) -> dict[str, Any] | None:
    uid = meta.get("uid") or ((body or {}).get("metadata") or {}).get("uid")
    if not uid:
        return None
    return {
        "apiVersion": api_version,
        "kind": kind,
        "metadata": {"name": name, "namespace": namespace, "uid": uid},
    }


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
    patch: kopf.Patch,
    body: dict[str, Any] | None = None,
    old: dict[str, Any] | None = None,
    **_: Any,
) -> None:
    generation = generation_of(meta, body)
    if old and "spec" in old:
        violations = check_gateway_immutables(old["spec"], spec)
        if violations:
            apply_status(
                patch,
                phase="Invalid",
                generation=generation,
                reason=violations[0].reason,
                message=violations[0].message,
                ready=False,
            )
            return

    try:
        gateway = map_gateway(namespace, name, spec)
    except (KeyError, TypeError, ValueError) as exc:
        apply_status(
            patch,
            phase="Invalid",
            generation=generation,
            reason="InvalidSpec",
            message=str(exc) or exc.__class__.__name__,
            ready=False,
        )
        return
    runtime = get_runtime()
    deleting = bool(meta.get("deletionTimestamp"))
    finalizers = tuple(meta.get("finalizers") or [])
    owner = _owner_body(
        api_version="vmcp.io/v1alpha1",
        kind="VmcpGateway",
        namespace=namespace,
        name=name,
        meta=meta,
        body=body,
    )
    async with _lock_for(gateway.key):
        mcps = await runtime.list_mcps(gateway.key)
        decision = plan_gateway_finalizer(
            existing=finalizers,
            deleting=deleting,
            children_remaining=len(mcps) if deleting else 0,
        )
        if decision.block_delete:
            apply_status(
                patch,
                phase="Deleting",
                generation=generation,
                reason=decision.reason or "blocked",
                message=decision.reason or "blocked",
                ready=False,
            )
            return
        if deleting and decision.remove:
            schedule_finalizer_removes(patch, decision.remove)
            apply_status(
                patch,
                phase="Finalized",
                generation=generation,
                reason="ready to finalize",
                message="finalizers removed",
                ready=True,
            )
            return
        result = await runtime.gateway_reconcile.execute(gateway, mcps, owner=owner)
        if decision.add:
            schedule_finalizer_adds(patch, decision.add)
        apply_status(
            patch,
            phase=str(result.get("phase", "Applied")),
            generation=generation,
            artifact_sha256=str(result.get("bundleSha256") or "") or None,
            reason="Applied",
            message=(
                f"objects={result.get('objects', 0)} "
                f"adminHopHeaderInjected={result.get('adminHopHeaderInjected', False)}"
            ),
            ready=True,
        )


@kopf.on.create("vmcp.io", "v1alpha1", "vmcpmcpservers")
@kopf.on.update("vmcp.io", "v1alpha1", "vmcpmcpservers")
@kopf.on.resume("vmcp.io", "v1alpha1", "vmcpmcpservers")
async def reconcile_mcp(
    namespace: str,
    name: str,
    spec: dict[str, Any],
    meta: dict[str, Any],
    patch: kopf.Patch,
    body: dict[str, Any] | None = None,
    old: dict[str, Any] | None = None,
    **_: Any,
) -> None:
    generation = generation_of(meta, body)
    if old and "spec" in old:
        violations = check_mcp_immutables(old["spec"], spec)
        if violations:
            apply_status(
                patch,
                phase="Invalid",
                generation=generation,
                reason=violations[0].reason,
                message=violations[0].message,
                ready=False,
            )
            return

    try:
        mcp = map_mcp(namespace, name, spec)
    except (KeyError, TypeError, ValueError) as exc:
        apply_status(
            patch,
            phase="Invalid",
            generation=generation,
            reason="InvalidSpec",
            message=str(exc) or exc.__class__.__name__,
            ready=False,
        )
        return
    runtime = get_runtime()
    deleting = bool(meta.get("deletionTimestamp"))
    finalizers = tuple(meta.get("finalizers") or [])
    owner = _owner_body(
        api_version="vmcp.io/v1alpha1",
        kind="VmcpMcpServer",
        namespace=namespace,
        name=name,
        meta=meta,
        body=body,
    )
    async with _lock_for(mcp.gateway_key):
        gateway = await runtime.get_gateway(mcp.gateway_key)
        unregistered = False
        if deleting:
            if runtime.unregister_upstream is not None:
                unregistered = await runtime.unregister_upstream(
                    mcp.gateway_key,
                    mcp.name,
                )
            else:
                # Tests / dry-run runtime: treat unregister as successful.
                unregistered = True
        decision = plan_mcp_finalizer(
            existing=finalizers,
            deleting=deleting,
            unregistered_from_vmcp=unregistered,
        )
        if decision.block_delete:
            apply_status(
                patch,
                phase="Deleting",
                generation=generation,
                reason=decision.reason or "blocked",
                message=decision.reason or "blocked",
                ready=False,
            )
            return
        if deleting and decision.remove:
            schedule_finalizer_removes(patch, decision.remove)
            await runtime.touch_gateway(mcp.gateway_key)
            apply_status(
                patch,
                phase="Finalized",
                generation=generation,
                reason="unregistered",
                message="finalizers removed",
                ready=True,
            )
            return
        if gateway is None:
            adds = decision.add if decision.add else (MCP_FINALIZER,)
            schedule_finalizer_adds(patch, adds)
            await runtime.touch_gateway(mcp.gateway_key)
            apply_status(
                patch,
                phase="PendingGateway",
                generation=generation,
                reason="PendingGateway",
                message=f"gateway {mcp.gateway_key.as_str()} not found",
                ready=False,
            )
            return
        mcp_result = await runtime.mcp_reconcile.execute(gateway, mcp, owner=owner)
        mcps = await runtime.list_mcps(mcp.gateway_key)
        # Secondary gateway apply from MCP path has no Gateway uid here; skip
        # ownerRefs — primary Gateway reconcile (woken via touch) re-asserts them.
        await runtime.gateway_reconcile.execute(gateway, mcps, owner=None)
        if decision.add:
            schedule_finalizer_adds(patch, decision.add)
        await runtime.touch_gateway(mcp.gateway_key)
        apply_status(
            patch,
            phase=str(mcp_result.get("phase", "Applied")),
            generation=generation,
            reason="Applied",
            message=(
                f"gateway={mcp.gateway_key.as_str()} objects={mcp_result.get('objects', 0)}"
            ),
            ready=True,
        )


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
