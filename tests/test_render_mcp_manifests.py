from __future__ import annotations

import pytest

from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.models.mcp import (
    ContainerImageSource,
    McpEndpoint,
    McpServerDesired,
    NamedPort,
    RemoteHttpSource,
    WebExposureDesired,
)
from vmcp_operator.domain.usecases.render_mcp_manifests import RenderMcpManifests


def _gateway() -> GatewayDesired:
    return GatewayDesired(
        key=GatewayKey(namespace="team-a", name="code"),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
        public_route=RouteDesired(
            hostname="code.example.com",
            gateway_ref=GatewayParentRef(name="kgateway", namespace="gateway-system"),
        ),
    )


def test_render_managed_mcp_with_web_exposure() -> None:
    mcp = McpServerDesired(
        namespace="team-a",
        name="architect-c4",
        gateway_key=GatewayKey(namespace="team-a", name="code"),
        enabled=True,
        description="c4",
        source=ContainerImageSource(
            image="harbor.example.com/ai/architect-c4:1",
            ports=(NamedPort(name="http", container_port=8766),),
            mcp_endpoint=McpEndpoint(port_name="http", path="/mcp"),
        ),
        web_exposures=(
            WebExposureDesired(
                name="viewer",
                port_name="http",
                hostname="architect.example.com",
                paths=("/", "/adrs", "/view"),
                public_base_url_env="ARCHITECT_C4_PUBLIC_BASE",
                gateway_ref=GatewayParentRef(
                    name="kgateway",
                    namespace="gateway-system",
                    section_name="https",
                ),
            ),
        ),
    )
    manifests = RenderMcpManifests().execute(_gateway(), mcp)
    kinds = [item["kind"] for item in manifests]
    assert kinds == ["Deployment", "Service", "HTTPRoute"]
    deploy = manifests[0]
    assert "vmcp.io/workload-checksum" in deploy["metadata"]["annotations"]
    assert (
        deploy["spec"]["template"]["metadata"]["annotations"]["vmcp.io/workload-checksum"]
        == deploy["metadata"]["annotations"]["vmcp.io/workload-checksum"]
    )
    container = deploy["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item["value"] for item in container["env"]}
    assert env["ARCHITECT_C4_PUBLIC_BASE"] == "https://architect.example.com"
    route = manifests[2]
    assert route["metadata"]["annotations"]["vmcp.io/status-independent-of-mcp"] == "true"
    assert route["spec"]["rules"][0]["backendRefs"][0]["port"] == 8766
    assert route["spec"]["parentRefs"][0]["sectionName"] == "https"


def test_remote_http_renders_no_workload() -> None:
    mcp = McpServerDesired(
        namespace="team-a",
        name="context7",
        gateway_key=GatewayKey(namespace="team-a", name="code"),
        enabled=True,
        description=None,
        source=RemoteHttpSource(url="https://context7.example/mcp"),
    )
    assert RenderMcpManifests().execute(_gateway(), mcp) == []


def test_missing_web_exposure_port_rejected() -> None:
    mcp = McpServerDesired(
        namespace="team-a",
        name="architect-c4",
        gateway_key=GatewayKey(namespace="team-a", name="code"),
        enabled=True,
        description=None,
        source=ContainerImageSource(
            image="harbor.example.com/ai/architect-c4:1",
            ports=(NamedPort(name="http", container_port=8766),),
            mcp_endpoint=McpEndpoint(port_name="http"),
        ),
        web_exposures=(
            WebExposureDesired(
                name="viewer",
                port_name="missing",
                hostname="architect.example.com",
                paths=("/",),
            ),
        ),
    )
    with pytest.raises(ValueError, match="portName"):
        RenderMcpManifests().execute(_gateway(), mcp)


def test_cross_namespace_rejected() -> None:
    mcp = McpServerDesired(
        namespace="team-b",
        name="architect-c4",
        gateway_key=GatewayKey(namespace="team-b", name="code"),
        enabled=True,
        description=None,
        source=ContainerImageSource(
            image="harbor.example.com/ai/architect-c4:1",
            ports=(NamedPort(name="http", container_port=8766),),
            mcp_endpoint=McpEndpoint(port_name="http"),
        ),
    )
    with pytest.raises(ValueError, match="same-namespace"):
        RenderMcpManifests().execute(_gateway(), mcp)
