"""Minimal Kopf-like patch double for handler unit tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class FakePatch:
    def __init__(self) -> None:
        self.status: dict[str, Any] = {}
        self.fns: list[Callable[[dict[str, Any]], None]] = []
