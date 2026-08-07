"""Ports for reading Kubernetes Secret values at reconcile time."""

from __future__ import annotations

from typing import Protocol

from vmcp_operator.domain.models.gateway import SecretRef


class SecretValueLoader(Protocol):
    async def get(self, namespace: str, ref: SecretRef) -> str | None:
        """Return the secret value, or None when missing / unreadable."""
