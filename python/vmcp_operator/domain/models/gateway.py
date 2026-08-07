"""Immutable Gateway desired/observed models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


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
    # Public: strip client-forged Authentik / hop headers (defence in depth).
    strip_client_identity_headers: bool = True
    # Admin: set hop header from forwardAuthSecretRef (None = auto when secret set).
    inject_forward_auth_header: bool | None = None


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
class GqlDesired:
    max_complexity: int = 1000
    max_depth: int = 10


class AuthProvider(StrEnum):
    LOCAL = "local"
    AUTHENTIK = "authentik"


class AdminAuthMode(StrEnum):
    NONE = "none"
    BASIC = "basic"
    AUTHENTIK = "authentik"


@dataclass(frozen=True, slots=True)
class AdminAuthDesired:
    mode: AdminAuthMode = AdminAuthMode.BASIC
    required_groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthentikDesired:
    issuer: str = ""
    jwks_url: str = ""
    audiences: tuple[str, ...] = ()
    accept_bearer: bool = True
    forward_auth: bool = True
    username_header: str = "x-authentik-username"
    groups_header: str = "x-authentik-groups"
    groups_claim: str = "groups"
    group_scopes: tuple[tuple[str, str], ...] = ()
    trusted_proxies: tuple[str, ...] = ()
    forward_auth_secret_ref: SecretRef | None = None
    forward_auth_secret_header: str = "x-vmcp-forward-auth"


@dataclass(frozen=True, slots=True)
class AuthDesired:
    enabled: bool = True
    provider: AuthProvider = AuthProvider.LOCAL
    admin: AdminAuthDesired = field(default_factory=AdminAuthDesired)
    authentik: AuthentikDesired = field(default_factory=AuthentikDesired)


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
    gql: GqlDesired = GqlDesired()
    auth: AuthDesired = AuthDesired()
    skill_refs: tuple[SkillRef, ...] = ()
    # Override derived ``https://{publicRoute.hostname}`` in vmcp.toml.
    public_base_url: str | None = None
    generation: int = 1


# Headers clients must never supply on the public edge (issue #4 Gap 1).
PUBLIC_STRIP_IDENTITY_HEADERS: tuple[str, ...] = (
    "X-authentik-username",
    "X-authentik-groups",
    "X-authentik-uid",
    "X-authentik-name",
    "X-authentik-email",
    "X-authentik-entitlements",
    "X-Vmcp-Forward-Auth",
)
