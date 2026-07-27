"""List watched Gateway environments for the operator dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from vmcp_operator.domain.models.gateway import GatewayDesired, GatewayKey
from vmcp_operator.domain.ports import GatewayRepository


@dataclass(frozen=True, slots=True)
class EnvironmentRow:
    key: GatewayKey
    phase: str
    public_hostname: str
    admin_url: str | None


@dataclass(frozen=True, slots=True)
class ListEnvironments:
    gateways: GatewayRepository
    phases: dict[str, str]

    async def execute(self) -> list[EnvironmentRow]:
        rows: list[EnvironmentRow] = []
        for gateway in await self.gateways.list_all():
            rows.append(_to_row(gateway, self.phases.get(gateway.key.as_str(), "Unknown")))
        rows.sort(key=lambda row: row.key.as_str())
        return rows


def _to_row(gateway: GatewayDesired, phase: str) -> EnvironmentRow:
    admin_url = None
    if gateway.admin_route is not None:
        admin_url = f"https://{gateway.admin_route.hostname}/admin"
    return EnvironmentRow(
        key=gateway.key,
        phase=phase,
        public_hostname=gateway.public_route.hostname,
        admin_url=admin_url,
    )
