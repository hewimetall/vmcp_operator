"""Server-side apply helper with conflict retry (pure function over a port)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ObjectApplier(Protocol):
    async def server_side_apply(
        self,
        body: dict[str, Any],
        *,
        field_manager: str,
        force: bool,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ServerSideApply:
    applier: ObjectApplier
    field_manager: str = "vmcp-operator"
    max_attempts: int = 5

    async def apply(self, body: dict[str, Any]) -> dict[str, Any]:
        force = False
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await self.applier.server_side_apply(
                    body,
                    field_manager=self.field_manager,
                    force=force,
                )
            except ConflictError as exc:
                last_error = exc
                force = True
                if attempt == self.max_attempts:
                    break
        assert last_error is not None
        raise last_error


class ConflictError(RuntimeError):
    """Raised by the applier when SSA reports a field-manager conflict."""


@dataclass
class InMemoryApplier:
    """Test double that can inject conflicts then succeed."""

    conflicts_before_success: int = 0
    applied: list[dict[str, Any]] | None = None
    _seen: int = 0

    def __post_init__(self) -> None:
        if self.applied is None:
            self.applied = []

    async def server_side_apply(
        self,
        body: dict[str, Any],
        *,
        field_manager: str,
        force: bool,
    ) -> dict[str, Any]:
        del force  # force is exercised by ServerSideApply; conflicts are attempt-based.
        self._seen += 1
        if self._seen <= self.conflicts_before_success:
            raise ConflictError("conflict")
        assert self.applied is not None
        self.applied.append({"body": body, "field_manager": field_manager})
        return body
