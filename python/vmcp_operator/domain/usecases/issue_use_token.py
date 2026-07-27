"""Issue a one-time static token with fixed mcp:use scope."""

from __future__ import annotations

from dataclasses import dataclass

from vmcp_operator.domain.models.gateway import GatewayKey
from vmcp_operator.domain.ports import GatewayRepository, TokenIssuer

FIXED_SCOPE = "mcp:use"


class DuplicateTokenError(ValueError):
    """Raised when the selected Gateway already has the client name."""


@dataclass(frozen=True, slots=True)
class IssuedToken:
    gateway: GatewayKey
    client_name: str
    scope: str
    token: str


@dataclass(frozen=True, slots=True)
class IssueUseToken:
    gateways: GatewayRepository
    issuer: TokenIssuer

    async def execute(self, key: GatewayKey, client_name: str) -> IssuedToken:
        name = client_name.strip()
        if not name:
            raise ValueError("client name must be non-empty")
        gateway = await self.gateways.get(key)
        if gateway is None:
            raise LookupError(f"gateway `{key.as_str()}` not found")
        try:
            token = await self.issuer.issue_use_token(key, name)
        except FileExistsError as exc:
            raise DuplicateTokenError(str(exc)) from exc
        return IssuedToken(
            gateway=key,
            client_name=name,
            scope=FIXED_SCOPE,
            token=token,
        )
