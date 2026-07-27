from __future__ import annotations

from vmcp_operator.wiring import handlers, wire


def test_wire_registers_kopf_handlers() -> None:
    wire()
    assert callable(handlers.reconcile_gateway)
    assert callable(handlers.reconcile_mcp)
