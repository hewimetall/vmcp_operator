"""Console entrypoint."""

from __future__ import annotations


def main() -> None:
    """Start the operator.

    Runtime wiring lands after the Python 3.15t compatibility gate. Keeping
    this entrypoint import-light prevents accidental eager framework startup.
    """
    raise SystemExit("vmcp-operator runtime is not wired yet")


if __name__ == "__main__":
    main()
