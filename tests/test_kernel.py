from __future__ import annotations

import runpy
import sys

import pytest

from vmcp_operator import _kernel


def test_extension_keeps_free_threading_enabled() -> None:
    assert sys._is_gil_enabled() is False


def test_sha256_boundary_accepts_python_bytes() -> None:
    assert (
        _kernel.sha256_hex(b"vmcp-operator")
        == "a78dc5576bf47b2fc53a63ee91392950bc99054b4a084b88d4c2843ba0352d58"
    )


def test_module_execution_delegates_to_main() -> None:
    with pytest.raises(SystemExit, match="runtime is not wired yet"):
        runpy.run_module("vmcp_operator.__main__", run_name="__main__")


def test_unwired_entrypoint_fails_explicitly() -> None:
    from vmcp_operator.__main__ import main

    with pytest.raises(SystemExit, match="runtime is not wired yet"):
        main()
