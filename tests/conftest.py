"""Unit-test defaults: never hit a live API server from handler startup."""

from __future__ import annotations

import pytest

from vmcp_operator.adapters.driving.k8s import handlers


@pytest.fixture(autouse=True)
def _skip_live_crd_inspect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMCP_OPERATOR_SKIP_CRD_CHECK", "1")
    handlers.CRD_SKEW = ()
    yield
    handlers.CRD_SKEW = ()
