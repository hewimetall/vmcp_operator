# Issue #4 — adoption gaps

Tracker: https://github.com/hewimetall/vmcp_operator/issues/4

| Item | Status |
| --- | --- |
| Runnable operator image + GHCR release workflow | PR #5 (merged) |
| Gap 1 — public HTTPRoute strips client Authentik / hop headers | PR #6 (merged) |
| Gap 2 — admin HTTPRoute sets hop header from `forwardAuthSecretRef` | PR #6 (merged) |
| Gap 3 — `enableServiceLinks: false` on Gateway pods | PR #6 (merged) |
| `publicBaseUrl` override | PR #6 (merged) |
| CRD status accepts reconciler writes (`phase` / `artifactSha256` / …) | This change |
| Finalizers land on Gateway / MCP CRs | This change |
| Child objects carry `ownerReferences` (GC) | This change |
| Admin route strips identity headers (symmetric with public) | This change |
| Writable admin tokens (`adminTokenSecretRef.writable`) | This change |
| BYO HTTPRoute (`manage: false`) + `extraFilters` + `attachments` | This change |
| `cryptography>=50` for free-threaded image builds | This change |
| README: GHCR requires authenticated pull | This change |

## Status / finalizers / ownership

Handlers write **top-level** `status.phase`, `status.observedGeneration`,
`status.artifactSha256` (Gateway), and `status.conditions` via Kopf `patch.status`.
Do not return status dicts — Kopf would nest them under `status.<handler_name>`,
which structural CRD schemas prune.

Finalizers (`vmcp.io/gateway-protection`, `vmcp.io/unregister-before-gc`) are
applied with `patch.fns` transforms. MCP membership changes bump Gateway
annotation `vmcp.io/mcp-generation` so delete unblocks after children are gone.

Rendered Deploy/Service/ConfigMap/PVC/HTTPRoute (and `spec.attachments`) get a
controller `ownerReference` to the parent CR.

## Edge filters

**Public** (`stripClientIdentityHeaders`, default `true`):

Removes at least `X-authentik-{username,groups,uid,name,email,entitlements}` and
`X-Vmcp-Forward-Auth` (plus configured username/groups/hop header names).

**Admin** (same strip + `injectForwardAuthHeader`):

Admin HTTPRoute removes the same identity headers, then optionally **sets** the
hop header from `forwardAuthSecretRef` so browser `/admin` after Authentik
forward-auth satisfies hop trust.

Note: Gateway API `RequestHeaderModifier.set` takes a literal value, so the hop
secret appears in the HTTPRoute object. Restrict `get/list` on HTTPRoutes
accordingly.

## Writable tokens / BYO routes

- `spec.adminTokenSecretRef.writable: true` — seed Secret into `/state/tokens.json`
  once (init copies only if missing) for Token CRUD persistence.
- `publicRoute.manage` / `adminRoute.manage: false` — skip operator HTTPRoute apply
  (bring-your-own). Pair with `spec.attachments` for kgateway `TrafficPolicy` etc.
- `extraFilters` — opaque Gateway API filters merged after built-in strip/inject.
