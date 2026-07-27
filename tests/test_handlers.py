from __future__ import annotations

from types import SimpleNamespace

import pytest

from vmcp_operator.adapters.driving.k8s import handlers


@pytest.mark.asyncio
async def test_configure_startup_settings() -> None:
    settings = SimpleNamespace(
        posting=SimpleNamespace(enabled=False),
        watching=SimpleNamespace(server_timeout=0),
    )
    await handlers.configure(settings)
    assert settings.posting.enabled is True
    assert settings.watching.server_timeout == 60


@pytest.mark.asyncio
async def test_reconcile_gateway_and_mcp_handlers() -> None:
    gw = await handlers.reconcile_gateway(
        namespace="team-a",
        name="main",
        spec={"image": "harbor.example.com/ai/vmcp:1"},
    )
    assert gw["phase"] == "Observed"
    assert gw["gateway"] == "team-a/main"

    mcp = await handlers.reconcile_mcp(
        namespace="team-a",
        name="docs",
        spec={"gatewayRef": {"name": "main"}, "source": {"type": "RemoteHttp"}},
    )
    assert mcp["gateway"] == "team-a/main"
