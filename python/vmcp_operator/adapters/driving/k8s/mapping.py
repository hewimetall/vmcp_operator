"""Map Kubernetes CR dictionaries into immutable domain models."""

from __future__ import annotations

from typing import Any

from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    PersistenceDesired,
    ProxyDesired,
    RouteDesired,
    SecretRef,
    SkillRef,
    TasksDesired,
)
from vmcp_operator.domain.models.mcp import (
    ContainerImageSource,
    McpEndpoint,
    McpServerDesired,
    NamedPort,
    RemoteHttpSource,
    ToolOverrideDesired,
    WebExposureDesired,
)


def map_gateway(namespace: str, name: str, spec: dict[str, Any]) -> GatewayDesired:
    public = spec["publicRoute"]
    admin = spec.get("adminRoute")
    persistence = spec.get("persistence") or {}
    tasks = spec.get("tasks") or {}
    proxy = spec.get("proxy") or {}
    return GatewayDesired(
        key=GatewayKey(namespace=namespace, name=name),
        image=str(spec["image"]),
        admin_token_secret_ref=_secret_ref(spec["adminTokenSecretRef"]),
        master_password_secret_ref=_secret_ref(spec["masterPasswordSecretRef"]),
        public_route=_route(public),
        admin_route=_route(admin) if admin else None,
        persistence=PersistenceDesired(
            size=str(persistence.get("size", "5Gi")),
            storage_class_name=persistence.get("storageClassName"),
            reclaim_policy=str(persistence.get("reclaimPolicy", "Retain")),
        ),
        tasks=TasksDesired(
            enabled=bool(tasks.get("enabled", False)),
            max_concurrent=int(tasks.get("maxConcurrent", 1)),
        ),
        proxy=ProxyDesired(
            enabled=bool(proxy.get("enabled", False)),
            path=str(proxy.get("path", "/mcp-proxy")),
        ),
        skill_refs=tuple(_skill_ref(item) for item in spec.get("skillRefs") or ()),
    )


def map_mcp(namespace: str, name: str, spec: dict[str, Any]) -> McpServerDesired:
    source = spec["source"]
    source_type = source["type"]
    if source_type == "RemoteHttp":
        mapped_source: ContainerImageSource | RemoteHttpSource = RemoteHttpSource(
            url=str(source["url"]),
            bearer_secret_ref=(
                _secret_ref(source["bearerSecretRef"])
                if source.get("bearerSecretRef")
                else None
            ),
        )
    elif source_type == "ContainerImage":
        ports = tuple(
            NamedPort(
                name=str(port["name"]),
                container_port=int(port["containerPort"]),
                protocol=str(port.get("protocol", "TCP")),
            )
            for port in source.get("ports") or ()
        )
        endpoint = source.get("mcpEndpoint") or {}
        mapped_source = ContainerImageSource(
            image=str(source["image"]),
            ports=ports,
            mcp_endpoint=McpEndpoint(
                port_name=str(endpoint.get("portName", "http")),
                path=str(endpoint.get("path", "/mcp")),
            ),
            env=tuple(
                (str(item["name"]), str(item.get("value", "")))
                for item in source.get("env") or ()
                if "name" in item
            ),
        )
    else:
        raise ValueError(f"unsupported source.type `{source_type}`")

    return McpServerDesired(
        namespace=namespace,
        name=name,
        gateway_key=GatewayKey(namespace=namespace, name=str(spec["gatewayRef"]["name"])),
        enabled=bool(spec.get("enabled", True)),
        description=spec.get("description"),
        source=mapped_source,
        tool_overrides=tuple(
            ToolOverrideDesired(
                name=str(item["name"]),
                read_only=bool(item["readOnly"]),
                task_support=item.get("taskSupport"),
            )
            for item in spec.get("toolOverrides") or ()
        ),
        skill_refs=tuple(_skill_ref(item) for item in spec.get("skillRefs") or ()),
        web_exposures=tuple(_web_exposure(item) for item in spec.get("webExposures") or ()),
    )


def _secret_ref(raw: dict[str, Any]) -> SecretRef:
    return SecretRef(name=str(raw["name"]), key=str(raw.get("key", "token")))


def _route(raw: dict[str, Any]) -> RouteDesired:
    ref = raw["gatewayRef"]
    annotations = tuple(sorted((str(k), str(v)) for k, v in (raw.get("annotations") or {}).items()))
    return RouteDesired(
        hostname=str(raw["hostname"]),
        gateway_ref=GatewayParentRef(
            name=str(ref["name"]),
            namespace=ref.get("namespace"),
            section_name=ref.get("sectionName"),
        ),
        annotations=annotations,
    )


def _skill_ref(raw: dict[str, Any]) -> SkillRef:
    return SkillRef(name=str(raw["name"]), key=raw.get("key"))


def _web_exposure(raw: dict[str, Any]) -> WebExposureDesired:
    ref = raw.get("gatewayRef")
    return WebExposureDesired(
        name=str(raw["name"]),
        port_name=str(raw["portName"]),
        hostname=str(raw["hostname"]),
        paths=tuple(str(path) for path in raw.get("paths") or ()),
        gateway_ref=(
            GatewayParentRef(
                name=str(ref["name"]),
                namespace=ref.get("namespace"),
                section_name=ref.get("sectionName"),
            )
            if ref
            else None
        ),
        annotations=tuple(
            sorted((str(k), str(v)) for k, v in (raw.get("annotations") or {}).items())
        ),
        public_base_url_env=raw.get("publicBaseUrlEnv"),
    )
