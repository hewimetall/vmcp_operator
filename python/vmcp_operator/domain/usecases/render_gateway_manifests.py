"""Render desired Kubernetes manifests for one VmcpGateway (pure data)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vmcp_operator.domain.models.artifacts import ArtifactBundle
from vmcp_operator.domain.models.gateway import (
    PUBLIC_STRIP_IDENTITY_HEADERS,
    GatewayDesired,
    GatewayParentRef,
)
from vmcp_operator.domain.models.mcp import (
    McpServerDesired,
    RemoteHttpSource,
    VmcpProxySource,
)
from vmcp_operator.domain.usecases.render_gateway_config import render_gateway_config

# Any retained for Kubernetes object dictionaries only.


@dataclass(frozen=True, slots=True)
class RenderGatewayManifests:
    """Build child object dicts. Apply/SSA belongs in driven adapters."""

    def execute(
        self,
        gateway: GatewayDesired,
        artifacts: ArtifactBundle,
        mcps: list[McpServerDesired] | None = None,
        *,
        forward_auth_header_value: str | None = None,
    ) -> list[dict[str, Any]]:
        ns = gateway.key.namespace
        name = gateway.key.name
        labels = {
            "app.kubernetes.io/name": "vmcp",
            "app.kubernetes.io/instance": name,
            "vmcp.io/gateway": name,
        }
        pvc = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": f"{name}-state", "namespace": ns, "labels": labels},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": gateway.persistence.size}},
                "volumeMode": "Filesystem",
            },
        }
        if gateway.persistence.storage_class_name:
            pvc["spec"]["storageClassName"] = gateway.persistence.storage_class_name
        # Retain is expressed via StorageClass/PV lifecycle; annotate intent.
        pvc["metadata"]["annotations"] = {
            "vmcp.io/reclaim-policy": gateway.persistence.reclaim_policy,
        }

        # ConfigMap keys cannot contain '/'; flatten path → key with '__'.
        cm_data = {
            flatten_configmap_key(path): file.data for path, file in artifacts.files.items()
        }
        cm_data["vmcp.toml"] = render_gateway_config(gateway)
        configmap = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": f"{name}-artifacts",
                "namespace": ns,
                "labels": labels,
                "annotations": {
                    "vmcp.io/bundle-sha256": artifacts.bundle_sha256,
                    "vmcp.io/registry-sha256": artifacts.registry_sha256,
                    "vmcp.io/key-encoding": "slash-as-double-underscore",
                    "vmcp.io/contract": "vmcp-v1.2",
                },
            },
            "data": cm_data,
        }

        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": ns, "labels": labels},
            "spec": {
                "type": "ClusterIP",
                "selector": labels,
                "ports": [
                    {"name": "http", "port": 8080, "targetPort": "http"},
                ],
            },
        }

        env = _gateway_env(gateway, mcps or [])
        volumes = [
            {
                "name": "artifacts-raw",
                "configMap": {"name": f"{name}-artifacts"},
            },
            {"name": "artifacts", "emptyDir": {}},
            {
                "name": "state",
                "persistentVolumeClaim": {"claimName": f"{name}-state"},
            },
            {
                "name": "admin-tokens",
                "secret": {
                    "secretName": gateway.admin_token_secret_ref.name,
                    "items": [
                        {
                            "key": gateway.admin_token_secret_ref.key,
                            "path": "tokens.json",
                        }
                    ],
                },
            },
        ]
        volume_mounts = [
            {"name": "artifacts", "mountPath": "/config"},
            {"name": "state", "mountPath": "/state"},
            {
                "name": "admin-tokens",
                "mountPath": "/secrets",
                "readOnly": True,
            },
        ]

        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": ns, "labels": labels},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {
                        "labels": labels,
                        "annotations": {
                            "vmcp.io/bundle-sha256": artifacts.bundle_sha256,
                        },
                    },
                    "spec": {
                        # Avoid kubelet Service env (VMCP_PORT=tcp://…) clobbering vmcp settings
                        # when the Gateway/Service is named `vmcp` (issue #4 Gap 3).
                        "enableServiceLinks": False,
                        "initContainers": [
                            {
                                "name": "expand-artifacts",
                                "image": gateway.image,
                                "command": ["sh", "-c"],
                                "args": [
                                    "set -eu; "
                                    "mkdir -p /config; "
                                    "for f in /config-raw/*; do "
                                    "  base=$(basename \"$f\"); "
                                    "  rel=$(printf '%s' \"$base\" | sed 's#__#/#g'); "
                                    "  mkdir -p \"/config/$(dirname \"$rel\")\"; "
                                    "  cp \"$f\" \"/config/$rel\"; "
                                    "done"
                                ],
                                "volumeMounts": [
                                    {"name": "artifacts-raw", "mountPath": "/config-raw"},
                                    {"name": "artifacts", "mountPath": "/config"},
                                ],
                            }
                        ],
                        "containers": [
                            {
                                "name": "vmcp",
                                "image": gateway.image,
                                "ports": [{"name": "http", "containerPort": 8080}],
                                "env": env,
                                "volumeMounts": volume_mounts,
                            }
                        ],
                        "volumes": volumes,
                    },
                },
            },
        }

        public_rule: dict[str, Any] = {
            "matches": [{"path": {"type": "PathPrefix", "value": "/"}}],
            "backendRefs": [{"name": name, "port": 8080}],
        }
        public_filters = _public_strip_filters(gateway)
        if public_filters:
            public_rule["filters"] = public_filters

        public_route = {
            "apiVersion": "gateway.networking.k8s.io/v1",
            "kind": "HTTPRoute",
            "metadata": {
                "name": f"{name}-public",
                "namespace": ns,
                "labels": labels,
            },
            "spec": {
                "parentRefs": [_parent_ref(gateway.public_route.gateway_ref)],
                "hostnames": [gateway.public_route.hostname],
                "rules": [public_rule],
            },
        }
        if gateway.public_route.annotations:
            public_route["metadata"]["annotations"] = dict(gateway.public_route.annotations)

        manifests = [pvc, configmap, service, deployment, public_route]
        if gateway.admin_route is not None:
            admin_rule: dict[str, Any] = {
                "matches": [{"path": {"type": "PathPrefix", "value": "/admin"}}],
                "backendRefs": [{"name": name, "port": 8080}],
            }
            admin_filters = _admin_hop_filters(gateway, forward_auth_header_value)
            if admin_filters:
                admin_rule["filters"] = admin_filters
            admin_obj: dict[str, Any] = {
                "apiVersion": "gateway.networking.k8s.io/v1",
                "kind": "HTTPRoute",
                "metadata": {
                    "name": f"{name}-admin",
                    "namespace": ns,
                    "labels": labels,
                },
                "spec": {
                    "parentRefs": [_parent_ref(gateway.admin_route.gateway_ref)],
                    "hostnames": [gateway.admin_route.hostname],
                    "rules": [admin_rule],
                },
            }
            if gateway.admin_route.annotations:
                admin_obj["metadata"]["annotations"] = dict(gateway.admin_route.annotations)
            manifests.append(admin_obj)
        return manifests


def _public_strip_filters(gateway: GatewayDesired) -> list[dict[str, Any]]:
    if not gateway.public_route.strip_client_identity_headers:
        return []
    headers = list(PUBLIC_STRIP_IDENTITY_HEADERS)
    ak = gateway.auth.authentik
    for custom in (ak.username_header, ak.groups_header, ak.forward_auth_secret_header):
        # Preserve casing from the canonical list when possible; still strip customs.
        canon = next((h for h in headers if h.lower() == custom.lower()), None)
        if canon is None:
            headers.append(custom)
    # Deduplicate case-insensitively while keeping first spelling.
    seen: set[str] = set()
    remove: list[str] = []
    for header in headers:
        key = header.lower()
        if key in seen:
            continue
        seen.add(key)
        remove.append(header)
    return [
        {
            "type": "RequestHeaderModifier",
            "requestHeaderModifier": {"remove": remove},
        }
    ]


def _admin_hop_filters(
    gateway: GatewayDesired, forward_auth_header_value: str | None
) -> list[dict[str, Any]]:
    route = gateway.admin_route
    if route is None:
        return []
    want = route.inject_forward_auth_header
    secret_ref = gateway.auth.authentik.forward_auth_secret_ref
    if want is None:
        want = secret_ref is not None
    if not want:
        return []
    if not forward_auth_header_value:
        # Reconcile could not materialize the secret; omit set rather than mint empty hop.
        return []
    header = gateway.auth.authentik.forward_auth_secret_header or "x-vmcp-forward-auth"
    # Gateway API header names are typically canonicalized; use the configured spelling.
    return [
        {
            "type": "RequestHeaderModifier",
            "requestHeaderModifier": {
                "set": [{"name": header, "value": forward_auth_header_value}],
            },
        }
    ]


def _gateway_env(
    gateway: GatewayDesired, mcps: list[McpServerDesired]
) -> list[dict[str, Any]]:
    env: list[dict[str, Any]] = [
        {"name": "VMCP_CONFIG", "value": "/config/vmcp.toml"},
        {"name": "VMCP_REGISTRY_PATH", "value": "/config/registry.json"},
        {"name": "VMCP_SKILLS_DIR", "value": "/state/skills"},
        {
            "name": "VMCP_AUTH__MASTER_PASSWORD_ARGON2",
            "valueFrom": {
                "secretKeyRef": {
                    "name": gateway.master_password_secret_ref.name,
                    "key": gateway.master_password_secret_ref.key,
                }
            },
        },
    ]
    ak_secret = gateway.auth.authentik.forward_auth_secret_ref
    if ak_secret is not None:
        env.append(
            {
                "name": "VMCP_AUTH__AUTHENTIK__FORWARD_AUTH_SECRET",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": ak_secret.name,
                        "key": ak_secret.key,
                    }
                },
            }
        )
    for mcp in sorted(mcps, key=lambda item: item.name):
        if not mcp.enabled or mcp.gateway_key != gateway.key:
            continue
        source = mcp.source
        bearer_ref = None
        if isinstance(source, (RemoteHttpSource, VmcpProxySource)):
            bearer_ref = source.bearer_secret_ref
        if bearer_ref is not None:
            env_name = f"VMCP_BEARER_{mcp.name.upper().replace('-', '_')}"
            env.append(
                {
                    "name": env_name,
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": bearer_ref.name,
                            "key": bearer_ref.key,
                        }
                    },
                }
            )
    return env


def _parent_ref(ref: GatewayParentRef) -> dict[str, str]:
    out: dict[str, str] = {"name": ref.name}
    if ref.namespace:
        out["namespace"] = ref.namespace
    if ref.section_name:
        out["sectionName"] = ref.section_name
    return out


def flatten_configmap_key(path: str) -> str:
    """Encode nested artifact paths into legal ConfigMap keys."""
    if path != path.strip() or not path:
        raise ValueError("artifact path must be non-empty")
    return path.replace("/", "__")
