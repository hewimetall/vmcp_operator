from __future__ import annotations

import pytest

from vmcp_operator.domain.models.artifacts import ArtifactBundle, ArtifactFile
from vmcp_operator.domain.models.gateway import (
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    PersistenceDesired,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.usecases.render_gateway_manifests import (
    RenderGatewayManifests,
    flatten_configmap_key,
)


def test_render_gateway_manifests_no_subpath_and_admin_route() -> None:
    gateway = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
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
    manifests = RenderGatewayManifests().execute(gateway, artifacts)
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
    cm = next(m for m in manifests if m["kind"] == "ConfigMap")
    assert "registry.json" in cm["data"]
    assert all("/" not in key for key in cm["data"])
    assert deploy["spec"]["template"]["spec"]["initContainers"][0]["name"] == "expand-artifacts"
    admin = next(m for m in manifests if m["metadata"]["name"] == "main-admin")
    assert admin["spec"]["rules"][0]["matches"][0]["path"]["value"] == "/admin"
    pvc = next(m for m in manifests if m["kind"] == "PersistentVolumeClaim")
    assert pvc["spec"]["storageClassName"] == "fast"
    assert pvc["metadata"]["annotations"]["vmcp.io/reclaim-policy"] == "Retain"


def test_flatten_configmap_key() -> None:
    assert flatten_configmap_key("skills/foo.yaml") == "skills__foo.yaml"
    with pytest.raises(ValueError):
        flatten_configmap_key("")


def test_render_gateway_manifests_without_admin_or_storage_class() -> None:
    gateway = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="solo"),
        image="harbor.example.com/ai/vmcp:1",
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
