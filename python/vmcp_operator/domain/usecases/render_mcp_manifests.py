"""Render managed MCP workloads and optional web exposure routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vmcp_operator.domain.models.gateway import GatewayDesired, GatewayParentRef
from vmcp_operator.domain.models.mcp import ContainerImageSource, McpServerDesired
from vmcp_operator.domain.usecases.checksum_rollout import (
    annotate_checksum,
    managed_workload_checksum,
)


@dataclass(frozen=True, slots=True)
class RenderMcpManifests:
    """ContainerImage → Deployment/Service; webExposures → HTTPRoutes."""

    def execute(
        self,
        gateway: GatewayDesired,
        mcp: McpServerDesired,
    ) -> list[dict[str, Any]]:
        if mcp.gateway_key != gateway.key:
            raise ValueError(
                f"mcp `{mcp.name}` gatewayRef `{mcp.gateway_key.as_str()}` "
                f"must match gateway `{gateway.key.as_str()}` (same-namespace only)"
            )
        if not isinstance(mcp.source, ContainerImageSource):
            return []

        ns = gateway.key.namespace
        child = f"{gateway.key.name}-{mcp.name}"
        labels = {
            "app.kubernetes.io/name": "vmcp-mcp",
            "app.kubernetes.io/instance": child,
            "vmcp.io/gateway": gateway.key.name,
            "vmcp.io/mcp": mcp.name,
        }
        env = [{"name": key, "value": value} for key, value in mcp.source.env]
        for exposure in mcp.web_exposures:
            if exposure.public_base_url_env:
                env.append(
                    {
                        "name": exposure.public_base_url_env,
                        "value": f"https://{exposure.hostname}",
                    }
                )
        checksum = managed_workload_checksum(
            image=mcp.source.image,
            env=tuple((item["name"], item["value"]) for item in env),
            ports=tuple((p.name, p.container_port) for p in mcp.source.ports),
            mcp_path=mcp.source.mcp_endpoint.path,
        )
        pod_meta = annotate_checksum({"labels": labels}, checksum)

        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": annotate_checksum(
                {"name": child, "namespace": ns, "labels": labels},
                checksum,
            ),
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": pod_meta,
                    "spec": {
                        "containers": [
                            {
                                "name": "mcp",
                                "image": mcp.source.image,
                                "ports": [
                                    {
                                        "name": port.name,
                                        "containerPort": port.container_port,
                                        "protocol": port.protocol,
                                    }
                                    for port in mcp.source.ports
                                ],
                                "env": env,
                            }
                        ]
                    },
                },
            },
        }
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": child, "namespace": ns, "labels": labels},
            "spec": {
                "type": "ClusterIP",
                "selector": labels,
                "ports": [
                    {
                        "name": port.name,
                        "port": port.container_port,
                        "targetPort": port.name,
                    }
                    for port in mcp.source.ports
                ],
            },
        }
        manifests: list[dict[str, Any]] = [deployment, service]
        for exposure in mcp.web_exposures:
            parent = exposure.gateway_ref or gateway.public_route.gateway_ref
            manifests.append(
                {
                    "apiVersion": "gateway.networking.k8s.io/v1",
                    "kind": "HTTPRoute",
                    "metadata": {
                        "name": f"{child}-{exposure.name}",
                        "namespace": ns,
                        "labels": labels,
                        "annotations": {
                            "vmcp.io/web-exposure": exposure.name,
                            "vmcp.io/status-independent-of-mcp": "true",
                        },
                    },
                    "spec": {
                        "parentRefs": [_parent_ref(parent)],
                        "hostnames": [exposure.hostname],
                        "rules": [
                            {
                                "matches": [
                                    {"path": {"type": "PathPrefix", "value": path}}
                                    for path in exposure.paths
                                ],
                                "backendRefs": [
                                    {
                                        "name": child,
                                        "port": _port_number(mcp.source, exposure.port_name),
                                    }
                                ],
                            }
                        ],
                    },
                }
            )
        return manifests


def _port_number(source: ContainerImageSource, port_name: str) -> int:
    for port in source.ports:
        if port.name == port_name:
            return port.container_port
    raise ValueError(f"webExposure portName `{port_name}` not found in ports")


def _parent_ref(ref: GatewayParentRef) -> dict[str, str]:
    out: dict[str, str] = {"name": ref.name}
    if ref.namespace:
        out["namespace"] = ref.namespace
    if ref.section_name:
        out["sectionName"] = ref.section_name
    return out
