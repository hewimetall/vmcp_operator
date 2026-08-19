from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fake_patch import FakePatch
from vmcp_operator.adapters.driving.k8s import handlers
from vmcp_operator.adapters.driving.k8s.mapping import map_gateway
from vmcp_operator.adapters.driving.k8s.runtime import OperatorRuntime, set_runtime
from vmcp_operator.domain.models.artifacts import ArtifactBundle, ArtifactFile
from vmcp_operator.domain.models.gateway import (
    AuthDesired,
    AuthentikDesired,
    AuthProvider,
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    RouteDesired,
    SecretRef,
)
from vmcp_operator.domain.usecases.list_environments import ListEnvironments
from vmcp_operator.domain.usecases.render_gateway_manifests import (
    RenderGatewayManifests,
    plan_early_identity_strip,
)


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


def _base_spec() -> dict:
    return {
        "image": "registry.example.com/ai/vmcp:1.2.0",
        "adminTokenSecretRef": {"name": "tokens"},
        "masterPasswordSecretRef": {"name": "pass", "key": "password"},
        "publicRoute": {
            "hostname": "vmcp.example.com",
            "gatewayRef": {"name": "kgateway", "namespace": "gw", "sectionName": "https"},
        },
    }


def test_admin_route_without_gateway_ref_inherits_public() -> None:
    spec = _base_spec()
    spec["adminRoute"] = {"injectForwardAuthHeader": True}
    gw = map_gateway("vmcp", "gateway", spec)
    assert gw.admin_route is not None
    assert gw.admin_route.hostname == "vmcp.example.com"
    assert gw.admin_route.path == "/admin"
    assert gw.admin_route.gateway_ref.name == "kgateway"
    assert gw.admin_route.gateway_ref.namespace == "gw"
    assert gw.admin_route.gateway_ref.section_name == "https"
    assert gw.admin_route.inject_forward_auth_header is True


def test_admin_route_same_host_custom_path() -> None:
    spec = _base_spec()
    spec["adminRoute"] = {"path": "/console"}
    gw = map_gateway("vmcp", "gateway", spec)
    assert gw.admin_route is not None
    manifests = RenderGatewayManifests().execute(gw, _artifacts())
    admin = next(m for m in manifests if m["metadata"]["name"] == "gateway-admin")
    public = next(m for m in manifests if m["metadata"]["name"] == "gateway-public")
    assert admin["spec"]["hostnames"] == ["vmcp.example.com"]
    assert public["spec"]["hostnames"] == ["vmcp.example.com"]
    assert admin["spec"]["rules"][0]["matches"][0]["path"]["value"] == "/console"
    assert public["spec"]["rules"][0]["matches"][0]["path"]["value"] == "/"


def test_admin_route_path_must_start_with_slash() -> None:
    spec = _base_spec()
    spec["adminRoute"] = {"path": "admin"}
    with pytest.raises(ValueError, match=r"adminRoute\.path must start with '/'"):
        map_gateway("vmcp", "gateway", spec)


def test_public_route_requires_hostname_and_gateway_ref() -> None:
    spec = _base_spec()
    spec["publicRoute"] = {"gatewayRef": {"name": "kgateway"}}
    with pytest.raises(ValueError, match=r"publicRoute\.hostname is required"):
        map_gateway("vmcp", "gateway", spec)
    spec["publicRoute"] = {"hostname": "vmcp.example.com"}
    with pytest.raises(ValueError, match=r"publicRoute\.gatewayRef\.name is required"):
        map_gateway("vmcp", "gateway", spec)
    with pytest.raises(ValueError, match="publicRoute is required"):
        map_gateway("vmcp", "gateway", {k: v for k, v in spec.items() if k != "publicRoute"})


def test_admin_gateway_ref_must_be_object() -> None:
    spec = _base_spec()
    spec["adminRoute"] = {"gatewayRef": "kgateway"}
    with pytest.raises(ValueError, match=r"adminRoute\.gatewayRef must be an object"):
        map_gateway("vmcp", "gateway", spec)


def test_map_same_host_sample() -> None:
    doc = yaml.safe_load(
        Path("deploy/samples/gateway-authentik-same-host.yaml").read_text(encoding="utf-8")
    )
    gw = map_gateway(doc["metadata"]["namespace"], doc["metadata"]["name"], doc["spec"])
    assert gw.admin_route is not None
    assert gw.admin_route.hostname == gw.public_route.hostname
    assert gw.admin_route.path == "/admin"
    assert gw.admin_route.inject_forward_auth_header is True


def test_merged_header_modifier_and_extra_filters() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="vmcp"),
        image="registry.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname="vmcp.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
        admin_route=RouteDesired(
            hostname="vmcp.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            path="/admin",
            inject_forward_auth_header=True,
            extra_filters=(
                {
                    "type": "RequestHeaderModifier",
                    "requestHeaderModifier": {
                        "remove": ["X-Debug"],
                        "set": [{"name": "X-Trace", "value": "1"}],
                        "add": [{"name": "X-Added", "value": "yes"}],
                    },
                },
                {"type": "RequestRedirect", "requestRedirect": {"scheme": "https"}},
            ),
        ),
        auth=AuthDesired(
            provider=AuthProvider.AUTHENTIK,
            authentik=AuthentikDesired(
                forward_auth_secret_ref=SecretRef(name="hop", key="secret"),
                forward_auth_secret_header="X-Vmcp-Forward-Auth",
            ),
        ),
    )
    manifests = RenderGatewayManifests().execute(
        gw, _artifacts(), forward_auth_header_value="s3cr3t"
    )
    admin = next(m for m in manifests if m["metadata"]["name"] == "vmcp-admin")
    types = [f["type"] for f in admin["spec"]["rules"][0]["filters"]]
    assert types.count("RequestHeaderModifier") == 1
    assert "RequestRedirect" in types
    rhm = next(
        f["requestHeaderModifier"]
        for f in admin["spec"]["rules"][0]["filters"]
        if f["type"] == "RequestHeaderModifier"
    )
    assert {"name": "X-Vmcp-Forward-Auth", "value": "s3cr3t"} in rhm["set"]
    assert {"name": "X-Trace", "value": "1"} in rhm["set"]
    assert {"name": "X-Added", "value": "yes"} in rhm["add"]
    assert "X-Debug" in rhm["remove"]
    assert "X-authentik-username" not in rhm["remove"]


def test_admin_without_hop_inject_still_strips_identity() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="vmcp"),
        image="registry.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname="vmcp.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
        admin_route=RouteDesired(
            hostname="admin.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            path="/admin",
            inject_forward_auth_header=False,
        ),
    )
    admin = next(
        m
        for m in RenderGatewayManifests().execute(gw, _artifacts())
        if m["metadata"]["name"] == "vmcp-admin"
    )
    removed = {
        h.lower()
        for h in admin["spec"]["rules"][0]["filters"][0]["requestHeaderModifier"]["remove"]
    }
    assert "x-authentik-username" in removed


@pytest.mark.asyncio
async def test_list_environments_uses_admin_path() -> None:
    class FakeGateways:
        async def list_all(self) -> list[GatewayDesired]:
            return [
                GatewayDesired(
                    key=GatewayKey(namespace="team-a", name="main"),
                    image="img",
                    admin_token_secret_ref=SecretRef(name="t"),
                    master_password_secret_ref=SecretRef(name="p"),
                    public_route=RouteDesired(
                        hostname="vmcp.example.com",
                        gateway_ref=GatewayParentRef(name="kgateway"),
                    ),
                    admin_route=RouteDesired(
                        hostname="vmcp.example.com",
                        gateway_ref=GatewayParentRef(name="kgateway"),
                        path="admin",
                    ),
                )
            ]

    rows = await ListEnvironments(gateways=FakeGateways(), phases={}).execute()
    assert rows[0].admin_url == "https://vmcp.example.com/admin"


@pytest.mark.asyncio
async def test_invalid_admin_spec_sets_status_not_crash() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )
    rt = OperatorRuntime.in_memory(gateways={gw.key.as_str(): gw}, mcps={})
    set_runtime(rt)
    try:
        patch = FakePatch()
        spec = _base_spec()
        spec["adminRoute"] = {"path": "nope"}
        await handlers.reconcile_gateway(
            namespace="team-a",
            name="main",
            spec=spec,
            meta={"uid": "gw-uid-1", "generation": 9},
            patch=patch,
        )
        assert patch.status["phase"] == "Invalid"
        assert patch.status["conditions"][0]["reason"] == "InvalidSpec"
        assert "adminRoute.path" in patch.status["conditions"][0]["message"]
        assert patch.status["observedGeneration"] == 9
    finally:
        set_runtime(None)


@pytest.mark.asyncio
async def test_invalid_gateway_keyerror_sets_status() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )
    rt = OperatorRuntime.in_memory(gateways={gw.key.as_str(): gw}, mcps={})
    set_runtime(rt)
    try:
        patch = FakePatch()
        spec = _base_spec()
        del spec["image"]
        await handlers.reconcile_gateway(
            namespace="team-a",
            name="main",
            spec=spec,
            meta={"uid": "gw-uid-1", "generation": 4},
            patch=patch,
        )
        assert patch.status["phase"] == "Invalid"
        assert patch.status["conditions"][0]["reason"] == "InvalidSpec"
    finally:
        set_runtime(None)


def test_malformed_extra_header_modifier_is_ignored() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="vmcp"),
        image="registry.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname="vmcp.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            extra_filters=(
                {"type": "RequestHeaderModifier"},
                {
                    "type": "RequestHeaderModifier",
                    "requestHeaderModifier": {
                        "remove": ["X-A", "x-a"],
                        "set": ["not-a-dict", {"name": "X-B", "value": "1"}],
                        "add": [{"name": "X-C", "value": "2"}],
                    },
                },
            ),
            strip_client_identity_headers=False,
        ),
    )
    public = next(
        m
        for m in RenderGatewayManifests().execute(gw, _artifacts())
        if m["metadata"]["name"] == "vmcp-public"
    )
    rhm = public["spec"]["rules"][0]["filters"][0]["requestHeaderModifier"]
    assert rhm["remove"] == ["X-A"]
    assert rhm["set"] == [{"name": "X-B", "value": "1"}]
    assert rhm["add"] == [{"name": "X-C", "value": "2"}]


@pytest.mark.asyncio
async def test_invalid_mcp_spec_sets_status_not_crash() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )
    rt = OperatorRuntime.in_memory(gateways={gw.key.as_str(): gw}, mcps={})
    set_runtime(rt)
    try:
        patch = FakePatch()
        await handlers.reconcile_mcp(
            namespace="team-a",
            name="docs",
            spec={"gatewayRef": {"name": "main"}, "source": {"type": "Stdio"}},
            meta={"uid": "mcp-uid-1", "generation": 2},
            patch=patch,
        )
        assert patch.status["phase"] == "Invalid"
        assert patch.status["conditions"][0]["reason"] == "InvalidSpec"
    finally:
        set_runtime(None)


def test_map_gcf_and_identity_strip() -> None:
    spec = _base_spec()
    spec["gql"] = {"gcf": True, "maxDepth": 8}
    spec["proxy"] = {"enabled": True, "gcf": True}
    spec["identityStrip"] = {"manageListenerPolicy": False}
    gw = map_gateway("team-a", "gateway", spec)
    assert gw.gql.gcf is True
    assert gw.gql.max_depth == 8
    assert gw.proxy.gcf is True
    assert gw.identity_strip.manage_listener_policy is False


def test_map_colocated_sample() -> None:
    doc = yaml.safe_load(
        Path("deploy/samples/gateway-authentik-colocated.yaml").read_text(encoding="utf-8")
    )
    gw = map_gateway(doc["metadata"]["namespace"], doc["metadata"]["name"], doc["spec"])
    assert gw.public_route.gateway_ref.namespace is None
    assert gw.admin_route is not None
    assert gw.admin_route.hostname == gw.public_route.hostname
    assert ("dayana", "mcp:use upstream:dayana") in gw.auth.authentik.group_scopes
    plan = plan_early_identity_strip(gw)
    assert plan.phase == "Applied"
    policy = plan.objects[0]
    assert policy["kind"] == "ListenerPolicy"
    assert policy["metadata"]["namespace"] == "team-a"
    assert policy["spec"]["targetRefs"][0]["sectionName"] == "https"
    removed = {
        h.lower()
        for h in policy["spec"]["default"]["httpSettings"]["earlyRequestHeaderModifier"][
            "remove"
        ]
    }
    assert "x-authentik-username" in removed
    assert "x-vmcp-forward-auth" in removed


def test_early_strip_skipped_when_parent_is_cross_namespace() -> None:
    spec = _base_spec()
    gw = map_gateway("vmcp", "gateway", spec)
    plan = plan_early_identity_strip(gw)
    assert plan.phase == "SkippedCrossNamespace"
    assert plan.objects == ()
    assert "gw/kgateway" in plan.message


def test_early_strip_disabled_when_manage_false_or_no_strip() -> None:
    spec = _base_spec()
    spec["identityStrip"] = {"manageListenerPolicy": False}
    spec["publicRoute"]["gatewayRef"] = {"name": "kgateway"}
    gw = map_gateway("team-a", "gateway", spec)
    assert plan_early_identity_strip(gw).phase == "Disabled"

    gw_none = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="vmcp"),
        image="img",
        admin_token_secret_ref=SecretRef(name="t"),
        master_password_secret_ref=SecretRef(name="p"),
        public_route=RouteDesired(
            hostname="vmcp.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            strip_client_identity_headers=False,
        ),
    )
    assert plan_early_identity_strip(gw_none).phase == "Disabled"
    assert "no identity strip" in plan_early_identity_strip(gw_none).message


def test_early_strip_same_ns_and_skip_mixed_parents() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="vmcp"),
        image="img",
        admin_token_secret_ref=SecretRef(name="t"),
        master_password_secret_ref=SecretRef(name="p"),
        public_route=RouteDesired(
            hostname="vmcp.example.com",
            gateway_ref=GatewayParentRef(name="kgateway", section_name="https"),
        ),
        admin_route=RouteDesired(
            hostname="admin.example.com",
            gateway_ref=GatewayParentRef(
                name="other", namespace="gateway-system", section_name="https"
            ),
            path="/admin",
        ),
    )
    plan = plan_early_identity_strip(gw)
    assert plan.phase == "Applied"
    assert len(plan.objects) == 1
    assert plan.objects[0]["metadata"]["name"] == "vmcp-identity-strip-kgateway-https"
    assert "gateway-system/other#https" in plan.message


def test_early_strip_cross_namespace_without_section() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="vmcp"),
        image="img",
        admin_token_secret_ref=SecretRef(name="t"),
        master_password_secret_ref=SecretRef(name="p"),
        public_route=RouteDesired(
            hostname="vmcp.example.com",
            gateway_ref=GatewayParentRef(name="kgateway", namespace="gateway-system"),
        ),
    )
    plan = plan_early_identity_strip(gw)
    assert plan.phase == "SkippedCrossNamespace"
    assert "gateway-system/kgateway" in plan.message
    assert "#" not in plan.message.split("kgateway")[-1]


def test_listener_policy_name_sanitizes_section() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="vmcp"),
        image="img",
        admin_token_secret_ref=SecretRef(name="t"),
        master_password_secret_ref=SecretRef(name="p"),
        public_route=RouteDesired(
            hostname="vmcp.example.com",
            gateway_ref=GatewayParentRef(name="kgateway", section_name="HTTPS/443"),
        ),
    )
    plan = plan_early_identity_strip(gw)
    assert plan.objects[0]["metadata"]["name"] == "vmcp-identity-strip-kgateway-https-443"


def test_listener_policy_name_collapses_repeated_separators() -> None:
    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="vmcp"),
        image="img",
        admin_token_secret_ref=SecretRef(name="t"),
        master_password_secret_ref=SecretRef(name="p"),
        public_route=RouteDesired(
            hostname="vmcp.example.com",
            gateway_ref=GatewayParentRef(name="kgateway", section_name="HTTPS/-443"),
        ),
    )
    plan = plan_early_identity_strip(gw)
    assert plan.objects[0]["metadata"]["name"] == "vmcp-identity-strip-kgateway-https-443"


@pytest.mark.asyncio
async def test_reconcile_applies_listener_policy_with_owner() -> None:
    from vmcp_operator.adapters.driven.k8s.ssa import InMemoryApplier, ServerSideApply
    from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
    from vmcp_operator.adapters.driving.k8s.reconcile import GatewayReconcile
    from vmcp_operator.adapters.driving.k8s.runtime import EmptySkillLoader
    from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts

    gw = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="main"),
        image="img",
        admin_token_secret_ref=SecretRef(name="t"),
        master_password_secret_ref=SecretRef(name="p"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway", section_name="https"),
        ),
    )
    applier = InMemoryApplier()
    owner = {
        "apiVersion": "vmcp.io/v1alpha1",
        "kind": "VmcpGateway",
        "metadata": {"name": "main", "namespace": "team-a", "uid": "gw"},
    }
    result = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(), skill_loader=EmptySkillLoader()
        ),
        manifests=RenderGatewayManifests(),
        apply=ServerSideApply(applier=applier),
    ).execute(gw, [], owner=owner)
    assert result["listenerPolicy"] == "Applied"
    policy = next(
        item["body"] for item in (applier.applied or []) if item["body"]["kind"] == "ListenerPolicy"
    )
    assert policy["metadata"]["ownerReferences"][0]["uid"] == "gw"
    assert policy["spec"]["targetRefs"][0] == {
        "group": "gateway.networking.k8s.io",
        "kind": "Gateway",
        "name": "kgateway",
        "sectionName": "https",
    }
