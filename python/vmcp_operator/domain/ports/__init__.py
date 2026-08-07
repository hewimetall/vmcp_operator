"""Domain ports (protocols)."""

from __future__ import annotations

from typing import Protocol

from vmcp_operator.domain.models.artifacts import (
    ArtifactBundle,
    SkillDesired,
    UpstreamArtifactsDesired,
)
from vmcp_operator.domain.models.gateway import GatewayDesired, GatewayKey
from vmcp_operator.domain.models.mcp import McpServerDesired


class GatewayRepository(Protocol):
    async def get(self, key: GatewayKey) -> GatewayDesired | None: ...

    async def list_all(self) -> list[GatewayDesired]: ...


class McpServerRepository(Protocol):
    async def list_for_gateway(self, key: GatewayKey) -> list[McpServerDesired]: ...


class McpCatalog(Protocol):
    """Operator-owned VmcpMcpServer CR catalog (SoT for fleet MCP CRUD)."""

    async def list_for_gateway(self, key: GatewayKey) -> list[McpServerDesired]: ...

    async def get(self, namespace: str, name: str) -> McpServerDesired | None: ...

    async def upsert(self, mcp: McpServerDesired) -> McpServerDesired: ...

    async def delete(self, namespace: str, name: str) -> bool: ...


class SkillLoader(Protocol):
    async def load_skills(
        self, gateway: GatewayDesired, mcps: list[McpServerDesired]
    ) -> list[SkillDesired]: ...


class ArtifactRenderer(Protocol):
    def render_bundle(
        self,
        upstreams: list[UpstreamArtifactsDesired],
        skills: list[SkillDesired],
    ) -> ArtifactBundle: ...


class TokenIssuer(Protocol):
    async def issue_use_token(self, key: GatewayKey, client_name: str) -> str: ...


class EnvironmentSummary(Protocol):
    @property
    def key(self) -> GatewayKey: ...

    @property
    def phase(self) -> str: ...

    @property
    def public_hostname(self) -> str: ...

    @property
    def admin_url(self) -> str | None: ...
