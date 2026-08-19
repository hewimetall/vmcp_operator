"""Close remaining branch/line gaps so every measured module is ≥98%."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from vmcp_operator.adapters.driven.k8s.kr8s_applier import (
    ConflictError,
    Kr8sServerSideApplier,
)
from vmcp_operator.adapters.driven.k8s.secret_loader import InMemorySecretValueLoader
from vmcp_operator.adapters.driven.k8s.ssa import InMemoryApplier, ServerSideApply
from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.adapters.driving.k8s.finalizer_patch import schedule_finalizer_adds
from vmcp_operator.adapters.driving.k8s.mapping import mcp_to_crd, mcp_to_public_dict
from vmcp_operator.adapters.driving.k8s.reconcile import GatewayReconcile
from vmcp_operator.adapters.driving.k8s.runtime import (
    EmptySkillLoader,
    OperatorRuntime,
    get_runtime,
    set_runtime,
)
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
    SkillRef,
)
from vmcp_operator.domain.models.mcp import (
    ContainerImageSource,
    McpEndpoint,
    McpServerDesired,
    NamedPort,
    RemoteHttpSource,
    ToolOverrideDesired,
    VmcpProxySource,
    WebExposureDesired,
)
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import (
    RenderGatewayManifests,
    _identity_remove_headers,
    _parent_ref,
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


def _gw(**kwargs: Any) -> GatewayDesired:
    base = dict(
        key=GatewayKey(namespace="team-a", name="main"),
        image="registry.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway", namespace="gw", section_name="https"),
        ),
    )
    base.update(kwargs)
    return GatewayDesired(**base)


@pytest.mark.asyncio
async def test_reconcile_hop_ref_none_and_wants_helpers() -> None:
    from vmcp_operator.adapters.driving.k8s import reconcile as rec

    # admin_route missing → no inject
    assert rec._wants_admin_hop_inject(_gw(admin_route=None)) is False
    # explicit false
    assert (
        rec._wants_admin_hop_inject(
            _gw(
                admin_route=RouteDesired(
                    hostname="a.example.com",
                    gateway_ref=GatewayParentRef(name="kgateway"),
                    inject_forward_auth_header=False,
                )
            )
        )
        is False
    )
    # want is None + secret present → True (auto)
    assert (
        rec._wants_admin_hop_inject(
            _gw(
                admin_route=RouteDesired(
                    hostname="a.example.com",
                    gateway_ref=GatewayParentRef(name="kgateway"),
                    inject_forward_auth_header=None,
                ),
                auth=AuthDesired(
                    provider=AuthProvider.AUTHENTIK,
                    authentik=AuthentikDesired(
                        forward_auth_secret_ref=SecretRef(name="hop", key="secret")
                    ),
                ),
            )
        )
        is True
    )
    # want is None + no secret → False
    assert (
        rec._wants_admin_hop_inject(
            _gw(
                admin_route=RouteDesired(
                    hostname="a.example.com",
                    gateway_ref=GatewayParentRef(name="kgateway"),
                    inject_forward_auth_header=None,
                ),
                auth=AuthDesired(authentik=AuthentikDesired()),
            )
        )
        is False
    )
    # extraRoutes hop inject without admin route
    assert (
        rec._wants_admin_hop_inject(
            _gw(
                admin_route=None,
                extra_routes=(
                    RouteDesired(
                        hostname="a.example.com",
                        gateway_ref=GatewayParentRef(name="kgateway"),
                        path="/mcp",
                        route_name="mcp",
                        inject_forward_auth_header=True,
                    ),
                ),
            )
        )
        is True
    )

    # secrets present, inject wanted, but secret ref missing → line 64
    gw = _gw(
        admin_route=RouteDesired(
            hostname="a.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            inject_forward_auth_header=True,
        ),
        auth=AuthDesired(
            provider=AuthProvider.AUTHENTIK,
            authentik=AuthentikDesired(forward_auth_secret_ref=None),
        ),
    )
    result = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(), skill_loader=EmptySkillLoader()
        ),
        manifests=RenderGatewayManifests(),
        apply=ServerSideApply(applier=InMemoryApplier()),
        secrets=InMemorySecretValueLoader(values={("team-a", "hop", "secret"): "x"}),
    ).execute(gw, [])
    assert result["adminHopHeaderInjected"] is False

    # empty secret value
    gw2 = _gw(
        admin_route=RouteDesired(
            hostname="a.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
            inject_forward_auth_header=True,
        ),
        auth=AuthDesired(
            provider=AuthProvider.AUTHENTIK,
            authentik=AuthentikDesired(
                forward_auth_secret_ref=SecretRef(name="hop", key="secret")
            ),
        ),
    )
    result2 = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(), skill_loader=EmptySkillLoader()
        ),
        manifests=RenderGatewayManifests(),
        apply=ServerSideApply(applier=InMemoryApplier()),
        secrets=InMemorySecretValueLoader(values={("team-a", "hop", "secret"): "  "}),
    ).execute(gw2, [])
    assert result2["adminHopHeaderInjected"] is False


def test_finalizer_patch_accepts_non_list_fns() -> None:
    class FnsBag:
        def __init__(self) -> None:
            self.items: list[Any] = []

        def append(self, item: Any) -> None:
            self.items.append(item)

    patch = SimpleNamespace(fns=FnsBag())
    schedule_finalizer_adds(patch, ("vmcp.io/x",))
    assert len(patch.fns.items) == 1


def test_render_identity_headers_custom_and_dedupe() -> None:
    gw = _gw(
        auth=AuthDesired(
            authentik=AuthentikDesired(
                username_header="X-Custom-User",
                groups_header="x-authentik-groups",  # duplicate of canonical
                forward_auth_secret_header="X-Hop",
            )
        )
    )
    removed = _identity_remove_headers(gw)
    lower = [h.lower() for h in removed]
    assert "x-custom-user" in lower
    assert "x-hop" in lower
    assert lower.count("x-authentik-groups") == 1
    ref = _parent_ref(GatewayParentRef(name="kgateway", namespace="ns", section_name="https"))
    assert ref == {"name": "kgateway", "namespace": "ns", "sectionName": "https"}


def test_render_skips_disabled_mcp_bearer_env() -> None:
    gw = _gw()
    mcps = [
        McpServerDesired(
            namespace="team-a",
            name="off",
            gateway_key=gw.key,
            enabled=False,
            description=None,
            source=RemoteHttpSource(
                url="https://x",
                bearer_secret_ref=SecretRef(name="b", key="t"),
            ),
        ),
        McpServerDesired(
            namespace="team-a",
            name="other-gw",
            gateway_key=GatewayKey(namespace="team-a", name="other"),
            enabled=True,
            description=None,
            source=RemoteHttpSource(
                url="https://y",
                bearer_secret_ref=SecretRef(name="b2", key="t"),
            ),
        ),
    ]
    manifests = RenderGatewayManifests().execute(gw, _artifacts(), mcps)
    deploy = next(m for m in manifests if m["kind"] == "Deployment")
    env_names = {e["name"] for e in deploy["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert "VMCP_BEARER_OFF" not in env_names
    assert "VMCP_BEARER_OTHER_GW" not in env_names


def test_mcp_to_public_and_crd_source_edges() -> None:
    container = McpServerDesired(
        namespace="team-a",
        name="c4",
        gateway_key=GatewayKey(namespace="team-a", name="main"),
        enabled=True,
        description="d",
        source=ContainerImageSource(
            image="img:1",
            ports=(NamedPort(name="http", container_port=8080),),
            mcp_endpoint=McpEndpoint(port_name="http", path="/mcp"),
            env=(("A", "1"),),
        ),
        tool_overrides=(ToolOverrideDesired(name="t", read_only=True, task_support="optional"),),
        skill_refs=(SkillRef(name="s", key="k"),),
        web_exposures=(
            WebExposureDesired(
                name="ui",
                port_name="http",
                hostname="ui.example.com",
                paths=("/",),
                gateway_ref=GatewayParentRef(
                    name="kgateway", namespace="gw", section_name="https"
                ),
                annotations=(("a", "b"),),
                public_base_url_env="PUBLIC",
            ),
        ),
        forward_identity=True,
    )
    public = mcp_to_public_dict(container)
    assert public["source"]["type"] == "ContainerImage"
    crd = mcp_to_crd(container)
    assert crd["spec"]["source"]["env"] == [{"name": "A", "value": "1"}]
    assert crd["spec"]["webExposures"][0]["gatewayRef"]["sectionName"] == "https"

    proxy = McpServerDesired(
        namespace="team-a",
        name="peer",
        gateway_key=GatewayKey(namespace="team-a", name="main"),
        enabled=True,
        description=None,
        source=VmcpProxySource(
            peer=GatewayKey(namespace="other", name="code"),
            bearer_secret_ref=SecretRef(name="tok", key="token"),
        ),
    )
    pub2 = mcp_to_public_dict(proxy)
    assert pub2["source"]["bearerSecretRef"]["name"] == "tok"
    crd2 = mcp_to_crd(proxy)
    assert crd2["spec"]["source"]["peerGatewayRef"]["namespace"] == "other"
    assert crd2["spec"]["source"]["bearerSecretRef"]["key"] == "token"

    remote = McpServerDesired(
        namespace="team-a",
        name="docs",
        gateway_key=GatewayKey(namespace="team-a", name="main"),
        enabled=True,
        description=None,
        source=RemoteHttpSource(
            url="https://docs.example/mcp",
            bearer_secret_ref=SecretRef(name="r", key="token"),
        ),
    )
    pub3 = mcp_to_public_dict(remote)
    assert pub3["source"]["bearerSecretRef"] == {"name": "r", "key": "token"}
    crd3 = mcp_to_crd(remote)
    assert crd3["spec"]["source"]["bearerSecretRef"]["name"] == "r"


@pytest.mark.asyncio
async def test_runtime_default_branch_and_for_cluster_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_runtime(None)
    monkeypatch.setenv("VMCP_OPERATOR_RUNTIME", "default-local")
    monkeypatch.delenv("KUBECONFIG", raising=False)
    rt = get_runtime()
    assert isinstance(rt, OperatorRuntime)
    set_runtime(None)

    class FakeCatalog:
        async def list_for_gateway(self, key: GatewayKey) -> list[McpServerDesired]:
            return []

    class FakeGateways:
        async def get(self, key: GatewayKey) -> GatewayDesired | None:
            return None

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.mcp_catalog.Kr8sMcpCatalog",
        lambda: FakeCatalog(),
    )
    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.gateway_catalog.Kr8sGatewayRepository",
        lambda: FakeGateways(),
    )
    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.secret_loader.Kr8sSecretValueLoader",
        lambda: InMemorySecretValueLoader(),
    )
    from vmcp_operator.adapters.driven.k8s.gateway_toucher import RecordingGatewayToucher

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.gateway_toucher.Kr8sGatewayToucher",
        RecordingGatewayToucher,
    )
    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.Kr8sServerSideApplier",
        InMemoryApplier,
    )
    cluster = OperatorRuntime.for_cluster()
    assert await cluster.list_mcps(GatewayKey("ns", "gw")) == []
    assert await cluster.get_gateway(GatewayKey("ns", "gw")) is None
    set_runtime(None)
    monkeypatch.setenv("VMCP_OPERATOR_RUNTIME", "kr8s")
    via_env = get_runtime()
    assert via_env.gateway_toucher is not None
    # touch without toucher
    bare = OperatorRuntime.in_memory(gateway_toucher=None)
    bare.gateway_toucher = None
    await bare.touch_gateway(GatewayKey("ns", "gw"))
    assert "ns/gw" in bare.pending
    set_runtime(None)


@pytest.mark.asyncio
async def test_ssa_preseeded_applied_list() -> None:
    existing: list[dict[str, Any]] = []
    applier = InMemoryApplier(applied=existing)
    ssa = ServerSideApply(applier=applier)
    await ssa.apply({"kind": "ConfigMap", "metadata": {"name": "z"}})
    assert existing and existing[0]["body"]["kind"] == "ConfigMap"


@pytest.mark.asyncio
async def test_kr8s_plain_conflict_and_not_found_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_api() -> object:
        return object()

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.kr8s.asyncio.api",
        fake_api,
    )

    class FakeObj:
        def __init__(self, body: dict[str, Any], api: Any = None) -> None:
            self.raw = dict(body)
            self.api = api
            self._exists = True

        async def exists(self) -> bool:
            return self._exists

        async def refresh(self) -> None:
            return None

        async def create(self) -> None:
            self._exists = True

        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            if kwargs.get("type") == "apply":
                raise RuntimeError("apply unsupported")
            raise RuntimeError("conflict on plain")

    def fake_new_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> FakeObj:
            return FakeObj(body, api=api)

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        fake_new_class,
    )
    applier = Kr8sServerSideApplier(api=object())
    body = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "z", "namespace": "ns"},
    }
    with pytest.raises(ConflictError):
        await applier.server_side_apply(body, field_manager="fm", force=False)

    class NotFoundObj(FakeObj):
        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            if kwargs.get("type") == "apply":
                raise RuntimeError("apply unsupported")
            raise RuntimeError("not found")

        async def create(self) -> None:
            self.raw["created"] = True

    def nf_class(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> NotFoundObj:
            return NotFoundObj(body, api=api)

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        nf_class,
    )
    out = await applier.server_side_apply(body, field_manager="fm", force=False)
    assert out.get("created") is True

    # Outer exists() path: apply fails non-conflict → plain → not found → create (L79)
    class ExistsNotFound(FakeObj):
        async def exists(self) -> bool:
            return True

        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            if kwargs.get("type") == "apply":
                raise RuntimeError("server-side apply rejected")
            raise RuntimeError("Not Found")

        async def create(self) -> None:
            self.raw = {**self.raw, "created": "via-79"}

    def exists_nf(**_kwargs: Any):
        def ctor(body: dict[str, Any], api: Any = None) -> ExistsNotFound:
            return ExistsNotFound(body, api=api)

        return ctor

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        exists_nf,
    )
    out2 = await applier.server_side_apply(body, field_manager="fm", force=False)
    assert out2.get("created") == "via-79"


@pytest.mark.asyncio
async def test_kr8s_plain_not_found_create_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dedicated path: apply rejected → plain not found → create."""

    async def fake_api() -> object:
        return object()

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.kr8s.asyncio.api",
        fake_api,
    )

    class Obj:
        def __init__(self, body: dict[str, Any], api: Any = None) -> None:
            self.raw = dict(body)
            self.api = api

        async def exists(self) -> bool:
            return True

        async def refresh(self) -> None:
            return None

        async def create(self) -> None:
            self.raw["ok"] = True

        async def patch(self, body: dict[str, Any], **kwargs: Any) -> None:
            if kwargs.get("type") == "apply":
                raise RuntimeError("cannot apply")
            raise RuntimeError("object not found in cache")

    monkeypatch.setattr(
        "vmcp_operator.adapters.driven.k8s.kr8s_applier.new_class",
        lambda **_: (lambda body, api=None: Obj(body, api)),
    )
    applier = Kr8sServerSideApplier(api=object())
    out = await applier.server_side_apply(
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "n", "namespace": "ns"}},
        field_manager="fm",
        force=False,
    )
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_main_dashboard_stubs_callable() -> None:
    from vmcp_operator.__main__ import _DeniedIssuer, _EmptyGateways

    with pytest.raises(LookupError):
        await _DeniedIssuer().issue_use_token(object(), "client")
    gw = _EmptyGateways()
    assert await gw.get(object()) is None
    assert await gw.list_all() == []
