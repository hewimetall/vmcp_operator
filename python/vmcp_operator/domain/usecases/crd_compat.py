"""Detect operator image vs VmcpGateway CRD schema skew (issue #8)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Fields this image understands; older CRDs prune them with no API error.
REQUIRED_VMCPGATEWAY_SPEC = (
    ("identityStrip",),
    ("adminRoute", "path"),
    ("publicRoute", "path"),
    ("extraRoutes",),
    ("gql", "gcf"),
    ("proxy", "gcf"),
)
REQUIRED_VMCPGATEWAY_STATUS = (
    ("listenerPolicy",),
    ("observedGeneration",),
    ("crdSkew",),
)


def missing_vmcpgateway_crd_fields(crd: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Return dotted spec./status. paths absent from the storage version schema."""
    if not crd:
        return ("<crd-missing>",)
    versions = (crd.get("spec") or {}).get("versions") or ()
    storage = next((item for item in versions if item.get("storage")), None)
    if not isinstance(storage, Mapping):
        return ("<no-storage-version>",)
    schema = ((storage.get("schema") or {}).get("openAPIV3Schema") or {}).get("properties") or {}
    spec_props = ((schema.get("spec") or {}).get("properties") or {})
    status_props = ((schema.get("status") or {}).get("properties") or {})
    missing: list[str] = []
    for path in REQUIRED_VMCPGATEWAY_SPEC:
        if not _has_path(spec_props, path):
            missing.append("spec." + ".".join(path))
    for path in REQUIRED_VMCPGATEWAY_STATUS:
        if not _has_path(status_props, path):
            missing.append("status." + ".".join(path))
    return tuple(missing)


def _has_path(properties: Mapping[str, Any], path: tuple[str, ...]) -> bool:
    node: Any = properties
    for i, key in enumerate(path):
        if not isinstance(node, Mapping) or key not in node:
            return False
        node = node[key]
        if i < len(path) - 1:
            node = (node or {}).get("properties") or {}
    return True
