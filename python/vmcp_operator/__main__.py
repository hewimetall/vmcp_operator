"""Console entrypoint."""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Start the operator with eager handler wiring."""
    os.environ.setdefault("PYTHON_LAZY_IMPORTS", "normal")
    if sys._is_gil_enabled():
        raise SystemExit("vmcp-operator requires free-threaded CPython (GIL is enabled)")

    from vmcp_operator.wiring import wire

    wire()

    import kopf

    kopf.run(clusterwide=False)


if __name__ == "__main__":
    main()
