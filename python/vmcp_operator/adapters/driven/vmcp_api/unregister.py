"""Unregister MCP upstreams from a Gateway before child GC."""

from __future__ import annotations

from dataclasses import dataclass

from vmcp_operator.adapters.driven.vmcp_api.client import VmcpApiClient
from vmcp_operator.domain.usecases.connection_strategy import filter_registry_names


@dataclass(frozen=True, slots=True)
class UnregisterUpstream:
    """Remove one upstream name then reload; used by MCP finalizer path."""

    client: VmcpApiClient

    async def execute(self, *, upstream_name: str, desired_sha256: str) -> bool:
        current = await self.client.list_upstream_names()
        remaining = filter_registry_names(current, temporarily_removed=(upstream_name,))
        # Reload after remove is signaled by caller via desired sha of the
        # filtered registry bundle. Here we only verify the live catalog.
        status = await self.client.reload_registry(desired_sha256=desired_sha256)
        return upstream_name not in remaining and (
            status.matched or upstream_name not in status.upstream_names
        )
