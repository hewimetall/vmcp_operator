"""Map reconcile outcomes onto CRD-declared status fields via Kopf ``patch``."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from typing import Any


def apply_status(
    patch: Any,
    *,
    phase: str,
    generation: int | None,
    artifact_sha256: str | None = None,
    reason: str | None = None,
    message: str | None = None,
    ready: bool | None = None,
    listener_policy: Mapping[str, Any] | None = None,
    crd_skew: tuple[str, ...] | None = None,
) -> None:
    """Write top-level ``status`` fields accepted by the Vmcp* CRD schemas.

    Kopf stores bare handler return values under ``status.<handler_name>``, which
    structural schemas prune. Always use this helper (or equivalent ``patch.status``
    writes) instead of returning a status dict.
    """
    status = _status_mapping(patch)
    status["phase"] = phase
    if generation is not None:
        status["observedGeneration"] = int(generation)
    if artifact_sha256 is not None:
        status["artifactSha256"] = artifact_sha256
    if listener_policy is not None:
        status["listenerPolicy"] = dict(listener_policy)
    if crd_skew is not None:
        status["crdSkew"] = list(crd_skew)

    if ready is None:
        ready = phase in {"Applied", "Registered", "Finalized"}
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    conditions: list[dict[str, Any]] = [
        {
            "type": "Ready",
            "status": "True" if ready else "False",
            "reason": reason or phase,
            "message": message or phase,
            "lastTransitionTime": now,
        }
    ]
    if crd_skew is not None:
        conditions.append(
            {
                "type": "CRDsReady",
                "status": "False" if crd_skew else "True",
                "reason": "SchemaSkew" if crd_skew else "Current",
                "message": (
                    "API will prune: " + ", ".join(crd_skew)
                    if crd_skew
                    else "VmcpGateway CRD matches this operator image"
                ),
                "lastTransitionTime": now,
            }
        )
    status["conditions"] = conditions


def generation_of(meta: Mapping[str, Any] | None, body: Mapping[str, Any] | None = None) -> int:
    if meta and meta.get("generation") is not None:
        return int(meta["generation"])
    if body:
        nested = (body.get("metadata") or {}).get("generation")
        if nested is not None:
            return int(nested)
    return 0


def _status_mapping(patch: Any) -> MutableMapping[str, Any]:
    status = getattr(patch, "status", None)
    if status is None:
        # Plain dict patches used in unit tests.
        if isinstance(patch, MutableMapping):
            nested = patch.setdefault("status", {})
            if not isinstance(nested, MutableMapping):
                raise TypeError("patch.status must be a mutable mapping")
            return nested
        raise TypeError("patch must expose a mutable .status mapping")
    if not isinstance(status, MutableMapping):
        # Kopf Patch.status behaves like a mutable mapping.
        return status  # type: ignore[return-value]
    return status


__all__ = ["apply_status", "generation_of"]
