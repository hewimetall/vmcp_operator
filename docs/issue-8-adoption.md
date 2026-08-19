# Issue #8 — 0.0.2 adoption (adminRoute, CRD skew, health)

Tracker: https://github.com/hewimetall/vmcp_operator/issues/8

| Item | Status |
| --- | --- |
| `adminRoute` without `gatewayRef` crashes reconcile (`BoxKeyError`) | Fixed — inherit from `publicRoute`, else `InvalidSpec` |
| Same-host admin (path on the public hostname) | `adminRoute.hostname` optional; `path` default `/admin` |
| Extra path routes (`/mcp`, `/health`, `/api/v1`, …) | `spec.extraRoutes[]` — HTTPRoute `{gateway}-{name}` |
| Two `RequestHeaderModifier` filters rejected by Gateway API | Merged into one filter (`remove` + `set` + `add`) |
| `stripClientIdentityHeaders` on admin undoes Authentik login | Authentik identity headers not stripped when hop inject is on |
| Pre-auth strip (before kgateway extAuth) | Same-namespace `ListenerPolicy` `earlyRequestHeaderModifier` |
| Image upgrade without matching CRDs silently prunes new fields | Startup inspect + `status.crdSkew` / condition `CRDsReady` |
| `phase` is not a liveness signal | Operator Deployment probes `/healthz` on `:8081`; CR lag is `observedGeneration` |

## adminRoute

`publicRoute` still requires `hostname` + `gatewayRef`. `adminRoute` does not:
omitted `hostname` / `gatewayRef` inherit from `publicRoute`. The crash repro

```bash
kubectl patch vmcpgateway gateway -n vmcp --type=merge \
  -p '{"spec":{"adminRoute":{"injectForwardAuthHeader":true}}}'
```

now renders an admin HTTPRoute on the **public hostname** at path `/admin`
(Gateway API longest-prefix match vs public `/`). A distinct admin host still
works when `hostname` is set.

Additional paths (`/mcp`, `/mcp-proxy`, `/api/v1`, `/health`, `/ready`) are
`spec.extraRoutes[]`. Each item needs `name` + `path`; omitted `hostname` /
`gatewayRef` inherit from `publicRoute`. The operator applies HTTPRoute
`{gateway}-{name}` (so attachments can target `kind: HTTPRoute`,
`name: main-mcp`). Hop inject on extra routes is **opt-in**
(`injectForwardAuthHeader: true`). `manage: false` skips that HTTPRoute.

Invalid mapping (missing public hostname, `path` without a leading `/`,
non-object `gatewayRef`) sets `status.phase=Invalid` / `reason=InvalidSpec`
instead of crashing the reconciler.

## Header filters (kgateway 2.3)

Gateway API allows **at most one** `RequestHeaderModifier` per HTTPRoute rule.
Built-in strip + hop inject + any `extraFilters` of that type are merged.

kgateway applies HTTPRoute `RequestHeaderModifier` **after** extAuth. On an
admin route that also injects the hop header, the operator therefore does
**not** remove `X-authentik-*` (or the configured username/groups headers) in
that filter — doing so deletes the identity forward-auth just wrote
(`missing X-authentik-username`). Client-forged hop headers are still
overwritten by `set`.

### Pre-auth strip (vmcp ADR 0001)

The intended order is: strip client `X-authentik-*` and the hop header **before**
Authentik/outpost re-inject identity, then set the hop secret on `/admin`.

OSS kgateway can only do that with a `ListenerPolicy`
`spec.default.httpSettings.earlyRequestHeaderModifier`. That CR:

- must live in the **same namespace** as the parent `Gateway` (no
  `targetRefs[].namespace`)
- is **listener-scoped** (before route match) — `sectionName` is honoured when set
- conflicts with any other ListenerPolicy that also sets `httpSettings` on the
  same listener (kgateway keeps the oldest)

When `stripClientIdentityHeaders` is true and
`identityStrip.manageListenerPolicy` is true (the default), the operator applies
an owned `{gateway}-identity-strip-{parent}[-{section}]` ListenerPolicy **if**
the parent Gateway is in the VmcpGateway namespace. Cross-namespace parents
(typical `gateway-system`) set `status.listenerPolicy.phase=SkippedCrossNamespace`
and leave HTTPRoute behaviour unchanged so login still works.

Colocate the Gateway with the VmcpGateway (omit `gatewayRef.namespace`, or set
it to the tenant namespace) to get the early strip. Sample:
`deploy/samples/gateway-authentik-colocated.yaml`.

Bring-your-own: `spec.identityStrip.manageListenerPolicy: false` plus an
attachment or a ListenerPolicy you manage in the Gateway namespace.

Two VmcpGateways that share one listener and both emit `httpSettings` will
race — only the first-created ListenerPolicy wins. Prefer one Gateway per
tenant listener, or a single BYO policy.

## Upgrading image vs CRDs

The operator image and the CRDs are separate artifacts. Applying a newer
image with older CRDs does **not** error: the API server **prunes** unknown
`spec` fields (`stripClientIdentityHeaders`, `manage`, `extraFilters`,
`path`, `identityStrip`, `gql.gcf`, …). The operator looks upgraded and
silently ignores the new configuration.

Always apply `charts/vmcp-operator/crds/` at the **same tag** as the image
(`kubectl apply --server-side` before `helm upgrade --skip-crds`). See
[charts/vmcp-operator/README.md](../charts/vmcp-operator/README.md).

At startup the operator reads the live `VmcpGateway` CRD and writes
`status.crdSkew` plus condition `CRDsReady` (`Current` / `SchemaSkew`) on
every reconcile. A `False` `CRDsReady` means the API server will prune
fields this image understands (`identityStrip`, `extraRoutes`, `gql.gcf`, …).
Set `VMCP_OPERATOR_SKIP_CRD_CHECK=1` only in unit tests.

Release images are published only on `v*` tags ([docs/release.md](release.md)).

## Health: operator process vs CR `phase`

The operator Deployment serves Kopf liveness at `http://0.0.0.0:8081/healthz`
(kubelet `livenessProbe` / `readinessProbe`). That is the process health
signal.

`status.phase` is persisted on the CR. Scaling the operator to zero leaves
`phase=Applied` even though nothing is reconciling.

A live operator has caught up on a given CR when `status.observedGeneration`
equals `metadata.generation`. `kubectl get vmcpgateway` prints an `Observed`
column for that field.

`status.listenerPolicy.phase` reports early-strip attach:
`Applied` / `SkippedCrossNamespace` / `Disabled`.
