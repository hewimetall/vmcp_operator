"""Document coverage expectations; CI enforces fail_under=98 in pyproject."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_coverage_fail_under_is_at_least_98() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    fail_under = data["tool"]["coverage"]["report"]["fail_under"]
    assert fail_under >= 98
