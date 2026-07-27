"""Eager runtime wiring for the operator process.

Handler registration and dashboard startup must import eagerly so
``PYTHON_LAZY_IMPORTS=normal`` keeps decorator side-effects intact.
"""

from __future__ import annotations

from vmcp_operator.adapters.driving.k8s import handlers as _handlers

__all__ = ["handlers", "wire"]

handlers = _handlers


def wire() -> None:
    """Import driving adapters so Kopf decorators register."""
    # Touch module attribute to keep import side-effects intentional.
    assert handlers.reconcile_gateway is not None
    assert handlers.reconcile_mcp is not None
