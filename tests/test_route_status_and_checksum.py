from __future__ import annotations

from vmcp_operator.domain.usecases.checksum_rollout import managed_workload_checksum
from vmcp_operator.domain.usecases.route_status import (
    assert_routes_ready,
    summarize_route_status,
)


def test_route_status_ready_and_not_ready() -> None:
    ready = summarize_route_status(
        name="main-public",
        status={
            "conditions": [
                {"type": "Accepted", "status": "True", "reason": "Accepted"},
                {"type": "ResolvedRefs", "status": "True", "reason": "ResolvedRefs"},
            ]
        },
    )
    assert ready.ready is True
    assert assert_routes_ready((ready,)) == ()

    with_ready = summarize_route_status(
        name="main-public",
        status={
            "conditions": [
                {"type": "Accepted", "status": "True"},
                {"type": "ResolvedRefs", "status": "True"},
                {"type": "Ready", "status": "True"},
            ]
        },
    )
    assert with_ready.ready is True

    empty = summarize_route_status(name="x", status=None)
    assert empty.ready is False

    bad = summarize_route_status(
        name="main-admin",
        status={
            "conditions": [
                {"type": "Accepted", "status": "False", "reason": "NotAllowed"},
                {"type": "ResolvedRefs", "status": "True"},
                "skip-me",
            ]
        },
    )
    assert bad.ready is False
    assert "Accepted:NotAllowed" in bad.reasons
    assert assert_routes_ready((ready, bad)) == (bad,)


def test_checksum_stable_and_sensitive() -> None:
    a = managed_workload_checksum(
        image="reg/ai/x:1",
        env=(("A", "1"),),
        ports=(("http", 8080),),
        mcp_path="/mcp",
    )
    b = managed_workload_checksum(
        image="reg/ai/x:1",
        env=(("A", "1"),),
        ports=(("http", 8080),),
        mcp_path="/mcp",
    )
    c = managed_workload_checksum(
        image="reg/ai/x:2",
        env=(("A", "1"),),
        ports=(("http", 8080),),
        mcp_path="/mcp",
    )
    assert a == b
    assert a != c
