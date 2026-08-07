"""McpCatalog adapters: in-memory (tests/dashboard stub) and kr8s CR store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import kr8s
from kr8s._exceptions import NotFoundError
from kr8s.asyncio.objects import new_class

from vmcp_operator.adapters.driving.k8s.mapping import map_mcp, mcp_to_crd
from vmcp_operator.domain.models.gateway import GatewayKey
from vmcp_operator.domain.models.mcp import McpServerDesired


@dataclass
class InMemoryMcpCatalog:
    """Test/double catalog keyed by namespace/name."""

    items: dict[str, McpServerDesired] = field(default_factory=dict)

    def _key(self, namespace: str, name: str) -> str:
        return f"{namespace}/{name}"

    async def list_for_gateway(self, key: GatewayKey) -> list[McpServerDesired]:
        return [item for item in self.items.values() if item.gateway_key == key]

    async def get(self, namespace: str, name: str) -> McpServerDesired | None:
        return self.items.get(self._key(namespace, name))

    async def upsert(self, mcp: McpServerDesired) -> McpServerDesired:
        self.items[self._key(mcp.namespace, mcp.name)] = mcp
        return mcp

    async def delete(self, namespace: str, name: str) -> bool:
        return self.items.pop(self._key(namespace, name), None) is not None


@dataclass
class Kr8sMcpCatalog:
    """Persist VmcpMcpServer CRs via the Kubernetes API."""

    api: Any | None = None
    field_manager: str = "vmcp-operator-control-plane"

    async def _api(self) -> Any:
        if self.api is None:
            self.api = await kr8s.asyncio.api()
        return self.api

    def _cls(self) -> Any:
        return new_class(
            kind="VmcpMcpServer",
            version="vmcp.io/v1alpha1",
            plural="vmcpmcpservers",
            namespaced=True,
            asyncio=True,
        )

    async def list_for_gateway(self, key: GatewayKey) -> list[McpServerDesired]:
        api = await self._api()
        cls = self._cls()
        rows: list[McpServerDesired] = []
        async for obj in cls.list(namespace=key.namespace, api=api):
            raw = dict(obj.raw)
            meta = raw.get("metadata") or {}
            spec = raw.get("spec") or {}
            if str((spec.get("gatewayRef") or {}).get("name", "")) != key.name:
                continue
            rows.append(map_mcp(str(meta["namespace"]), str(meta["name"]), spec))
        return rows

    async def get(self, namespace: str, name: str) -> McpServerDesired | None:
        api = await self._api()
        cls = self._cls()
        obj = cls({"metadata": {"name": name, "namespace": namespace}}, api=api)
        try:
            if not await obj.exists():
                return None
            await obj.refresh()
        except NotFoundError:
            return None
        raw = dict(obj.raw)
        meta = raw.get("metadata") or {}
        return map_mcp(str(meta["namespace"]), str(meta["name"]), raw.get("spec") or {})

    async def upsert(self, mcp: McpServerDesired) -> McpServerDesired:
        api = await self._api()
        body = mcp_to_crd(mcp)
        cls = self._cls()
        obj = cls(body, api=api)
        try:
            if await obj.exists():
                await obj.patch(
                    body,
                    type="apply",
                    field_manager=self.field_manager,
                    force=True,
                )
                await obj.refresh()
            else:
                await obj.create()
        except NotFoundError:
            await obj.create()
        raw = dict(obj.raw)
        meta = raw.get("metadata") or {}
        return map_mcp(str(meta["namespace"]), str(meta["name"]), raw.get("spec") or {})

    async def delete(self, namespace: str, name: str) -> bool:
        api = await self._api()
        cls = self._cls()
        obj = cls({"metadata": {"name": name, "namespace": namespace}}, api=api)
        try:
            if not await obj.exists():
                return False
            await obj.delete()
            return True
        except NotFoundError:
            return False
