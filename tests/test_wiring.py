from __future__ import annotations

from vmcp_operator.wiring import wire


def test_wire_is_noop_until_handlers_land() -> None:
    assert wire() is None
