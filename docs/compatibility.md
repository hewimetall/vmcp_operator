# Compatibility: operator ↔ vmcp

| Operator contract | vmcp release | Notes |
| --- | --- | --- |
| `vmcp-registry` git pin | **v1.2.0** (`450f742…`) | AuthFacade wire + `forward_identity` |
| Recommended Gateway image | `…/vmcp:1.2.0` (or newer) | Hop trust + identity propagation |

## Features projected by the operator

| vmcp feature | CR / render path |
| --- | --- |
| HTTP `registry.json` + sidecars + skills | `VmcpMcpServer` → artifact ConfigMap |
| `forward_identity` (per upstream) | `VmcpMcpServer.spec.forwardIdentity` |
| Peer Gateway via `/mcp-proxy` | `source.type: VmcpProxy` (peer must `proxy.enabled`) |
| AuthFacade `local` \| `authentik` | `VmcpGateway.spec.auth` → `/config/vmcp.toml` |
| Admin auth `none` \| `basic` \| `authentik` | `spec.auth.admin` |
| Hop trust (`trusted_proxies` / hop secret) | `spec.auth.authentik.trustedProxies` + `forwardAuthSecretRef` |
| Proxy / tasks / gql | `spec.proxy` / `spec.tasks` / `spec.gql` → toml |
| Admin tokens + master password | Secret mounts / `VMCP_AUTH__MASTER_PASSWORD_ARGON2` |
| Upstream bearer `${ENV}` | `source.bearerSecretRef` → pod env |

## Secrets

1. **`adminTokenSecretRef`** — Secret key (default `token`) with `tokens.json` body; mounted at `/secrets/tokens.json`.
2. **`masterPasswordSecretRef`** — argon2id hash (`vmcp hash-password`), injected as `VMCP_AUTH__MASTER_PASSWORD_ARGON2`.
3. **`auth.authentik.forwardAuthSecretRef`** (optional) — hop secret → `VMCP_AUTH__AUTHENTIK__FORWARD_AUTH_SECRET`.

When `forwardAuth: true`, set `trustedProxies` and/or `forwardAuthSecretRef` (vmcp fail-closed).

## Samples

- Local OAuth: `deploy/samples/gateway.yaml`
- Authentik + hop trust: `deploy/samples/gateway-authentik.yaml`
- External SaaS upstream: `deploy/samples/mcp-server.yaml` (`forwardIdentity: false`)
- Internal adapter: `deploy/samples/mcp-internal.yaml` (`forwardIdentity: true`)
- Peer via vmcp-proxy: `deploy/samples/mcp-vmcp-proxy.yaml`
