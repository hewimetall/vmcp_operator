from __future__ import annotations

import pytest

from vmcp_operator.domain.models.artifacts import ArtifactBundle, ArtifactFile
from vmcp_operator.domain.models.gateway import (
    AuthDesired,
    AuthentikDesired,
    AuthProvider,
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    PersistenceDesired,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.models.mcp import McpServerDesired, RemoteHttpSource
from vmcp_operator.domain.usecases.render_gateway_manifests import (
    RenderGatewayManifests,
    flatten_configmap_key,
)


def test_render_gateway_manifests_no_subpath_and_admin_route() -> None:
    gateway = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway", namespace="gw", section_name="https"),
        ),
        admin_route=RouteDesired(
            hostname="admin-main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
        persistence=PersistenceDesired(
            size="8Gi",
            storage_class_name="fast",
            reclaim_policy="Retain",
        ),
    )
    artifacts = ArtifactBundle(
        files={
            "registry.json": ArtifactFile(
                path="registry.json",
                data='{"upstreams":[]}\n',
                sha256="abc",
            )
        },
        registry_sha256="abc",
        bundle_sha256="def",
        total_bytes=16,
    )
    mcp = McpServerDesired(
        namespace="team-a",
        name="docs",
        gateway_key=gateway.key,
        enabled=True,
        description=None,
        source=RemoteHttpSource(
            url="https://docs.example.com/mcp",
            bearer_secret_ref=SecretRef(name="docs-bearer", key="token"),
        ),
    )
    manifests = RenderGatewayManifests().execute(gateway, artifacts, [mcp])
    kinds = [m["kind"] for m in manifests]
    assert kinds == [
        "PersistentVolumeClaim",
        "ConfigMap",
        "Service",
        "Deployment",
        "HTTPRoute",
        "HTTPRoute",
    ]
    deploy = next(m for m in manifests if m["kind"] == "Deployment")
    mounts = deploy["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
    assert all("subPath" not in mount for mount in mounts)
    assert any(m["mountPath"] == "/secrets" for m in mounts)
    env = {e["name"]: e for e in deploy["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["VMCP_CONFIG"]["value"] == "/config/vmcp.toml"
    assert env["VMCP_AUTH__MASTER_PASSWORD_ARGON2"]["valueFrom"]["secretKeyRef"]["name"] == "pass"
    assert env["VMCP_BEARER_DOCS"]["valueFrom"]["secretKeyRef"]["name"] == "docs-bearer"
    cm = next(m for m in manifests if m["kind"] == "ConfigMap")
    assert "registry.json" in cm["data"]
    assert "vmcp.toml" in cm["data"]
    assert 'provider = "local"' in cm["data"]["vmcp.toml"]
    assert cm["metadata"]["annotations"]["vmcp.io/contract"] == "vmcp-v1.2"
    assert all("/" not in key for key in cm["data"])
    assert deploy["spec"]["template"]["spec"]["initContainers"][0]["name"] == "expand-artifacts"
    admin = next(m for m in manifests if m["metadata"]["name"] == "main-admin")
    assert admin["spec"]["rules"][0]["matches"][0]["path"]["value"] == "/admin"
    pvc = next(m for m in manifests if m["kind"] == "PersistentVolumeClaim")
    assert pvc["spec"]["storageClassName"] == "fast"
    assert pvc["metadata"]["annotations"]["vmcp.io/reclaim-policy"] == "Retain"


def test_render_authentik_forward_auth_secret_env() -> None:
    gateway = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="ak"),
        image="harbor.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname="ak.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
        auth=AuthDesired(
            provider=AuthProvider.AUTHENTIK,
            authentik=AuthentikDesired(
                issuer="https://auth.example.com/o/mcp/",
                jwks_url="https://auth.example.com/o/mcp/jwks/",
                trusted_proxies=("10.244.0.0/16",),
                forward_auth_secret_ref=SecretRef(name="hop", key="secret"),
            ),
        ),
    )
    artifacts = ArtifactBundle(
        files={
            "registry.json": ArtifactFile(
                path="registry.json",
                data="{}\n",
                sha256="a",
            )
        },
        registry_sha256="a",
        bundle_sha256="b",
        total_bytes=3,
    )
    deploy = next(
        m
        for m in RenderGatewayManifests().execute(gateway, artifacts)
        if m["kind"] == "Deployment"
    )
    env = {e["name"]: e for e in deploy["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert (
        env["VMCP_AUTH__AUTHENTIK__FORWARD_AUTH_SECRET"]["valueFrom"]["secretKeyRef"]["name"]
        == "hop"
    )


def test_flatten_configmap_key() -> None:
    assert flatten_configmap_key("skills/foo.yaml") == "skills__foo.yaml"
    with pytest.raises(ValueError):
        flatten_configmap_key("")


def test_render_gateway_manifests_without_admin_or_storage_class() -> None:
    gateway = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="solo"),
        image="harbor.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
        public_route=RouteDesired(
            hostname="solo.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )
    artifacts = ArtifactBundle(
        files={
            "registry.json": ArtifactFile(
                path="registry.json",
                data="{}\n",
                sha256="a",
            )
        },
        registry_sha256="a",
        bundle_sha256="b",
        total_bytes=3,
    )
    manifests = RenderGatewayManifests().execute(gateway, artifacts)
    assert [m["kind"] for m in manifests] == [
        "PersistentVolumeClaim",
        "ConfigMap",
        "Service",
        "Deployment",
        "HTTPRoute",
    ]
    pvc = manifests[0]
    assert "storageClassName" not in pvc["spec"]
