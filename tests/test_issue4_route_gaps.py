from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vmcp_operator.adapters.driven.k8s.secret_loader import InMemorySecretValueLoader
from vmcp_operator.adapters.driven.k8s.ssa import InMemoryApplier, ServerSideApply
from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.adapters.driving.k8s.mapping import map_gateway
from vmcp_operator.adapters.driving.k8s.reconcile import GatewayReconcile
from vmcp_operator.adapters.driving.k8s.runtime import EmptySkillLoader
from vmcp_operator.domain.models.artifacts import ArtifactBundle, ArtifactFile
from vmcp_operator.domain.models.gateway import (
    PUBLIC_STRIP_IDENTITY_HEADERS,
    AdminAuthDesired,
    AdminAuthMode,
    AuthDesired,
    AuthentikDesired,
    AuthProvider,
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_config import render_gateway_config
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests


def _artifacts() -> ArtifactBundle:
    return ArtifactBundle(
        files={
            "registry.json": ArtifactFile(
                path="registry.json", data='{"upstreams":[]}\n', sha256="a"
            )
        },
        registry_sha256="a",
        bundle_sha256="b",
        total_bytes=16,
    )


def _ak_gateway() -> GatewayDesired:
    return GatewayDesired(
        key=GatewayKey(namespace="team-a", name="vmcp"),
        image="registry.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            strip_client_identity_headers=True,
        ),
        admin_route=RouteDesired(
            hostname="admin.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            inject_forward_auth_header=True,
        ),
        auth=AuthDesired(
            provider=AuthProvider.AUTHENTIK,
            admin=AdminAuthDesired(mode=AdminAuthMode.AUTHENTIK),
            authentik=AuthentikDesired(
                issuer="https://auth.example.com/o/mcp/",
                jwks_url="https://auth.example.com/o/mcp/jwks/",
                forward_auth_secret_ref=SecretRef(name="hop", key="secret"),
                forward_auth_secret_header="X-Vmcp-Forward-Auth",
            ),
        ),
        public_base_url="https://mcp.example.com",
    )


def test_gap1_public_route_strips_identity_headers() -> None:
    manifests = RenderGatewayManifests().execute(_ak_gateway(), _artifacts())
    public = next(m for m in manifests if m["metadata"]["name"] == "vmcp-public")
    filters = public["spec"]["rules"][0]["filters"]
    assert filters[0]["type"] == "RequestHeaderModifier"
    removed = {h.lower() for h in filters[0]["requestHeaderModifier"]["remove"]}
    for header in PUBLIC_STRIP_IDENTITY_HEADERS:
        assert header.lower() in removed


def test_gap2_admin_route_sets_hop_header_when_value_provided() -> None:
    manifests = RenderGatewayManifests().execute(
        _ak_gateway(),
        _artifacts(),
        forward_auth_header_value="s3cr3t",
    )
    admin = next(m for m in manifests if m["metadata"]["name"] == "vmcp-admin")
    filters = admin["spec"]["rules"][0]["filters"]
    assert filters[0]["requestHeaderModifier"]["set"] == [
        {"name": "X-Vmcp-Forward-Auth", "value": "s3cr3t"}
    ]


def test_gap2_admin_omits_set_without_secret_value() -> None:
    manifests = RenderGatewayManifests().execute(_ak_gateway(), _artifacts())
    admin = next(m for m in manifests if m["metadata"]["name"] == "vmcp-admin")
    assert "filters" not in admin["spec"]["rules"][0]


def test_gap3_enable_service_links_false() -> None:
    deploy = next(
        m
        for m in RenderGatewayManifests().execute(_ak_gateway(), _artifacts())
        if m["kind"] == "Deployment"
    )
    assert deploy["spec"]["template"]["spec"]["enableServiceLinks"] is False


def test_public_base_url_override_in_toml() -> None:
    toml = render_gateway_config(_ak_gateway())
    assert 'public_base_url = "https://mcp.example.com"' in toml


def test_map_sample_authentik_route_flags() -> None:
    doc = yaml.safe_load(
        Path("deploy/samples/gateway-authentik.yaml").read_text(encoding="utf-8")
    )
    gw = map_gateway(doc["metadata"]["namespace"], doc["metadata"]["name"], doc["spec"])
    assert gw.public_route.strip_client_identity_headers is True
    assert gw.admin_route is not None
    assert gw.admin_route.inject_forward_auth_header is True


@pytest.mark.asyncio
async def test_reconcile_materializes_hop_secret_into_admin_route() -> None:
    gw = _ak_gateway()
    secrets = InMemorySecretValueLoader(
        values={("team-a", "hop", "secret"): "from-k8s"}
    )
    applier = InMemoryApplier()
    result = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(), skill_loader=EmptySkillLoader()
        ),
        manifests=RenderGatewayManifests(),
        apply=ServerSideApply(applier=applier),
        secrets=secrets,
    ).execute(gw, [])
    assert result["adminHopHeaderInjected"] is True
    admin = next(
        item["body"]
        for item in (applier.applied or [])
        if item["body"].get("kind") == "HTTPRoute"
        and item["body"]["metadata"]["name"] == "vmcp-admin"
    )
    assert (
        admin["spec"]["rules"][0]["filters"][0]["requestHeaderModifier"]["set"][0]["value"]
        == "from-k8s"
    )


@pytest.mark.asyncio
async def test_reconcile_skips_hop_when_disabled_or_secret_missing() -> None:
    gw = _ak_gateway()
    gw_off = GatewayDesired(
        key=gw.key,
        image=gw.image,
        admin_token_secret_ref=gw.admin_token_secret_ref,
        master_password_secret_ref=gw.master_password_secret_ref,
        public_route=gw.public_route,
        admin_route=RouteDesired(
            hostname="admin.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            inject_forward_auth_header=False,
        ),
        auth=gw.auth,
    )
    result = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(), skill_loader=EmptySkillLoader()
        ),
        manifests=RenderGatewayManifests(),
        apply=ServerSideApply(applier=InMemoryApplier()),
        secrets=InMemorySecretValueLoader(
            values={("team-a", "hop", "secret"): "x"}
        ),
    ).execute(gw_off, [])
    assert result["adminHopHeaderInjected"] is False

    result_missing = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(), skill_loader=EmptySkillLoader()
        ),
        manifests=RenderGatewayManifests(),
        apply=ServerSideApply(applier=InMemoryApplier()),
        secrets=InMemorySecretValueLoader(),
    ).execute(gw, [])
    assert result_missing["adminHopHeaderInjected"] is False


def test_public_strip_can_be_disabled_and_annotations_pass() -> None:
    gw = _ak_gateway()
    gw = GatewayDesired(
        key=gw.key,
        image=gw.image,
        admin_token_secret_ref=gw.admin_token_secret_ref,
        master_password_secret_ref=gw.master_password_secret_ref,
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            strip_client_identity_headers=False,
            annotations=(("a", "b"),),
        ),
        admin_route=RouteDesired(
            hostname="admin.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            inject_forward_auth_header=None,
            annotations=(("c", "d"),),
        ),
        auth=gw.auth,
    )
    manifests = RenderGatewayManifests().execute(
        gw, _artifacts(), forward_auth_header_value="hop"
    )
    public = next(m for m in manifests if m["metadata"]["name"] == "vmcp-public")
    assert "filters" not in public["spec"]["rules"][0]
    assert public["metadata"]["annotations"]["a"] == "b"
    admin = next(m for m in manifests if m["metadata"]["name"] == "vmcp-admin")
    assert admin["metadata"]["annotations"]["c"] == "d"
    # inject=None + secret present → set filter when value provided
    assert admin["spec"]["rules"][0]["filters"]


def test_runtime_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    from vmcp_operator.adapters.driving.k8s import runtime as rt_mod

    rt_mod.set_runtime(None)
    monkeypatch.setenv("VMCP_OPERATOR_RUNTIME", "memory")
    monkeypatch.delenv("KUBECONFIG", raising=False)
    assert rt_mod.get_runtime().gateway_reconcile.secrets is None
    rt_mod.set_runtime(None)
    monkeypatch.setenv("VMCP_OPERATOR_RUNTIME", "kr8s")
    # for_cluster constructs without contacting the API until first call.
    cluster = rt_mod.OperatorRuntime.for_cluster()
    assert cluster.gateway_reconcile.secrets is not None
    rt_mod.set_runtime(None)
