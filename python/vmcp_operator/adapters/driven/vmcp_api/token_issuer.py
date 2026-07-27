"""TokenIssuer port adapter over VmcpApiClient."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vmcp_operator.adapters.driven.vmcp_api.client import VmcpApiClient
from vmcp_operator.domain.models.gateway import GatewayKey


@dataclass(frozen=True, slots=True)
class VmcpTokenIssuer:
    client_for: Callable[[GatewayKey], VmcpApiClient]

    async def issue_use_token(self, key: GatewayKey, client_name: str) -> str:
        client = self.client_for(key)
        return await client.issue_static_token(client_name=client_name, scope="mcp:use")
