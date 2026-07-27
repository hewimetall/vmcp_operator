"""Immutable Gateway desired/observed models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecretRef:
    name: str
    key: str = "token"


@dataclass(frozen=True, slots=True)
class GatewayParentRef:
    name: str
    namespace: str | None = None
    section_name: str | None = None


@dataclass(frozen=True, slots=True)
class RouteDesired:
    hostname: str
    gateway_ref: GatewayParentRef
    annotations: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PersistenceDesired:
    size: str = "5Gi"
    storage_class_name: str | None = None
    reclaim_policy: str = "Retain"


@dataclass(frozen=True, slots=True)
class TasksDesired:
    enabled: bool = False
    max_concurrent: int = 1


@dataclass(frozen=True, slots=True)
class ProxyDesired:
    enabled: bool = False
    path: str = "/mcp-proxy"


@dataclass(frozen=True, slots=True)
class SkillRef:
    name: str
    key: str | None = None


@dataclass(frozen=True, slots=True)
class GatewayKey:
    namespace: str
    name: str

    def as_str(self) -> str:
        return f"{self.namespace}/{self.name}"


@dataclass(frozen=True, slots=True)
class GatewayDesired:
    key: GatewayKey
    image: str
    admin_token_secret_ref: SecretRef
    master_password_secret_ref: SecretRef
    public_route: RouteDesired
    admin_route: RouteDesired | None = None
    persistence: PersistenceDesired = PersistenceDesired()
    tasks: TasksDesired = TasksDesired()
    proxy: ProxyDesired = ProxyDesired()
    skill_refs: tuple[SkillRef, ...] = ()
    generation: int = 1
