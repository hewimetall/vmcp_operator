"""Deliver finalizer add/remove via Kopf ``patch.fns`` transforms."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


def ensure_finalizer(name: str) -> Callable[[dict[str, Any]], None]:
    def _apply(body: dict[str, Any], /) -> None:
        finalizers = body.setdefault("metadata", {}).setdefault("finalizers", [])
        if name not in finalizers:
            finalizers.append(name)

    return _apply


def drop_finalizer(name: str) -> Callable[[dict[str, Any]], None]:
    def _apply(body: dict[str, Any], /) -> None:
        meta = body.setdefault("metadata", {})
        existing = list(meta.get("finalizers") or [])
        meta["finalizers"] = [item for item in existing if item != name]

    return _apply


def schedule_finalizer_adds(patch: Any, names: Iterable[str]) -> None:
    fns = _fns(patch)
    for name in names:
        fns.append(ensure_finalizer(name))


def schedule_finalizer_removes(patch: Any, names: Iterable[str]) -> None:
    fns = _fns(patch)
    for name in names:
        fns.append(drop_finalizer(name))


def apply_fns_to_body(
    fns: Iterable[Callable[[dict[str, Any]], None]],
    body: dict[str, Any],
) -> None:
    """Test helper: run scheduled transforms against a mutable body copy."""
    for fn in fns:
        fn(body)


def _fns(patch: Any) -> list[Any]:
    fns = getattr(patch, "fns", None)
    if fns is None:
        if isinstance(patch, dict):
            stored = patch.setdefault("fns", [])
            if not isinstance(stored, list):
                raise TypeError("patch.fns must be a list")
            return stored
        raise TypeError("patch must expose a mutable .fns list")
    if not isinstance(fns, list):
        # Kopf may use a custom list-like; append must work.
        return fns  # type: ignore[return-value]
    return fns


__all__ = [
    "apply_fns_to_body",
    "drop_finalizer",
    "ensure_finalizer",
    "schedule_finalizer_adds",
    "schedule_finalizer_removes",
]
