"""Operator control-plane value objects (above per-instance vmcp)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from vmcp_operator.domain.models.gateway import GatewayKey
from vmcp_operator.domain.models.mcp import McpServerDesired


class McpMutation(StrEnum):
    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"
    LIST = "list"
    GET = "get"


@dataclass(frozen=True, slots=True)
class McpWriteResult:
    mutation: McpMutation
    mcp: McpServerDesired
    created: bool = False


@dataclass(frozen=True, slots=True)
class NlIntent:
    """Structured intent produced by the NL planner (never LLM-bound)."""

    mutation: McpMutation
    gateway: GatewayKey | None = None
    name: str | None = None
    fields: dict[str, Any] | None = None
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class NlCrudResult:
    intent: NlIntent
    applied: bool
    message: str
    mcps: tuple[McpServerDesired, ...] = ()
    mcp: McpServerDesired | None = None
