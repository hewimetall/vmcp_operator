from __future__ import annotations

from typing import Any

import pytest

from vmcp_operator.adapters.driven.k8s.secret_loader import (
    Kr8sSecretValueLoader,
    _decode_secret_value,
)
from vmcp_operator.domain.models.gateway import SecretRef


def test_decode_secret_value_base64_and_bytes() -> None:
    assert _decode_secret_value("aG9wLXNlY3JldC1saXZl") == "hop-secret-live"
    assert _decode_secret_value(b"plain") == "plain"
    assert _decode_secret_value("not-valid-b64!!!") == "not-valid-b64!!!"


@pytest.mark.asyncio
async def test_kr8s_secret_loader_reads_named_key(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSecret:
        def __init__(self, body: dict[str, Any], api: Any = None) -> None:
            self.raw = {
                "data": {"secret": "aG9wLXNlY3JldC1saXZl"},
                "metadata": body.get("metadata") or {},
            }
            self.api = api

        async def exists(self) -> bool:
            return True

        async def refresh(self) -> None:
            return None

    async def fake_api() -> object:
        return object()

    monkeypatch.setattr("kr8s.asyncio.objects.Secret", FakeSecret)
    monkeypatch.setattr("kr8s.asyncio.api", fake_api)
    value = await Kr8sSecretValueLoader().get(
        "team-a", SecretRef(name="main-forward-auth", key="secret")
    )
    assert value == "hop-secret-live"


@pytest.mark.asyncio
async def test_kr8s_secret_loader_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    class Missing:
        def __init__(self, body: dict[str, Any], api: Any = None) -> None:
            self.raw = {"metadata": body.get("metadata") or {}}
            self.api = api

        async def exists(self) -> bool:
            return False

        async def refresh(self) -> None:
            return None

    async def fake_api() -> object:
        return object()

    monkeypatch.setattr("kr8s.asyncio.objects.Secret", Missing)
    monkeypatch.setattr("kr8s.asyncio.api", fake_api)
    assert (
        await Kr8sSecretValueLoader().get("team-a", SecretRef(name="nope", key="secret"))
        is None
    )
