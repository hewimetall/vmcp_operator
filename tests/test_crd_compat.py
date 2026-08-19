from __future__ import annotations

from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml

from vmcp_operator.adapters.driving.k8s import handlers
from vmcp_operator.domain.usecases.crd_compat import missing_vmcpgateway_crd_fields


def _install_fake_kr8s(
    monkeypatch: pytest.MonkeyPatch,
    *,
    obj_cls: type[Any],
    api_error: Exception | None = None,
) -> None:
    import sys

    kr8s_mod = ModuleType("kr8s")
    asyncio_mod = ModuleType("kr8s.asyncio")
    objects_mod = ModuleType("kr8s.asyncio.objects")

    async def _api() -> object:
        if api_error is not None:
            raise api_error
        return object()

    asyncio_mod.api = _api  # type: ignore[attr-defined]
    objects_mod.new_class = lambda **_: obj_cls  # type: ignore[attr-defined]
    kr8s_mod.asyncio = asyncio_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kr8s", kr8s_mod)
    monkeypatch.setitem(sys.modules, "kr8s.asyncio", asyncio_mod)
    monkeypatch.setitem(sys.modules, "kr8s.asyncio.objects", objects_mod)


def test_shipped_gateway_crd_matches_operator_image() -> None:
    from pathlib import Path

    crd = yaml.safe_load(
        Path("charts/vmcp-operator/crds/vmcpgateway.yaml").read_text(encoding="utf-8")
    )
    assert missing_vmcpgateway_crd_fields(crd) == ()


def test_missing_crd_fields_on_old_schema() -> None:
    crd = {
        "spec": {
            "versions": [
                {
                    "storage": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "properties": {
                                "spec": {"properties": {"image": {"type": "string"}}},
                                "status": {"properties": {"phase": {"type": "string"}}},
                            }
                        }
                    },
                }
            ]
        }
    }
    missing = missing_vmcpgateway_crd_fields(crd)
    assert "spec.identityStrip" in missing
    assert "spec.gql.gcf" in missing
    assert "spec.extraRoutes" in missing
    assert "spec.publicRoute.path" in missing
    assert "status.listenerPolicy" in missing
    assert "status.crdSkew" in missing


def test_missing_crd_when_absent_or_no_storage() -> None:
    assert missing_vmcpgateway_crd_fields(None) == ("<crd-missing>",)
    assert missing_vmcpgateway_crd_fields({"spec": {"versions": []}}) == (
        "<no-storage-version>",
    )


@pytest.mark.asyncio
async def test_inspect_gateway_crd_honours_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VMCP_OPERATOR_SKIP_CRD_CHECK", "1")
    assert await handlers._inspect_gateway_crd() == ()


@pytest.mark.asyncio
async def test_inspect_gateway_crd_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VMCP_OPERATOR_SKIP_CRD_CHECK", raising=False)

    class _Obj:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.raw: dict[str, Any] = {}

        async def exists(self) -> bool:
            return False

        async def refresh(self) -> None:
            return None

    _install_fake_kr8s(monkeypatch, obj_cls=_Obj)
    assert await handlers._inspect_gateway_crd() == ("<crd-missing>",)


@pytest.mark.asyncio
async def test_inspect_gateway_crd_schema_skew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VMCP_OPERATOR_SKIP_CRD_CHECK", raising=False)
    old = {
        "spec": {
            "versions": [
                {
                    "storage": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "properties": {
                                "spec": {"properties": {"image": {"type": "string"}}},
                                "status": {"properties": {"phase": {"type": "string"}}},
                            }
                        }
                    },
                }
            ]
        }
    }

    class _Obj:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.raw = old

        async def exists(self) -> bool:
            return True

        async def refresh(self) -> None:
            return None

    _install_fake_kr8s(monkeypatch, obj_cls=_Obj)
    missing = await handlers._inspect_gateway_crd()
    assert "spec.identityStrip" in missing
    assert "spec.extraRoutes" in missing


@pytest.mark.asyncio
async def test_inspect_gateway_crd_exception_is_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VMCP_OPERATOR_SKIP_CRD_CHECK", raising=False)

    class _Obj:
        def __init__(self, *_: Any, **__: Any) -> None:
            return None

    _install_fake_kr8s(monkeypatch, obj_cls=_Obj, api_error=RuntimeError("no cluster"))
    assert await handlers._inspect_gateway_crd() == ()


@pytest.mark.asyncio
async def test_configure_records_crd_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _skew() -> tuple[str, ...]:
        return ("spec.identityStrip",)

    monkeypatch.setattr(handlers, "_inspect_gateway_crd", _skew)
    settings = SimpleNamespace(
        posting=SimpleNamespace(enabled=False),
        watching=SimpleNamespace(server_timeout=0),
    )
    await handlers.configure(settings)
    assert handlers.CRD_SKEW == ("spec.identityStrip",)
    handlers.CRD_SKEW = ()

