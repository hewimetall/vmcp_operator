from __future__ import annotations

import pytest

from vmcp_operator.domain.models.gateway import GatewayKey
from vmcp_operator.domain.usecases.finalizers import (
    GATEWAY_FINALIZER,
    MCP_FINALIZER,
    ensure_same_namespace,
    plan_gateway_finalizer,
    plan_mcp_finalizer,
)
from vmcp_operator.domain.usecases.skills_sync import PlanSkillsSync, SkillFile


def test_skills_sync_preserves_admin_owned_and_refreshes_managed() -> None:
    plan = PlanSkillsSync().execute(
        desired_managed=(
            SkillFile(name="research_docs", content="new", managed=True),
            SkillFile(name="architect_overview", content="a", managed=True),
        ),
        existing_names=("research_docs", "admin_custom", "stale_managed"),
        previously_managed_names=("research_docs", "stale_managed"),
    )
    assert [s.name for s in plan.write] == ["architect_overview", "research_docs"]
    assert plan.delete == ("stale_managed",)
    assert plan.keep == ("admin_custom",)


def test_skills_sync_rejects_duplicates_and_unmanaged_flag() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        PlanSkillsSync().execute(
            desired_managed=(
                SkillFile(name="a", content="1", managed=True),
                SkillFile(name="a", content="2", managed=True),
            ),
            existing_names=(),
            previously_managed_names=(),
        )
    with pytest.raises(ValueError, match="managed"):
        PlanSkillsSync().execute(
            desired_managed=(SkillFile(name="a", content="1", managed=False),),
            existing_names=(),
            previously_managed_names=(),
        )


def test_finalizers_block_until_unregister() -> None:
    add = plan_mcp_finalizer(existing=(), deleting=False, unregistered_from_vmcp=False)
    assert add.add == (MCP_FINALIZER,)
    already = plan_mcp_finalizer(
        existing=(MCP_FINALIZER,),
        deleting=False,
        unregistered_from_vmcp=False,
    )
    assert already.add == ()
    blocked = plan_mcp_finalizer(
        existing=(MCP_FINALIZER,),
        deleting=True,
        unregistered_from_vmcp=False,
    )
    assert blocked.block_delete is True
    done = plan_mcp_finalizer(
        existing=(MCP_FINALIZER,),
        deleting=True,
        unregistered_from_vmcp=True,
    )
    assert done.remove == (MCP_FINALIZER,)
    done_absent = plan_mcp_finalizer(
        existing=(),
        deleting=True,
        unregistered_from_vmcp=True,
    )
    assert done_absent.remove == ()

    gw_add = plan_gateway_finalizer(
        existing=(),
        deleting=False,
        children_remaining=0,
    )
    assert gw_add.add == (GATEWAY_FINALIZER,)
    gw_present = plan_gateway_finalizer(
        existing=(GATEWAY_FINALIZER,),
        deleting=False,
        children_remaining=0,
    )
    assert gw_present.add == ()
    gw_block = plan_gateway_finalizer(
        existing=(GATEWAY_FINALIZER,),
        deleting=True,
        children_remaining=2,
    )
    assert gw_block.block_delete is True
    gw_done = plan_gateway_finalizer(
        existing=(GATEWAY_FINALIZER,),
        deleting=True,
        children_remaining=0,
    )
    assert gw_done.remove == (GATEWAY_FINALIZER,)
    gw_done_absent = plan_gateway_finalizer(
        existing=(),
        deleting=True,
        children_remaining=0,
    )
    assert gw_done_absent.remove == ()


def test_same_namespace_enforced() -> None:
    ensure_same_namespace(GatewayKey("team-a", "main"), "team-a", "Secret")
    with pytest.raises(ValueError, match="cross-namespace"):
        ensure_same_namespace(GatewayKey("team-a", "main"), "team-b", "Secret")
