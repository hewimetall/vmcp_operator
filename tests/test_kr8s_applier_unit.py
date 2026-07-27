from __future__ import annotations

from typing import Any

import pytest
from kr8s._exceptions import NotFoundError

from vmcp_operator.adapters.driven.k8s.kr8s_applier import Kr8sServerSideApplier, _guess_plural
from vmcp_operator.adapters.driven.k8s.ssa import ConflictError


class FakeObj:
    def __init__(self, body: dict[str, Any], api: Any = None) -> None:
        self.raw = dict(body)
        self.api = api
        self._exists = False
        self.created = False
        self.fail_apply_without_force = False
        self.raise_not_found_on_exists = False

    async def exists(self) -> bool:
        if self.raise_not_found_on_exists:
            raise NotFoundError("missing")
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


@pytest.mark.asyncio
async def test_kr8s_applier_string_not_found_and_inner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_api() -> object:
        return object()

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.kr8s.asyncio.api",
        fake_api,
    )

    class StringNotFound(FakeObj):
        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            if kwargs.get("type") == "apply":
                raise RuntimeError("object not found")
            raise RuntimeError("not found again")

    def nf_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> StringNotFound:
            obj = StringNotFound(body, api=api)
            obj._exists = True
            return obj

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        nf_class,
    )
    applier = Kr8sServerSideApplier(api=object())
    out = await applier.server_side_apply(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "nf", "namespace": "ns"},
        },
        field_manager="fm",
        force=False,
    )
    assert out["metadata"]["name"] == "nf"

    class InnerNotFound(FakeObj):
        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            if kwargs.get("type") == "apply":
                raise RuntimeError("apply unsupported")
            raise RuntimeError("resource not found")

    def inner_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> InnerNotFound:
            obj = InnerNotFound(body, api=api)
            obj._exists = True
            return obj

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        inner_class,
    )
    out2 = await applier.server_side_apply(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "nf2", "namespace": "ns"},
        },
        field_manager="fm",
        force=False,
    )
    assert out2["metadata"]["name"] == "nf2"


@pytest.mark.asyncio
async def test_kr8s_applier_not_found_creates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_api() -> object:
        return object()

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.kr8s.asyncio.api",
        fake_api,
    )

    def fake_new_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> FakeObj:
            obj = FakeObj(body, api=api)
            obj._exists = True
            obj.fail_apply_without_force = False

            async def boom_patch(body: dict[str, Any], **kwargs: Any) -> None:
                raise NotFoundError("gone")

            obj.patch = boom_patch  # type: ignore[method-assign]
            return obj

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        fake_new_class,
    )
    applier = Kr8sServerSideApplier(api=object())
    out = await applier.server_side_apply(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "x", "namespace": "ns"},
            "data": {"k": "v"},
        },
        field_manager="fm",
        force=False,
    )
    assert out["metadata"]["name"] == "x"


def test_guess_plural_and_requires_name() -> None:
    assert _guess_plural("ConfigMap") == "configmaps"
    assert _guess_plural("Ingress") == "ingresses"
    assert _guess_plural("Policy") == "policies"


@pytest.mark.asyncio
async def test_kr8s_applier_requires_name(monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.mark.asyncio
async def test_kr8s_applier_conflict_and_plain_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_api() -> object:
        return object()

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.kr8s.asyncio.api",
        fake_api,
    )

    class ConflictThenPlain(FakeObj):
        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            if kwargs.get("type") == "apply" and not kwargs.get("force"):
                raise RuntimeError("apply unsupported")
            if kwargs.get("type") == "apply" and kwargs.get("force"):
                raise RuntimeError("conflict forever")
            self.raw = dict(body)

    def fake_new_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> ConflictThenPlain:
            obj = ConflictThenPlain(body, api=api)
            obj._exists = True
            return obj

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        fake_new_class,
    )
    applier = Kr8sServerSideApplier(api=object())
    body = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "y", "namespace": "ns"},
        "data": {"a": "1"},
    }
    # apply unsupported → plain patch succeeds
    out = await applier.server_side_apply(body, field_manager="fm", force=False)
    assert out["data"]["a"] == "1"

    class ConflictAll(FakeObj):
        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            raise RuntimeError("conflict forever")

    def conflict_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> ConflictAll:
            obj = ConflictAll(body, api=api)
            obj._exists = True
            return obj

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        conflict_class,
    )
    with pytest.raises(ConflictError):
        await applier.server_side_apply(body, field_manager="fm", force=False)
