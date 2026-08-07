"""Immutable VmcpMcpServer desired models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vmcp_operator.domain.models.gateway import GatewayKey, GatewayParentRef, SecretRef, SkillRef


class SourceType(StrEnum):
    CONTAINER_IMAGE = "ContainerImage"
    REMOTE_HTTP = "RemoteHttp"


@dataclass(frozen=True, slots=True)
class NamedPort:
    name: str
    container_port: int
    protocol: str = "TCP"


@dataclass(frozen=True, slots=True)
class McpEndpoint:
    port_name: str
    path: str = "/mcp"


@dataclass(frozen=True, slots=True)
class WebExposureDesired:
    name: str
    port_name: str
    hostname: str
    paths: tuple[str, ...]
    gateway_ref: GatewayParentRef | None = None
    annotations: tuple[tuple[str, str], ...] = ()
    public_base_url_env: str | None = None


@dataclass(frozen=True, slots=True)
class ToolOverrideDesired:
    name: str
    read_only: bool
    task_support: str | None = None


@dataclass(frozen=True, slots=True)
class ContainerImageSource:
    image: str
    ports: tuple[NamedPort, ...]
    mcp_endpoint: McpEndpoint
    env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RemoteHttpSource:
    url: str
    bearer_secret_ref: SecretRef | None = None


@dataclass(frozen=True, slots=True)
class McpServerDesired:
    namespace: str
    name: str
    gateway_key: GatewayKey
    enabled: bool
    description: str | None
    source: ContainerImageSource | RemoteHttpSource
    tool_overrides: tuple[ToolOverrideDesired, ...] = ()
    skill_refs: tuple[SkillRef, ...] = ()
    web_exposures: tuple[WebExposureDesired, ...] = ()
    # Opt-in (vmcp v1.2+): forward X-Vmcp-Subject/Groups to this upstream.
    forward_identity: bool = False
