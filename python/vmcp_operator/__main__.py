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
    from vmcp_operator.adapters.driving.dashboard.app import DashboardAuth, create_app
    from vmcp_operator.domain.usecases.issue_use_token import IssueUseToken
    from vmcp_operator.domain.usecases.list_environments import ListEnvironments

    class _EmptyGateways:
        async def get(self, key: Any) -> None:
            return None

        async def list_all(self) -> list[Any]:
            return []

    class _DeniedIssuer:
        async def issue_use_token(self, key: Any, client_name: str) -> str:
            raise LookupError("dashboard token issuer not configured")

    auth = DashboardAuth(
        username=os.environ.get("VMCP_OPERATOR_DASHBOARD_USER", "admin"),
        password=os.environ.get("VMCP_OPERATOR_DASHBOARD_PASSWORD", ""),
    )
    if not auth.password:
        raise SystemExit("VMCP_OPERATOR_DASHBOARD_PASSWORD is required when dashboard enabled")

    app = create_app(
        auth=auth,
        list_environments=ListEnvironments(gateways=_EmptyGateways(), phases={}),
        issue_use_token=IssueUseToken(gateways=_EmptyGateways(), issuer=_DeniedIssuer()),
    )
    port = int(os.environ.get("VMCP_OPERATOR_DASHBOARD_PORT", "8080"))

    async def _serve() -> None:
        from aiohttp import web

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=port)
        await site.start()
        await asyncio.Event().wait()

    loop = asyncio.new_event_loop()

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_serve())

    import threading

    threading.Thread(target=_runner, name="vmcp-dashboard", daemon=True).start()


if __name__ == "__main__":
    main()
