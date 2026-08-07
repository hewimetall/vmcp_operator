"""GatewayRepository adapter backed by VmcpGateway CRs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import kr8s
from kr8s._exceptions import NotFoundError
from kr8s.asyncio.objects import new_class

from vmcp_operator.adapters.driving.k8s.mapping import map_gateway
from vmcp_operator.domain.models.gateway import GatewayDesired, GatewayKey


@dataclass
class Kr8sGatewayRepository:
    api: Any | None = None

    async def _api(self) -> Any:
        if self.api is None:
            self.api = await kr8s.asyncio.api()
        return self.api

    def _cls(self) -> Any:
        return new_class(
            kind="VmcpGateway",
            version="vmcp.io/v1alpha1",
            plural="vmcpgateways",
            namespaced=True,
            asyncio=True,
        )

    async def get(self, key: GatewayKey) -> GatewayDesired | None:
        api = await self._api()
        cls = self._cls()
        obj = cls(
            {"metadata": {"name": key.name, "namespace": key.namespace}},
            api=api,
        )
        try:
            if not await obj.exists():
                return None
            await obj.refresh()
        except NotFoundError:
            return None
        raw = dict(obj.raw)
        meta = raw.get("metadata") or {}
        return map_gateway(str(meta["namespace"]), str(meta["name"]), raw.get("spec") or {})

    async def list_all(self) -> list[GatewayDesired]:
        api = await self._api()
        cls = self._cls()
        rows: list[GatewayDesired] = []
        async for obj in cls.list(api=api):
            raw = dict(obj.raw)
            meta = raw.get("metadata") or {}
            rows.append(
                map_gateway(str(meta["namespace"]), str(meta["name"]), raw.get("spec") or {})
            )
        return rows
