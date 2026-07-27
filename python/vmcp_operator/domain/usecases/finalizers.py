"""Finalizer and same-namespace policy helpers."""

from __future__ import annotations

from dataclasses import dataclass

from vmcp_operator.domain.models.gateway import GatewayKey

GATEWAY_FINALIZER = "vmcp.io/gateway-protection"
MCP_FINALIZER = "vmcp.io/unregister-before-gc"


@dataclass(frozen=True, slots=True)
class FinalizerDecision:
    add: tuple[str, ...]
    remove: tuple[str, ...]
    block_delete: bool
    reason: str | None = None


def ensure_same_namespace(gateway: GatewayKey, resource_namespace: str, kind: str) -> None:
    if gateway.namespace != resource_namespace:
        raise ValueError(
            f"{kind} namespace `{resource_namespace}` must equal gateway namespace "
            f"`{gateway.namespace}` (cross-namespace refs forbidden)"
        )


def plan_gateway_finalizer(
    *,
    existing: tuple[str, ...],
    deleting: bool,
    children_remaining: int,
) -> FinalizerDecision:
    present = set(existing)
    if not deleting:
        if GATEWAY_FINALIZER in present:
            return FinalizerDecision(add=(), remove=(), block_delete=False)
        return FinalizerDecision(add=(GATEWAY_FINALIZER,), remove=(), block_delete=False)
    if children_remaining > 0:
        return FinalizerDecision(
            add=(),
            remove=(),
            block_delete=True,
            reason=f"{children_remaining} child objects remain",
        )
    if GATEWAY_FINALIZER in present:
        return FinalizerDecision(
            add=(),
            remove=(GATEWAY_FINALIZER,),
            block_delete=False,
            reason="ready to finalize",
        )
    return FinalizerDecision(add=(), remove=(), block_delete=False)


def plan_mcp_finalizer(
    *,
    existing: tuple[str, ...],
    deleting: bool,
    unregistered_from_vmcp: bool,
) -> FinalizerDecision:
    present = set(existing)
    if not deleting:
        if MCP_FINALIZER in present:
            return FinalizerDecision(add=(), remove=(), block_delete=False)
        return FinalizerDecision(add=(MCP_FINALIZER,), remove=(), block_delete=False)
    if not unregistered_from_vmcp:
        return FinalizerDecision(
            add=(),
            remove=(),
            block_delete=True,
            reason="waiting for upstream unregister before GC",
        )
    if MCP_FINALIZER in present:
        return FinalizerDecision(
            add=(),
            remove=(MCP_FINALIZER,),
            block_delete=False,
            reason="unregistered; allow GC",
        )
    return FinalizerDecision(add=(), remove=(), block_delete=False)
