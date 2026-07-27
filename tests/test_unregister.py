from __future__ import annotations

import pytest
from tests.test_vmcp_api_client import Transport, _patch_client

from vmcp_operator.adapters.driven.vmcp_api.client import VmcpApiClient
from vmcp_operator.adapters.driven.vmcp_api.unregister import UnregisterUpstream


@pytest.mark.asyncio
async def test_unregister_filters_and_reloads(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = Transport()
    transport.reload_payload = {
        "sha256": "deadbeef",
        "upstreams": ["context7", "tavily"],
    }
    _patch_client(monkeypatch, transport)
    client = VmcpApiClient(base_url="http://vmcp", admin_token="secret")
    ok = await UnregisterUpstream(client=client).execute(
        upstream_name="architect-c4",
        desired_sha256="deadbeef",
    )
    assert ok is True
