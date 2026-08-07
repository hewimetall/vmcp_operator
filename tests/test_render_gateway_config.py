from __future__ import annotations

from vmcp_operator.domain.models.gateway import (
    AdminAuthDesired,
    AdminAuthMode,
    AuthDesired,
    AuthentikDesired,
    AuthProvider,
    GatewayDesired,
    GatewayKey,
    GatewayParentRef,
    ProxyDesired,
    RouteDesired,
    SecretRef,
    TasksDesired,
)
from vmcp_operator.domain.usecases.render_gateway_config import render_gateway_config


def _gateway(**kwargs: object) -> GatewayDesired:
    base = dict(
        key=GatewayKey(namespace="team-a", name="main"),
        image="harbor.example.com/ai/vmcp:1.2.0",
        admin_token_secret_ref=SecretRef(name="tokens"),
        master_password_secret_ref=SecretRef(name="pass", key="password"),
        public_route=RouteDesired(
            hostname="main.example.com",
            gateway_ref=GatewayParentRef(name="kgateway"),
        ),
    )
    base.update(kwargs)
    return GatewayDesired(**base)  # type: ignore[arg-type]


def test_render_local_auth_defaults() -> None:
    text = render_gateway_config(_gateway())
    assert 'host = "0.0.0.0"' in text
    assert "port = 8080" in text
    assert 'public_base_url = "https://main.example.com"' in text
    assert 'provider = "local"' in text
    assert 'mode = "basic"' in text
    assert "[auth.authentik]" not in text
    assert 'tokens_file = "/secrets/tokens.json"' in text


def test_render_authentik_hop_trust_and_proxy_tasks() -> None:
    text = render_gateway_config(
        _gateway(
            proxy=ProxyDesired(enabled=True, path="/mcp-proxy"),
            tasks=TasksDesired(enabled=True, max_concurrent=2),
            auth=AuthDesired(
                provider=AuthProvider.AUTHENTIK,
                admin=AdminAuthDesired(
                    mode=AdminAuthMode.AUTHENTIK,
                    required_groups=("mcp-admins",),
                ),
                authentik=AuthentikDesired(
                    issuer="https://auth.example.com/application/o/mcp/",
                    jwks_url="https://auth.example.com/application/o/mcp/jwks/",
                    audiences=("https://main.example.com/mcp",),
                    trusted_proxies=("10.244.0.0/16",),
                    group_scopes=(("mcp-users", "mcp:use"), ("mcp-admins", "mcp:admin")),
                    forward_auth_secret_ref=SecretRef(name="hop", key="secret"),
                ),
            ),
        )
    )
    assert 'provider = "authentik"' in text
    assert 'mode = "authentik"' in text
    assert 'required_groups = ["mcp-admins"]' in text
    assert 'trusted_proxies = ["10.244.0.0/16"]' in text
    assert 'group_scopes = { "mcp-users" = "mcp:use", "mcp-admins" = "mcp:admin" }' in text
    assert "[proxy]" in text
    assert "enabled = true" in text
    assert "max_concurrent = 2" in text
