"""Console entrypoint."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any


def main() -> None:
    """Start the operator with eager handler wiring."""
    os.environ.setdefault("PYTHON_LAZY_IMPORTS", "normal")
    if sys._is_gil_enabled():
        raise SystemExit("vmcp-operator requires free-threaded CPython (GIL is enabled)")

    from vmcp_operator.wiring import wire

    wire()

    if os.environ.get("VMCP_OPERATOR_DASHBOARD_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        _start_dashboard_background()

    import kopf

    kopf.run(clusterwide=False)


def _start_dashboard_background() -> None:
    """Optionally serve the fleet dashboard beside Kopf."""
    from vmcp_operator.adapters.driven.k8s.gateway_catalog import Kr8sGatewayRepository
    from vmcp_operator.adapters.driven.k8s.mcp_catalog import (
        InMemoryMcpCatalog,
        Kr8sMcpCatalog,
    )
    from vmcp_operator.adapters.driving.dashboard.app import DashboardAuth, create_app
    from vmcp_operator.adapters.driving.dashboard.control_plane import build_control_plane
    from vmcp_operator.domain.usecases.issue_use_token import IssueUseToken
    from vmcp_operator.domain.usecases.list_environments import ListEnvironments

    class _DeniedIssuer:
        async def issue_use_token(self, key: Any, client_name: str) -> str:
            raise LookupError("dashboard token issuer not configured")

    auth = DashboardAuth(
        username=os.environ.get("VMCP_OPERATOR_DASHBOARD_USER", "admin"),
        password=os.environ.get("VMCP_OPERATOR_DASHBOARD_PASSWORD", ""),
    )
    if not auth.password:
        raise SystemExit("VMCP_OPERATOR_DASHBOARD_PASSWORD is required when dashboard enabled")

    class _EmptyGateways:
        async def get(self, key: Any) -> None:
            return None

        async def list_all(self) -> list[Any]:
            return []

    catalog_mode = os.environ.get("VMCP_OPERATOR_MCP_CATALOG", "kr8s").lower()
    if catalog_mode in {"memory", "inmemory", "stub"}:
        gateways: Any = _EmptyGateways()
        catalog: Any = InMemoryMcpCatalog()
    else:
        gateways = Kr8sGatewayRepository()
        catalog = Kr8sMcpCatalog()
    control = build_control_plane(gateways=gateways, catalog=catalog)

    app = create_app(
        auth=auth,
        list_environments=ListEnvironments(gateways=gateways, phases={}),
        issue_use_token=IssueUseToken(gateways=gateways, issuer=_DeniedIssuer()),
        list_mcps=control.list_mcps,
        get_mcp=control.get_mcp,
        add_mcp=control.add_mcp,
        update_mcp=control.update_mcp,
        remove_mcp=control.remove_mcp,
        nl_crud=control.nl_crud,
    )
    port = int(os.environ.get("VMCP_OPERATOR_DASHBOARD_PORT", "8080"))

    async def _serve() -> None:  # pragma: no cover - aiohttp event loop
        from aiohttp import web

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=port)
        await site.start()
        await asyncio.Event().wait()

    loop = asyncio.new_event_loop()

    def _runner() -> None:  # pragma: no cover - thread target
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_serve())

    import threading

    threading.Thread(target=_runner, name="vmcp-dashboard", daemon=True).start()


if __name__ == "__main__":
    main()
