from __future__ import annotations

from typing import Any

import pytest

from vmcp_operator.adapters.driven.k8s.kr8s_applier import Kr8sServerSideApplier, _guess_plural
from vmcp_operator.adapters.driven.k8s.ssa import ConflictError


class FakeObj:
    def __init__(self, body: dict[str, Any], api: Any = None) -> None:
        self.raw = dict(body)
        self.api = api
        self._exists = False
        self.created = False
        self.fail_apply_without_force = False

    async def exists(self) -> bool:
        return self._exists

    async def create(self) -> None:
        self.created = True
        self._exists = True

    async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
        if (
            kwargs.get("type") == "apply"
            and not kwargs.get("force")
            and self.fail_apply_without_force
        ):
            raise RuntimeError("conflict from field manager")
        self.raw = dict(body)
        self._exists = True

    async def refresh(self) -> None:
        return None


@pytest.mark.asyncio
async def test_kr8s_applier_create_and_conflict_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    current: dict[str, FakeObj] = {}

    def fake_new_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> FakeObj:
            key = body["metadata"]["name"]
            if key not in current:
                current[key] = FakeObj(body, api=api)
            else:
                current[key].raw = dict(body)
            return current[key]

        return ctor

    async def fake_api() -> object:
        return object()

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        fake_new_class,
    )
    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.kr8s.asyncio.api",
        fake_api,
    )

    applier = Kr8sServerSideApplier()
    body = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "demo", "namespace": "default"},
        "data": {"a": "1"},
    }
    out = await applier.server_side_apply(body, field_manager="fm", force=False)
    assert out["metadata"]["name"] == "demo"
    assert current["demo"].created is True

    current["demo"].fail_apply_without_force = True
    with pytest.raises(ConflictError):
        await applier.server_side_apply(body, field_manager="fm", force=False)

    out2 = await applier.server_side_apply(body, field_manager="fm", force=True)
    assert out2["data"]["a"] == "1"


def test_guess_plural_and_requires_name() -> None:
    assert _guess_plural("ConfigMap") == "configmaps"
    assert _guess_plural("Ingress") == "ingresses"
    assert _guess_plural("Policy") == "policies"


@pytest.mark.asyncio
async def test_kr8s_applier_requires_name_and_fallback_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_api() -> object:
        return object()

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.kr8s.asyncio.api",
        fake_api,
    )
    applier = Kr8sServerSideApplier(api=object())
    with pytest.raises(ValueError, match=r"metadata\.name"):
        await applier.server_side_apply(
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {}},
            field_manager="fm",
            force=False,
        )

    class FallbackObj(FakeObj):
        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            if kwargs.get("type") == "apply":
                raise RuntimeError("apply unsupported")
            self.raw = dict(body)
            self._exists = True

    def fake_new_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> FallbackObj:
            obj = FallbackObj(body, api=api)
            obj._exists = True
            return obj

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        fake_new_class,
    )
    out = await applier.server_side_apply(
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "x", "namespace": "ns"},
        },
        field_manager="fm",
        force=False,
    )
    assert out["metadata"]["name"] == "x"

    class ConflictFallback(FakeObj):
        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            raise RuntimeError("conflict forever")

    def conflict_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> ConflictFallback:
            obj = ConflictFallback(body, api=api)
            obj._exists = True
            return obj

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        conflict_class,
    )
    with pytest.raises(ConflictError):
        await applier.server_side_apply(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "y", "namespace": "ns"},
            },
            field_manager="fm",
            force=False,
        )
