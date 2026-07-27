from __future__ import annotations

from typing import Any, cast

import pytest

from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.domain.models.artifacts import SkillDesired
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
    ToolOverrideDesired,
)
from vmcp_operator.domain.usecases.issue_use_token import (
    DuplicateTokenError,
    IssueUseToken,
)
from vmcp_operator.domain.usecases.list_environments import ListEnvironments
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts


class FakeGateways:
    def __init__(self, items: list[GatewayDesired]) -> None:
        self._items = {item.key.as_str(): item for item in items}

    async def get(self, key: GatewayKey) -> GatewayDesired | None:
        return self._items.get(key.as_str())

    async def list_all(self) -> list[GatewayDesired]:
        return list(self._items.values())


class FakeSkills:
    async def load_skills(self, gateway, mcps) -> list[SkillDesired]:
        return [
            SkillDesired(
                name="research_docs",
                description="research",
                template="go",
            )
        ]


class FakeIssuer:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    async def issue_use_token(self, key: GatewayKey, client_name: str) -> str:
        marker = f"{key.as_str()}:{client_name}"
        if marker in self.seen:
            raise FileExistsError("duplicate")
        self.seen.add(marker)
        return f"tok-{client_name}"


def _gateway(name: str = "main", ns: str = "team-a") -> GatewayDesired:
    return GatewayDesired(
        key=GatewayKey(namespace=ns, name=name),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens", key="tokens.json"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname=f"{name}.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
        admin_route=RouteDesired(
            hostname=f"admin-{name}.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )


@pytest.mark.asyncio
async def test_reconcile_artifacts_builds_remote_and_managed() -> None:
    gateway = _gateway()
    mcps = [
        McpServerDesired(
            namespace="team-a",
            name="context7",
            gateway_key=gateway.key,
            enabled=True,
            description="docs",
            source=RemoteHttpSource(
                url="https://context7.example/mcp",
                bearer_secret_ref=SecretRef(name="c7"),
            ),
            tool_overrides=(ToolOverrideDesired(name="resolve", read_only=True),),
        ),
        McpServerDesired(
            namespace="team-a",
            name="architect-c4",
            gateway_key=gateway.key,
            enabled=True,
            description="c4",
            source=ContainerImageSource(
                image="harbor.example.com/ai/architect-c4:1",
                ports=(NamedPort(name="http", container_port=8766),),
                mcp_endpoint=McpEndpoint(port_name="http", path="/mcp"),
            ),
        ),
    ]
    usecase = ReconcileGatewayArtifacts(renderer=RegistryEngine(), skill_loader=FakeSkills())
    bundle = await usecase.execute(gateway, mcps)
    registry = bundle.files["registry.json"].data
    assert "context7" in registry
    assert "architect-c4" in registry
    assert "team-a.svc:8766/mcp" in registry
    assert "skills/research_docs.yaml" in bundle.files


@pytest.mark.asyncio
async def test_list_environments_sorted() -> None:
    rows = await ListEnvironments(
        gateways=FakeGateways([_gateway("b"), _gateway("a")]),
        phases={"team-a/a": "Ready", "team-a/b": "Pending"},
    ).execute()
    assert [row.key.name for row in rows] == ["a", "b"]
    assert rows[0].admin_url == "https://admin-a.example.com/admin"


@pytest.mark.asyncio
async def test_issue_use_token_fixed_scope_and_duplicate() -> None:
    key = GatewayKey(namespace="team-a", name="main")
    usecase = IssueUseToken(gateways=FakeGateways([_gateway()]), issuer=FakeIssuer())
    issued = await usecase.execute(key, "cursor")
    assert issued.scope == "mcp:use"
    assert issued.token == "tok-cursor"
    with pytest.raises(DuplicateTokenError):
        await usecase.execute(key, "cursor")
    with pytest.raises(ValueError, match="non-empty"):
        await usecase.execute(key, "  ")
    with pytest.raises(LookupError):
        await usecase.execute(GatewayKey(namespace="missing", name="x"), "client")


@pytest.mark.asyncio
async def test_reconcile_artifacts_remote_without_bearer() -> None:
    gateway = _gateway()
    mcps = [
        McpServerDesired(
            namespace="team-a",
            name="open",
            gateway_key=gateway.key,
            enabled=True,
            description=None,
            source=RemoteHttpSource(url="https://open.example/mcp"),
        )
    ]
    usecase = ReconcileGatewayArtifacts(renderer=RegistryEngine(), skill_loader=FakeSkills())
    bundle = await usecase.execute(gateway, mcps)
    assert "open" in bundle.files["registry.json"].data
    assert '"bearer": null' in bundle.files["registry.json"].data


@pytest.mark.asyncio
async def test_reconcile_artifacts_rejects_unknown_source() -> None:
    gateway = _gateway()
    mcps = [
        McpServerDesired(
            namespace="team-a",
            name="weird",
            gateway_key=gateway.key,
            enabled=True,
            description=None,
            source=cast(Any, object()),
        )
    ]
    usecase = ReconcileGatewayArtifacts(renderer=RegistryEngine(), skill_loader=FakeSkills())
    with pytest.raises(TypeError, match="unsupported source"):
        await usecase.execute(gateway, mcps)


@pytest.mark.asyncio
async def test_reconcile_artifacts_requires_named_mcp_port() -> None:
    gateway = _gateway()
    mcps = [
        McpServerDesired(
            namespace="team-a",
            name="broken",
            gateway_key=gateway.key,
            enabled=True,
            description=None,
            source=ContainerImageSource(
                image="harbor.example.com/ai/x:1",
                ports=(NamedPort(name="metrics", container_port=9090),),
                mcp_endpoint=McpEndpoint(port_name="http", path="/mcp"),
            ),
        )
    ]
    usecase = ReconcileGatewayArtifacts(renderer=RegistryEngine(), skill_loader=FakeSkills())
    with pytest.raises(ValueError, match="portName"):
        await usecase.execute(gateway, mcps)


@pytest.mark.asyncio
async def test_list_environments_without_admin_route() -> None:
    gateway = GatewayDesired(
        key=GatewayKey(namespace="team-a", name="solo"),
        image="harbor.example.com/ai/vmcp:1",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass"),
        public_route=RouteDesired(
            hostname="solo.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
        admin_route=None,
    )
    rows = await ListEnvironments(gateways=FakeGateways([gateway]), phases={}).execute()
    assert rows[0].admin_url is None
    assert rows[0].phase == "Unknown"
