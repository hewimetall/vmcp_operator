"""Eager runtime wiring for the operator process.

Handler registration and dashboard startup must import eagerly so
``PYTHON_LAZY_IMPORTS=normal`` keeps decorator side-effects intact.
"""

from __future__ import annotations


def wire() -> None:
    """Register driving adapters. Implemented in later phases."""
    return None
