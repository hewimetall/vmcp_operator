"""Map Kubernetes CR dictionaries into immutable domain models."""

from __future__ import annotations

from typing import Any

from vmcp_operator.domain.models.gateway import (
    AdminAuthDesired,
    AdminAuthMode,
    AuthDesired,
    AuthentikDesired,
    AuthProvider,
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    GqlDesired,
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
    McpSource,
    NamedPort,
    RemoteHttpSource,
    ToolOverrideDesired,
    VmcpProxySource,
    WebExposureDesired,
)


def map_gateway(namespace: str, name: str, spec: dict[str, Any]) -> GatewayDesired:
    public = spec["publicRoute"]
    admin = spec.get("adminRoute")
    persistence = spec.get("persistence") or {}
    tasks = spec.get("tasks") or {}
    proxy = spec.get("proxy") or {}
    gql = spec.get("gql") or {}
    public_base = spec.get("publicBaseUrl")
    return GatewayDesired(
        key=GatewayKey(namespace=namespace, name=name),
        image=str(spec["image"]),
        admin_token_secret_ref=_secret_ref(spec["adminTokenSecretRef"]),
        master_password_secret_ref=_secret_ref(
            spec["masterPasswordSecretRef"], default_key="password"
        ),
        public_route=_route(public, role="public"),
        admin_route=_route(admin, role="admin") if admin else None,
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
        gql=GqlDesired(
            max_complexity=int(gql.get("maxComplexity", 1000)),
            max_depth=int(gql.get("maxDepth", 10)),
        ),
        auth=_map_auth(spec.get("auth") or {}),
        skill_refs=tuple(_skill_ref(item) for item in spec.get("skillRefs") or ()),
        public_base_url=str(public_base).strip() if public_base else None,
    )


def map_mcp(namespace: str, name: str, spec: dict[str, Any]) -> McpServerDesired:
    source = spec["source"]
    source_type = source["type"]
    if source_type == "RemoteHttp":
        mapped_source: McpSource = RemoteHttpSource(
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
    elif source_type == "VmcpProxy":
        peer_raw = source.get("peerGatewayRef") or {}
        if not peer_raw.get("name"):
            raise ValueError("VmcpProxy source requires peerGatewayRef.name")
        mapped_source = VmcpProxySource(
            peer=GatewayKey(
                namespace=str(peer_raw.get("namespace") or namespace),
                name=str(peer_raw["name"]),
            ),
            path=str(source.get("path") or "/mcp-proxy"),
            port=int(source.get("port") or 8080),
            bearer_secret_ref=(
                _secret_ref(source["bearerSecretRef"])
                if source.get("bearerSecretRef")
                else None
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
        forward_identity=bool(spec.get("forwardIdentity", False)),
    )


def _map_auth(raw: dict[str, Any]) -> AuthDesired:
    admin_raw = raw.get("admin") or {}
    ak_raw = raw.get("authentik") or {}
    provider = AuthProvider(str(raw.get("provider", "local")))
    admin_mode = AdminAuthMode(str(admin_raw.get("mode", "basic")))
    group_scopes_raw = ak_raw.get("groupScopes") or {}
    group_scopes = tuple(
        sorted((str(k), str(v)) for k, v in group_scopes_raw.items())
    )
    forward_secret = ak_raw.get("forwardAuthSecretRef")
    return AuthDesired(
        enabled=bool(raw.get("enabled", True)),
        provider=provider,
        admin=AdminAuthDesired(
            mode=admin_mode,
            required_groups=tuple(str(g) for g in admin_raw.get("requiredGroups") or ()),
        ),
        authentik=AuthentikDesired(
            issuer=str(ak_raw.get("issuer", "")),
            jwks_url=str(ak_raw.get("jwksUrl", "")),
            audiences=tuple(str(a) for a in ak_raw.get("audiences") or ()),
            accept_bearer=bool(ak_raw.get("acceptBearer", True)),
            forward_auth=bool(ak_raw.get("forwardAuth", True)),
            username_header=str(ak_raw.get("usernameHeader", "x-authentik-username")),
            groups_header=str(ak_raw.get("groupsHeader", "x-authentik-groups")),
            groups_claim=str(ak_raw.get("groupsClaim", "groups")),
            group_scopes=group_scopes,
            trusted_proxies=tuple(str(p) for p in ak_raw.get("trustedProxies") or ()),
            forward_auth_secret_ref=(
                _secret_ref(forward_secret, default_key="secret") if forward_secret else None
            ),
            forward_auth_secret_header=str(
                ak_raw.get("forwardAuthSecretHeader", "x-vmcp-forward-auth")
            ),
        ),
    )


def _secret_ref(raw: dict[str, Any], *, default_key: str = "token") -> SecretRef:
    return SecretRef(name=str(raw["name"]), key=str(raw.get("key", default_key)))


def _route(raw: dict[str, Any], *, role: str) -> RouteDesired:
    ref = raw["gatewayRef"]
    annotations = tuple(sorted((str(k), str(v)) for k, v in (raw.get("annotations") or {}).items()))
    strip = bool(raw.get("stripClientIdentityHeaders", True))
    inject_raw = raw.get("injectForwardAuthHeader")
    inject: bool | None = None if inject_raw is None else bool(inject_raw)
    if role == "public":
        # Public edge never injects the hop secret.
        inject = False
    return RouteDesired(
        hostname=str(raw["hostname"]),
        gateway_ref=GatewayParentRef(
            name=str(ref["name"]),
            namespace=ref.get("namespace"),
            section_name=ref.get("sectionName"),
        ),
        annotations=annotations,
        strip_client_identity_headers=strip if role == "public" else False,
        inject_forward_auth_header=inject,
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


def mcp_to_crd(mcp: McpServerDesired) -> dict[str, Any]:
    """Serialize desired MCP state into a VmcpMcpServer CR body."""
    if mcp.gateway_key.namespace != mcp.namespace:
        raise ValueError("mcp namespace must match gateway namespace")
    source: dict[str, Any]
    if isinstance(mcp.source, RemoteHttpSource):
        source = {"type": "RemoteHttp", "url": mcp.source.url}
        if mcp.source.bearer_secret_ref is not None:
            source["bearerSecretRef"] = {
                "name": mcp.source.bearer_secret_ref.name,
                "key": mcp.source.bearer_secret_ref.key,
            }
    elif isinstance(mcp.source, ContainerImageSource):
        source = {
            "type": "ContainerImage",
            "image": mcp.source.image,
            "ports": [
                {
                    "name": port.name,
                    "containerPort": port.container_port,
                    "protocol": port.protocol,
                }
                for port in mcp.source.ports
            ],
            "mcpEndpoint": {
                "portName": mcp.source.mcp_endpoint.port_name,
                "path": mcp.source.mcp_endpoint.path,
            },
        }
        if mcp.source.env:
            source["env"] = [{"name": k, "value": v} for k, v in mcp.source.env]
    elif isinstance(mcp.source, VmcpProxySource):
        peer: dict[str, str] = {"name": mcp.source.peer.name}
        if mcp.source.peer.namespace != mcp.namespace:
            peer["namespace"] = mcp.source.peer.namespace
        source = {
            "type": "VmcpProxy",
            "peerGatewayRef": peer,
            "path": mcp.source.path,
            "port": mcp.source.port,
        }
        if mcp.source.bearer_secret_ref is not None:
            source["bearerSecretRef"] = {
                "name": mcp.source.bearer_secret_ref.name,
                "key": mcp.source.bearer_secret_ref.key,
            }
    else:
        raise TypeError(f"unsupported source {type(mcp.source)!r}")

    spec: dict[str, Any] = {
        "enabled": mcp.enabled,
        "gatewayRef": {"name": mcp.gateway_key.name},
        "source": source,
        "forwardIdentity": mcp.forward_identity,
    }
    if mcp.description is not None:
        spec["description"] = mcp.description
    if mcp.tool_overrides:
        spec["toolOverrides"] = [
            {
                "name": ov.name,
                "readOnly": ov.read_only,
                **({"taskSupport": ov.task_support} if ov.task_support else {}),
            }
            for ov in mcp.tool_overrides
        ]
    if mcp.skill_refs:
        spec["skillRefs"] = [
            {"name": ref.name, **({"key": ref.key} if ref.key else {})}
            for ref in mcp.skill_refs
        ]
    if mcp.web_exposures:
        exposures = []
        for exp in mcp.web_exposures:
            item: dict[str, Any] = {
                "name": exp.name,
                "portName": exp.port_name,
                "hostname": exp.hostname,
                "paths": list(exp.paths),
            }
            if exp.gateway_ref is not None:
                item["gatewayRef"] = {
                    "name": exp.gateway_ref.name,
                    **(
                        {"namespace": exp.gateway_ref.namespace}
                        if exp.gateway_ref.namespace
                        else {}
                    ),
                    **(
                        {"sectionName": exp.gateway_ref.section_name}
                        if exp.gateway_ref.section_name
                        else {}
                    ),
                }
            if exp.annotations:
                item["annotations"] = dict(exp.annotations)
            if exp.public_base_url_env:
                item["publicBaseUrlEnv"] = exp.public_base_url_env
            exposures.append(item)
        spec["webExposures"] = exposures

    return {
        "apiVersion": "vmcp.io/v1alpha1",
        "kind": "VmcpMcpServer",
        "metadata": {"name": mcp.name, "namespace": mcp.namespace},
        "spec": spec,
    }


def mcp_to_public_dict(mcp: McpServerDesired) -> dict[str, Any]:
    """JSON-friendly MCP summary for the operator control-plane API."""
    source: dict[str, Any]
    if isinstance(mcp.source, RemoteHttpSource):
        source = {"type": "RemoteHttp", "url": mcp.source.url}
        if mcp.source.bearer_secret_ref is not None:
            source["bearerSecretRef"] = {
                "name": mcp.source.bearer_secret_ref.name,
                "key": mcp.source.bearer_secret_ref.key,
            }
    elif isinstance(mcp.source, VmcpProxySource):
        source = {
            "type": "VmcpProxy",
            "peerGateway": mcp.source.peer.as_str(),
            "path": mcp.source.path,
            "port": mcp.source.port,
            "clusterUrl": mcp.source.cluster_url(),
        }
        if mcp.source.bearer_secret_ref is not None:
            source["bearerSecretRef"] = {
                "name": mcp.source.bearer_secret_ref.name,
                "key": mcp.source.bearer_secret_ref.key,
            }
    else:
        source = {
            "type": "ContainerImage",
            "image": mcp.source.image,
            "ports": [
                {
                    "name": p.name,
                    "containerPort": p.container_port,
                    "protocol": p.protocol,
                }
                for p in mcp.source.ports
            ],
            "mcpEndpoint": {
                "portName": mcp.source.mcp_endpoint.port_name,
                "path": mcp.source.mcp_endpoint.path,
            },
        }
    return {
        "namespace": mcp.namespace,
        "name": mcp.name,
        "gateway": mcp.gateway_key.as_str(),
        "enabled": mcp.enabled,
        "description": mcp.description,
        "forwardIdentity": mcp.forward_identity,
        "source": source,
    }
