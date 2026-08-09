"""Minimal Kopf-like patch double for handler unit tests."""

from __future__ import annotations

from typing import Any, Callable


class FakePatch:
    def __init__(self) -> None:
        self.status: dict[str, Any] = {}
        self.fns: list[Callable[[dict[str, Any]], None]] = []
