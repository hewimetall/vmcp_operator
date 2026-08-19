# Compatibility: operator ↔ vmcp

| Operator contract | vmcp release | Notes |
| --- | --- | --- |
| `vmcp-registry` git pin | **v1.2.0** (`450f742…`) | Unchanged in v1.3.0; AuthFacade + `forward_identity` |
| Recommended Gateway image | `…/vmcp:1.3.0` | G25 catalog whitelist + optional GCF; hop trust from 1.2.0 |

## Features projected by the operator

| vmcp feature | CR / render path |
| --- | --- |
| HTTP `registry.json` + sidecars + skills | `VmcpMcpServer` → artifact ConfigMap |
| `forward_identity` (per upstream) | `VmcpMcpServer.spec.forwardIdentity` |
| Peer Gateway via `/mcp-proxy` | `source.type: VmcpProxy` (peer must `proxy.enabled`) |
| AuthFacade `local` \| `authentik` | `VmcpGateway.spec.auth` → `/config/vmcp.toml` |
| Admin auth `none` \| `basic` \| `authentik` | `spec.auth.admin` |
| Hop trust (`trusted_proxies` / hop secret) | `spec.auth.authentik.trustedProxies` + `forwardAuthSecretRef` |
| G25 per-caller catalog (vmcp ≥1.3) | `auth.authentik.groupScopes` values like `mcp:use upstream:<name>` — no extra CR field; image must be ≥1.3.0 |
| Optional GCF (vmcp ≥1.3) | `spec.gql.gcf` / `spec.proxy.gcf` → `[gql].gcf` / `[proxy].gcf` |
| Public edge strip of client Authentik/hop headers | `publicRoute.stripClientIdentityHeaders` (default true) → HTTPRoute `RequestHeaderModifier.remove` |
| Pre-auth strip (kgateway OSS, vmcp ADR 0001) | Same-namespace `ListenerPolicy` `earlyRequestHeaderModifier`; skipped when `gatewayRef.namespace` differs (`status.listenerPolicy`) |
| Admin hop inject + same-host path | `adminRoute` inherits public hostname/`gatewayRef` when omitted; `path` default `/admin`; hop `set` merged into the same `RequestHeaderModifier` |
| Extra path HTTPRoutes | `spec.extraRoutes[]` (`name`+`path`; inherit host/parent) → `{gateway}-{name}` |
| Admin strip vs forward-auth | When hop inject is on, Authentik identity headers are kept (HTTPRoute RHM runs after kgateway extAuth) |
| CR status / GC | top-level `status.phase` + `observedGeneration` (+ `artifactSha256`, `listenerPolicy`, `crdSkew`, `CRDsReady`); finalizers; child `ownerReferences` |
| `enableServiceLinks: false` on Gateway pods | always (avoids `VMCP_PORT=tcp://…` when Gateway is named `vmcp`) |
| `public_base_url` override | `spec.publicBaseUrl` (else `https://{publicRoute.hostname}`) |
| BYO HTTPRoute | `publicRoute.manage` / `adminRoute.manage: false`; optional `extraFilters` |
| BYO ListenerPolicy | `spec.identityStrip.manageListenerPolicy: false` |
| Opaque attachments (e.g. TrafficPolicy) | `spec.attachments[]` SSA-applied with ownerReferences |
| Proxy / tasks / gql | `spec.proxy` / `spec.tasks` / `spec.gql` → toml |
| Admin tokens + master password | Secret mounts / `VMCP_AUTH__MASTER_PASSWORD_ARGON2` |
| Writable admin tokens (Token CRUD) | `adminTokenSecretRef.writable: true` → `/state/tokens.json` (seed once) |
| Upstream bearer `${ENV}` | `source.bearerSecretRef` → pod env |

## Catalog isolation (G25)

vmcp 1.2 already maps Authentik groups to MCP scopes. vmcp **1.3.0** also
filters GraphQL / `tools/list` / prompts by `upstream:<name>` tokens
([ADR 0002](https://github.com/hewimetall/vmcp/blob/v1.3.0/docs/adr/0002-per-caller-catalog-visibility.md)):

```yaml
auth:
  authentik:
    groupScopes:
      dayana: "mcp:use upstream:dayana"
      mcp-admins: "mcp:admin"
```

`mcp:use` without `upstream:*` still sees the full catalogue (same as call
grants). `mcp:admin` sees everything for discovery. Use a **1.3.0** Gateway
image for this behaviour.

## Secrets

1. **`adminTokenSecretRef`** — Secret key (default `token`) with `tokens.json` body; mounted read-only at `/secrets/tokens.json`, or seeded to `/state/tokens.json` when `writable: true`.
2. **`masterPasswordSecretRef`** — argon2id hash (`vmcp hash-password`), injected as `VMCP_AUTH__MASTER_PASSWORD_ARGON2`.
3. **`auth.authentik.forwardAuthSecretRef`** (optional) — hop secret → `VMCP_AUTH__AUTHENTIK__FORWARD_AUTH_SECRET`.

When `forwardAuth: true`, set `trustedProxies` and/or `forwardAuthSecretRef` (vmcp fail-closed).

## Samples

- Local OAuth: `deploy/samples/gateway.yaml`
- Authentik + hop trust (Gateway in another namespace): `deploy/samples/gateway-authentik.yaml`
- Authentik same-host `/admin`: `deploy/samples/gateway-authentik-same-host.yaml`
- Authentik + colocated Gateway (early ListenerPolicy strip): `deploy/samples/gateway-authentik-colocated.yaml`
- External SaaS upstream: `deploy/samples/mcp-server.yaml` (`forwardIdentity: false`)
- Internal adapter: `deploy/samples/mcp-internal.yaml` (`forwardIdentity: true`)
- Peer via vmcp-proxy: `deploy/samples/mcp-vmcp-proxy.yaml`
