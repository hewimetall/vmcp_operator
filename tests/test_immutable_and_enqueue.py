from __future__ import annotations

from vmcp_operator.adapters.driving.k8s.enqueue import (
    gateway_key_from_labels,
    should_enqueue_child,
)
from vmcp_operator.domain.usecases.immutable import (
    _size_bytes,
    check_gateway_immutables,
    check_mcp_immutables,
)


def test_immutable_gateway_and_mcp_rules() -> None:
    violations = check_gateway_immutables(
        {"persistence": {"storageClassName": "a", "size": "10Gi"}},
        {"persistence": {"storageClassName": "b", "size": "10Gi"}},
    )
    assert violations[0].field == "persistence.storageClassName"

    reclaim = check_gateway_immutables(
        {"persistence": {"reclaimPolicy": "Retain"}},
        {"persistence": {"reclaimPolicy": "Delete"}},
    )
    assert reclaim[0].field == "persistence.reclaimPolicy"

    shrink = check_gateway_immutables(
        {"persistence": {"size": "10Gi"}},
        {"persistence": {"size": "5Gi"}},
    )
    assert shrink[0].field == "persistence.size"

    grow = check_gateway_immutables(
        {"persistence": {"size": "5Gi"}},
        {"persistence": {"size": "10Gi"}},
    )
    assert grow == ()

    mcp = check_mcp_immutables(
        {"gatewayRef": {"name": "a"}},
        {"gatewayRef": {"name": "b"}},
    )
    assert mcp[0].field == "gatewayRef.name"
    assert check_mcp_immutables({"gatewayRef": {"name": "a"}}, {"gatewayRef": {"name": "a"}}) == ()
    assert _size_bytes("12") == 12


def test_enqueue_from_labels_and_annotation() -> None:
    key = gateway_key_from_labels("team-a", {"vmcp.io/gateway": "main"})
    assert key is not None
    assert key.as_str() == "team-a/main"
    assert gateway_key_from_labels("team-a", {}) is None
    assert gateway_key_from_labels("team-a", None) is None
    assert gateway_key_from_labels("team-a", {"vmcp.io/gateway": ""}) is None

    keyed = should_enqueue_child(
        {
            "metadata": {
                "namespace": "team-a",
                "annotations": {"vmcp.io/gateway-key": "team-a/main"},
            }
        }
    )
    assert keyed is not None
    assert keyed.as_str() == "team-a/main"
    assert should_enqueue_child({"metadata": {}}) is None
    assert should_enqueue_child({"metadata": {"namespace": "team-a", "labels": 1}}) is None
    assert (
        should_enqueue_child(
            {
                "metadata": {
                    "namespace": "team-a",
                    "annotations": {"vmcp.io/gateway-key": "noslash"},
                }
            }
        )
        is None
    )
