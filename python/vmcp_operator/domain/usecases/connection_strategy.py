"""MCP connection strategy: remove/add when Service URL is unchanged.

vmcp reload does not reconnect an upstream whose URL is unchanged after a
workload rollout. Operator must remove the upstream, reload, roll the
workload, then add/reload.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConnectionPhase(StrEnum):
    STABLE = "Stable"
    REMOVE = "Remove"
    WAIT_WORKLOAD = "WaitWorkload"
    ADD = "Add"


@dataclass(frozen=True, slots=True)
class ConnectionPlan:
    phase: ConnectionPhase
    remove_names: tuple[str, ...]
    add_names: tuple[str, ...]
    reload_after_remove: bool
    reload_after_add: bool


@dataclass(frozen=True, slots=True)
class McpConnectionStrategy:
    """Derive two-phase reconnect actions for rolled MCP workloads."""

    def plan_rollout(
        self,
        *,
        rolled_names: tuple[str, ...],
        service_url_unchanged: bool,
    ) -> ConnectionPlan:
        names = tuple(sorted({name for name in rolled_names if name}))
        if not names or not service_url_unchanged:
            return ConnectionPlan(
                phase=ConnectionPhase.STABLE,
                remove_names=(),
                add_names=(),
                reload_after_remove=False,
                reload_after_add=False,
            )
        return ConnectionPlan(
            phase=ConnectionPhase.REMOVE,
            remove_names=names,
            add_names=names,
            reload_after_remove=True,
            reload_after_add=True,
        )

    def next_after_remove(self, plan: ConnectionPlan) -> ConnectionPlan:
        if plan.phase != ConnectionPhase.REMOVE:
            return plan
        return ConnectionPlan(
            phase=ConnectionPhase.WAIT_WORKLOAD,
            remove_names=plan.remove_names,
            add_names=plan.add_names,
            reload_after_remove=False,
            reload_after_add=plan.reload_after_add,
        )

    def next_after_workload_ready(self, plan: ConnectionPlan) -> ConnectionPlan:
        if plan.phase != ConnectionPhase.WAIT_WORKLOAD:
            return plan
        return ConnectionPlan(
            phase=ConnectionPhase.ADD,
            remove_names=(),
            add_names=plan.add_names,
            reload_after_remove=False,
            reload_after_add=True,
        )

    def next_after_add(self, plan: ConnectionPlan) -> ConnectionPlan:
        if plan.phase != ConnectionPhase.ADD:
            return plan
        return ConnectionPlan(
            phase=ConnectionPhase.STABLE,
            remove_names=(),
            add_names=(),
            reload_after_remove=False,
            reload_after_add=False,
        )


def filter_registry_names(
    desired_names: tuple[str, ...],
    *,
    temporarily_removed: tuple[str, ...],
) -> tuple[str, ...]:
    """Drop temporarily removed upstreams from the desired registry set."""
    removed = set(temporarily_removed)
    return tuple(name for name in desired_names if name not in removed)
