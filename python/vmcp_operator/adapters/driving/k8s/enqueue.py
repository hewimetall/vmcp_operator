"""Extract Gateway keys from labeled child objects for reconcile enqueue."""

from __future__ import annotations

from typing import Any

from vmcp_operator.domain.models.gateway import GatewayKey

GATEWAY_LABEL = "vmcp.io/gateway"


def gateway_key_from_labels(
    namespace: str,
    labels: dict[str, str] | None,
) -> GatewayKey | None:
    if not labels:
        return None
    name = labels.get(GATEWAY_LABEL)
    if not name:
        return None
    return GatewayKey(namespace=namespace, name=name)


def gateway_key_from_owner(
    namespace: str,
    annotations: dict[str, str] | None = None,
    labels: dict[str, str] | None = None,
) -> GatewayKey | None:
    key = gateway_key_from_labels(namespace, labels)
    if key is not None:
        return key
    if annotations and "vmcp.io/gateway-key" in annotations:
        raw = annotations["vmcp.io/gateway-key"]
        if "/" in raw:
            ns, name = raw.split("/", 1)
            return GatewayKey(namespace=ns, name=name)
    return None


def should_enqueue_child(body: dict[str, Any]) -> GatewayKey | None:
    metadata = body.get("metadata") or {}
    namespace = str(metadata.get("namespace") or "")
    if not namespace:
        return None
    labels = metadata.get("labels") or {}
    annotations = metadata.get("annotations") or {}
    if not isinstance(labels, dict) or not isinstance(annotations, dict):
        return None
    return gateway_key_from_owner(
        namespace,
        annotations={str(k): str(v) for k, v in annotations.items()},
        labels={str(k): str(v) for k, v in labels.items()},
    )
