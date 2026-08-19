"""Render desired Kubernetes manifests for one VmcpGateway (pure data)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vmcp_operator.domain.models.artifacts import ArtifactBundle
from vmcp_operator.domain.models.gateway import (
    PUBLIC_STRIP_IDENTITY_HEADERS,
    GatewayDesired,
    GatewayParentRef,
    RouteDesired,
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
                    "vmcp.io/contract": "vmcp-v1.3",
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
        tokens_writable = gateway.admin_token_secret_ref.writable
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
        volume_mounts: list[dict[str, Any]] = [
            {"name": "artifacts", "mountPath": "/config"},
            {"name": "state", "mountPath": "/state"},
        ]
        if not tokens_writable:
            volume_mounts.append(
                {
                    "name": "admin-tokens",
                    "mountPath": "/secrets",
                    "readOnly": True,
                }
            )

        expand_script = (
            "set -eu; "
            "mkdir -p /config; "
            "for f in /config-raw/*; do "
            "  base=$(basename \"$f\"); "
            "  rel=$(printf '%s' \"$base\" | sed 's#__#/#g'); "
            "  mkdir -p \"/config/$(dirname \"$rel\")\"; "
            "  cp \"$f\" \"/config/$rel\"; "
            "done"
        )
        init_volume_mounts = [
            {"name": "artifacts-raw", "mountPath": "/config-raw"},
            {"name": "artifacts", "mountPath": "/config"},
        ]
        if tokens_writable:
            # Seed once: preserve Token CRUD writes across restarts.
            expand_script += (
                "; if [ ! -f /state/tokens.json ]; then "
                "cp /secrets-bootstrap/tokens.json /state/tokens.json; "
                "fi"
            )
            init_volume_mounts.extend(
                [
                    {"name": "admin-tokens", "mountPath": "/secrets-bootstrap", "readOnly": True},
                    {"name": "state", "mountPath": "/state"},
                ]
            )

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
                                "args": [expand_script],
                                "volumeMounts": init_volume_mounts,
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

        manifests: list[dict[str, Any]] = [pvc, configmap, service, deployment]
        if gateway.public_route.manage:
            public_rule: dict[str, Any] = {
                "matches": [
                    {"path": {"type": "PathPrefix", "value": gateway.public_route.path}}
                ],
                "backendRefs": [{"name": name, "port": 8080}],
            }
            public_filters = _route_filters(
                gateway,
                route=gateway.public_route,
                forward_auth_header_value=None,
                inject=False,
            )
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
            manifests.append(public_route)
        if gateway.admin_route is not None and gateway.admin_route.manage:
            admin_rule: dict[str, Any] = {
                "matches": [
                    {"path": {"type": "PathPrefix", "value": gateway.admin_route.path}}
                ],
                "backendRefs": [{"name": name, "port": 8080}],
            }
            admin_filters = _route_filters(
                gateway,
                route=gateway.admin_route,
                forward_auth_header_value=forward_auth_header_value,
                inject=True,
            )
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


def _identity_remove_headers(gateway: GatewayDesired) -> list[str]:
    headers = list(PUBLIC_STRIP_IDENTITY_HEADERS)
    ak = gateway.auth.authentik
    for custom in (ak.username_header, ak.groups_header, ak.forward_auth_secret_header):
        canon = next((h for h in headers if h.lower() == custom.lower()), None)
        if canon is None:
            headers.append(custom)
    seen: set[str] = set()
    remove: list[str] = []
    for header in headers:
        key = header.lower()
        if key in seen:
            continue
        seen.add(key)
        remove.append(header)
    return remove


def _wants_hop_inject(route: RouteDesired, gateway: GatewayDesired) -> bool:
    want = route.inject_forward_auth_header
    if want is None:
        return gateway.auth.authentik.forward_auth_secret_ref is not None
    return want


def _is_forward_auth_identity_header(gateway: GatewayDesired, header: str) -> bool:
    """Headers Authentik forward-auth (re)writes after HTTPRoute RHM in kgateway."""
    key = header.lower()
    if key.startswith("x-authentik-"):
        return True
    ak = gateway.auth.authentik
    return key in {ak.username_header.lower(), ak.groups_header.lower()}


def _strip_headers_for_route(
    gateway: GatewayDesired,
    route: RouteDesired,
    *,
    inject: bool,
    hop_header: str | None,
) -> list[str]:
    if not route.strip_client_identity_headers:
        return []
    headers = _identity_remove_headers(gateway)
    if inject and _wants_hop_inject(route, gateway):
        # HTTPRoute RequestHeaderModifier runs *after* kgateway extAuth
        # (issue #8). Stripping Authentik identity here undoes forward-auth.
        headers = [h for h in headers if not _is_forward_auth_identity_header(gateway, h)]
        if hop_header:
            hop = hop_header.lower()
            headers = [h for h in headers if h.lower() != hop]
    return headers


def _merge_request_header_modifier(
    remove: list[str],
    set_headers: list[dict[str, str]],
    add_headers: list[dict[str, str]],
) -> dict[str, Any] | None:
    """Gateway API allows at most one RequestHeaderModifier per HTTPRoute rule."""
    body: dict[str, Any] = {}
    if remove:
        body["remove"] = _dedupe_header_names(remove)
    if set_headers:
        body["set"] = _dedupe_named_headers(set_headers)
    if add_headers:
        body["add"] = _dedupe_named_headers(add_headers)
    if not body:
        return None
    return {"type": "RequestHeaderModifier", "requestHeaderModifier": body}


def _dedupe_header_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _dedupe_named_headers(items: list[dict[str, str]]) -> list[dict[str, str]]:
    by_name: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for item in items:
        name = str(item.get("name", ""))
        key = name.lower()
        if key not in by_name:
            order.append(key)
        by_name[key] = dict(item)
    return [by_name[key] for key in order]


def _route_filters(
    gateway: GatewayDesired,
    *,
    route: RouteDesired,
    forward_auth_header_value: str | None,
    inject: bool,
) -> list[dict[str, Any]]:
    hop_header: str | None = None
    set_headers: list[dict[str, str]] = []
    add_headers: list[dict[str, str]] = []
    extra_filters: list[dict[str, Any]] = []
    if inject and _wants_hop_inject(route, gateway) and forward_auth_header_value:
        hop_header = gateway.auth.authentik.forward_auth_secret_header or "x-vmcp-forward-auth"
        set_headers.append({"name": hop_header, "value": forward_auth_header_value})
    remove = _strip_headers_for_route(
        gateway, route, inject=inject, hop_header=hop_header
    )
    for extra in route.extra_filters:
        copied = dict(extra)
        if copied.get("type") == "RequestHeaderModifier":
            inner = copied.get("requestHeaderModifier")
            rhm = inner if isinstance(inner, dict) else {}
            remove.extend(str(h) for h in (rhm.get("remove") or ()))
            set_headers.extend(
                dict(item) for item in (rhm.get("set") or ()) if isinstance(item, dict)
            )
            add_headers.extend(
                dict(item) for item in (rhm.get("add") or ()) if isinstance(item, dict)
            )
            continue
        extra_filters.append(copied)
    filters: list[dict[str, Any]] = []
    merged = _merge_request_header_modifier(remove, set_headers, add_headers)
    if merged is not None:
        filters.append(merged)
    filters.extend(extra_filters)
    return filters


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


@dataclass(frozen=True, slots=True)
class EarlyStripPlan:
    """Whether to apply a same-namespace kgateway ListenerPolicy (issue #8)."""

    objects: tuple[dict[str, Any], ...]
    phase: str
    message: str


def plan_early_identity_strip(gateway: GatewayDesired) -> EarlyStripPlan:
    """Pre-auth strip: ListenerPolicy earlyRequestHeaderModifier (kgateway OSS).

    HTTPRoute RequestHeaderModifier runs *after* extAuth, so it cannot sanitize
    client-forged identity headers before Authentik. kgateway's only OSS hook
    before auth is ListenerPolicy on the parent Gateway. That CR must live in
    the *same namespace* as the Gateway (no cross-namespace targetRef).
    """
    if not gateway.identity_strip.manage_listener_policy:
        return EarlyStripPlan(
            (),
            "Disabled",
            "identityStrip.manageListenerPolicy=false",
        )
    parents: list[GatewayParentRef] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for route in _strip_routes(gateway):
        ref = route.gateway_ref
        key = (ref.name, ref.namespace, ref.section_name)
        if key in seen:
            continue
        seen.add(key)
        parents.append(ref)
    if not parents:
        return EarlyStripPlan((), "Disabled", "no identity strip requested")

    same_ns: list[GatewayParentRef] = []
    cross: list[str] = []
    for ref in parents:
        parent_ns = ref.namespace or gateway.key.namespace
        if parent_ns != gateway.key.namespace:
            loc = f"{parent_ns}/{ref.name}"
            if ref.section_name:
                loc = f"{loc}#{ref.section_name}"
            cross.append(loc)
            continue
        same_ns.append(ref)

    objects = tuple(_listener_policy(gateway, ref) for ref in same_ns)
    if objects:
        names = ", ".join(obj["metadata"]["name"] for obj in objects)
        message = f"applied {names}"
        if cross:
            message += f"; skipped cross-namespace Gateway {', '.join(cross)}"
        return EarlyStripPlan(objects, "Applied", message)
    return EarlyStripPlan(
        (),
        "SkippedCrossNamespace",
        "ListenerPolicy must share the Gateway namespace "
        f"({', '.join(cross)}); HTTPRoute strip still applies after extAuth",
    )


def _strip_routes(gateway: GatewayDesired) -> list[RouteDesired]:
    routes = [gateway.public_route]
    if gateway.admin_route is not None:
        routes.append(gateway.admin_route)
    return [route for route in routes if route.strip_client_identity_headers]


def _listener_policy(gateway: GatewayDesired, parent: GatewayParentRef) -> dict[str, Any]:
    name = gateway.key.name
    ns = gateway.key.namespace
    target: dict[str, str] = {
        "group": "gateway.networking.k8s.io",
        "kind": "Gateway",
        "name": parent.name,
    }
    if parent.section_name:
        target["sectionName"] = parent.section_name
    return {
        "apiVersion": "gateway.kgateway.dev/v1alpha1",
        "kind": "ListenerPolicy",
        "metadata": {
            "name": _listener_policy_name(name, parent),
            "namespace": ns,
            "labels": {
                "app.kubernetes.io/name": "vmcp",
                "app.kubernetes.io/instance": name,
                "vmcp.io/gateway": name,
            },
            "annotations": {"vmcp.io/identity-strip": "early"},
        },
        "spec": {
            "targetRefs": [target],
            "default": {
                "httpSettings": {
                    "earlyRequestHeaderModifier": {
                        "remove": _identity_remove_headers(gateway),
                    }
                }
            },
        },
    }


def _listener_policy_name(gateway_name: str, parent: GatewayParentRef) -> str:
    parts = [gateway_name, "identity-strip", parent.name]
    if parent.section_name:
        parts.append(parent.section_name)
    raw = "-".join(parts).lower()
    cleaned: list[str] = []
    prev_dash = False
    for char in raw:
        ok = char.isalnum() or char == "-"
        if ok and not (char == "-" and prev_dash):
            cleaned.append(char)
            prev_dash = char == "-"
        elif not ok and not prev_dash:
            cleaned.append("-")
            prev_dash = True
    return "".join(cleaned).strip("-")[:253]
