"""Wake a VmcpGateway reconcile by bumping an annotation (labels/annotations are essential)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from vmcp_operator.domain.models.gateway import GatewayKey

TOUCH_ANNOTATION = "vmcp.io/mcp-generation"


class GatewayToucher(Protocol):
    async def touch(self, key: GatewayKey) -> None: ...


@dataclass
class RecordingGatewayToucher:
    """In-memory toucher for unit tests."""

    touches: list[str] = field(default_factory=list)

    async def touch(self, key: GatewayKey) -> None:
        self.touches.append(key.as_str())


@dataclass
class Kr8sGatewayToucher:
    api: Any | None = None

    async def _api(self) -> Any:
        if self.api is None:
            import kr8s

            self.api = await kr8s.asyncio.api()
        return self.api

    async def touch(self, key: GatewayKey) -> None:
        from kr8s._exceptions import NotFoundError
        from kr8s.asyncio.objects import new_class

        api = await self._api()
        cls = new_class(
            kind="VmcpGateway",
            version="vmcp.io/v1alpha1",
            plural="vmcpgateways",
            namespaced=True,
            asyncio=True,
        )
        obj = cls(
            {"metadata": {"name": key.name, "namespace": key.namespace}},
            api=api,
        )
        try:
            if not await obj.exists():
                return
            await obj.refresh()
        except NotFoundError:
            return
        stamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        await obj.patch(
            {
                "metadata": {
                    "annotations": {
                        TOUCH_ANNOTATION: stamp,
                    }
                }
            }
        )


__all__ = [
    "TOUCH_ANNOTATION",
    "GatewayToucher",
    "Kr8sGatewayToucher",
    "RecordingGatewayToucher",
]
