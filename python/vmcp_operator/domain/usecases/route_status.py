"""Evaluate Gateway API HTTPRoute Conditions independently of MCP status."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RouteCondition:
    type: str
    status: str
    reason: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class RouteStatusSummary:
    name: str
    accepted: bool
    resolved_refs: bool
    ready: bool
    reasons: tuple[str, ...]


def parse_route_conditions(status: dict[str, Any] | None) -> tuple[RouteCondition, ...]:
    if not status:
        return ()
    raw = status.get("conditions") or []
    out: list[RouteCondition] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            RouteCondition(
                type=str(item.get("type", "")),
                status=str(item.get("status", "")),
                reason=str(item.get("reason", "")),
                message=str(item.get("message", "")),
            )
        )
    return tuple(out)


def summarize_route_status(
    *,
    name: str,
    status: dict[str, Any] | None,
) -> RouteStatusSummary:
    conditions = {c.type: c for c in parse_route_conditions(status)}
    accepted = _is_true(conditions.get("Accepted"))
    resolved = _is_true(conditions.get("ResolvedRefs"))
    # Some implementations expose Ready; treat missing Ready as AND of the two.
    ready = (
        _is_true(conditions.get("Ready"))
        if "Ready" in conditions
        else accepted and resolved
    )
    reasons = tuple(
        f"{c.type}:{c.reason or c.status}"
        for c in conditions.values()
        if c.status.lower() not in {"true", "1"}
    )
    return RouteStatusSummary(
        name=name,
        accepted=accepted,
        resolved_refs=resolved,
        ready=ready,
        reasons=reasons,
    )


def assert_routes_ready(
    routes: tuple[RouteStatusSummary, ...],
) -> tuple[RouteStatusSummary, ...]:
    """Return not-ready routes (empty means all good)."""
    return tuple(route for route in routes if not route.ready)


def _is_true(condition: RouteCondition | None) -> bool:
    if condition is None:
        return False
    return condition.status.lower() in {"true", "1"}
