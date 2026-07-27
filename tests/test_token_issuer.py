from __future__ import annotations

import pytest
from tests.test_vmcp_api_client import Transport, _patch_client

from vmcp_operator.adapters.driven.vmcp_api.client import VmcpApiClient
from vmcp_operator.adapters.driven.vmcp_api.token_issuer import VmcpTokenIssuer
from vmcp_operator.domain.models.gateway import GatewayKey


@pytest.mark.asyncio
async def test_token_issuer_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = Transport()
    _patch_client(monkeypatch, transport)
    issuer = VmcpTokenIssuer(
        client_for=lambda _key: VmcpApiClient(base_url="http://vmcp", admin_token="secret")
    )
    token = await issuer.issue_use_token(GatewayKey("team-a", "main"), "cursor")
    assert token == "tok-cursor"
