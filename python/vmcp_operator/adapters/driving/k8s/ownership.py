"""Attach Kubernetes ownerReferences without requiring a Kopf handling context."""

from __future__ import annotations

from typing import Any, Mapping


def build_owner_reference(owner: Mapping[str, Any]) -> dict[str, Any]:
    meta = owner.get("metadata") or {}
    api_version = owner.get("apiVersion")
    kind = owner.get("kind")
    name = meta.get("name")
    uid = meta.get("uid")
    if not api_version or not kind or not name or not uid:
        raise ValueError(
            "owner must include apiVersion, kind, metadata.name, and metadata.uid"
        )
    return {
        "apiVersion": str(api_version),
        "kind": str(kind),
        "name": str(name),
        "uid": str(uid),
        "controller": True,
        "blockOwnerDeletion": True,
    }


def attach_owner(obj: dict[str, Any], owner: Mapping[str, Any]) -> dict[str, Any]:
    """Idempotently set a controller ownerReference on ``obj``."""
    ref = build_owner_reference(owner)
    meta = obj.setdefault("metadata", {})
    refs = list(meta.get("ownerReferences") or [])
    uid = ref["uid"]
    refs = [item for item in refs if str(item.get("uid")) != uid]
    refs.append(ref)
    meta["ownerReferences"] = refs
    return obj


__all__ = ["attach_owner", "build_owner_reference"]
