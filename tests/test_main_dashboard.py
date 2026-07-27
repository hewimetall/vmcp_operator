from __future__ import annotations

from unittest.mock import patch

import pytest


def test_main_requires_dashboard_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMCP_OPERATOR_DASHBOARD_ENABLED", "true")
    monkeypatch.delenv("VMCP_OPERATOR_DASHBOARD_PASSWORD", raising=False)
    from vmcp_operator.__main__ import main

    with (
        patch("vmcp_operator.wiring.wire"),
        pytest.raises(SystemExit, match="DASHBOARD_PASSWORD"),
    ):
        main()


def test_main_starts_dashboard_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMCP_OPERATOR_DASHBOARD_ENABLED", "1")
    monkeypatch.setenv("VMCP_OPERATOR_DASHBOARD_PASSWORD", "secret")
    from vmcp_operator.__main__ import main

    with (
        patch("vmcp_operator.wiring.wire"),
        patch("vmcp_operator.__main__._start_dashboard_background") as dash,
        patch("kopf.run") as run,
    ):
        main()
        dash.assert_called_once()
        run.assert_called_once_with(clusterwide=False)


def test_start_dashboard_background_spawns_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VMCP_OPERATOR_DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("VMCP_OPERATOR_DASHBOARD_PORT", "18080")
    from vmcp_operator.__main__ import _start_dashboard_background

    with patch("threading.Thread") as thread_cls:
        _start_dashboard_background()
        thread_cls.assert_called_once()
        kwargs = thread_cls.call_args.kwargs
        assert kwargs["daemon"] is True
        assert kwargs["name"] == "vmcp-dashboard"
        thread_cls.return_value.start.assert_called_once()
