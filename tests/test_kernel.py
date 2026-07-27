from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from vmcp_operator import _kernel


def test_extension_keeps_free_threading_enabled() -> None:
    assert sys._is_gil_enabled() is False


def test_sha256_boundary_accepts_python_bytes() -> None:
    assert (
        _kernel.sha256_hex(b"vmcp-operator")
        == "a78dc5576bf47b2fc53a63ee91392950bc99054b4a084b88d4c2843ba0352d58"
    )


def test_main_wires_and_runs_kopf() -> None:
    from vmcp_operator.__main__ import main

    with (
        patch("vmcp_operator.wiring.wire") as wire,
        patch("kopf.run") as run,
    ):
        main()
        wire.assert_called_once()
        run.assert_called_once_with(clusterwide=False)


def test_main_rejects_gil_runtime() -> None:
    from vmcp_operator.__main__ import main

    with (
        patch("sys._is_gil_enabled", return_value=True),
        pytest.raises(SystemExit, match="free-threaded"),
    ):
        main()


def test_main_module_guard_invokes_main() -> None:
    import vmcp_operator.__main__ as main_mod

    with patch.object(main_mod, "main") as mocked:
        main_mod.main()
        mocked.assert_called_once()
