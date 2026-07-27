"""Deterministic rollout checksums for managed MCP workloads."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def managed_workload_checksum(
    *,
    image: str,
    env: tuple[tuple[str, str], ...],
    ports: tuple[tuple[str, int], ...],
    mcp_path: str,
) -> str:
    """Hash the fields that must trigger a rollout when changed."""
    payload = {
        "image": image,
        "env": sorted(env),
        "ports": sorted(ports),
        "mcp_path": mcp_path,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def annotate_checksum(metadata: dict[str, Any], checksum: str) -> dict[str, Any]:
    annotations = dict(metadata.get("annotations") or {})
    annotations["vmcp.io/workload-checksum"] = checksum
    return {**metadata, "annotations": annotations}
