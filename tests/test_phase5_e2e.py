from __future__ import annotations

import os
from pathlib import Path

import pytest

# Ensure in-memory mode for unit CI (no cluster required).
os.environ.pop("KUBECONFIG", None)


@pytest.mark.asyncio
async def test_phase5_api_e2e_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = tmp_path / "phase5.json"
    monkeypatch.setenv("VMCP_PHASE5_RESULT", str(result))
    monkeypatch.delenv("KUBECONFIG", raising=False)

    from scripts.phase5_kwok_e2e import main

    assert await main() == 0
    payload = result.read_text(encoding="utf-8")
    assert "team-a/resurche" in payload
    assert "team-a/code" in payload
    assert "team-a/other" in payload
    assert "levelReconcileRecovered" in payload
    assert "http://code.team-a.svc:8080/mcp-proxy" in payload
    assert '"vmcpProxyInRegistry": true' in payload
