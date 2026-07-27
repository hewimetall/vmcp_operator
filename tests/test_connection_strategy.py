from __future__ import annotations

from vmcp_operator.domain.usecases.connection_strategy import (
    ConnectionPhase,
    McpConnectionStrategy,
    filter_registry_names,
)


def test_rollout_with_unchanged_url_requires_remove_add() -> None:
    strategy = McpConnectionStrategy()
    plan = strategy.plan_rollout(
        rolled_names=("architect-c4",),
        service_url_unchanged=True,
    )
    assert plan.phase == ConnectionPhase.REMOVE
    assert plan.remove_names == ("architect-c4",)
    assert plan.reload_after_remove is True

    waiting = strategy.next_after_remove(plan)
    assert waiting.phase == ConnectionPhase.WAIT_WORKLOAD
    adding = strategy.next_after_workload_ready(waiting)
    assert adding.phase == ConnectionPhase.ADD
    assert adding.add_names == ("architect-c4",)
    stable = strategy.next_after_add(adding)
    assert stable.phase == ConnectionPhase.STABLE


def test_url_change_skips_two_phase() -> None:
    plan = McpConnectionStrategy().plan_rollout(
        rolled_names=("architect-c4",),
        service_url_unchanged=False,
    )
    assert plan.phase == ConnectionPhase.STABLE
    assert filter_registry_names(
        ("a", "b", "c"),
        temporarily_removed=("b",),
    ) == ("a", "c")


def test_connection_transitions_are_phase_guarded() -> None:
    strategy = McpConnectionStrategy()
    stable = strategy.plan_rollout(rolled_names=(), service_url_unchanged=True)
    assert strategy.next_after_remove(stable).phase == ConnectionPhase.STABLE
    assert strategy.next_after_workload_ready(stable).phase == ConnectionPhase.STABLE
    assert strategy.next_after_add(stable).phase == ConnectionPhase.STABLE
