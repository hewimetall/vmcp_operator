# Issue #8 — 0.0.2 adoption (adminRoute, CRD skew, health)

Tracker: https://github.com/hewimetall/vmcp_operator/issues/8

| Item | Status |
| --- | --- |
| `adminRoute` without `gatewayRef` crashes reconcile (`BoxKeyError`) | Fixed — inherit from `publicRoute`, else `InvalidSpec` |
| Same-host admin (path on the public hostname) | `adminRoute.hostname` optional; `path` default `/admin` |
| Two `RequestHeaderModifier` filters rejected by Gateway API | Merged into one filter (`remove` + `set` + `add`) |
| `stripClientIdentityHeaders` on admin undoes Authentik login | Authentik identity headers not stripped when hop inject is on |
| Image upgrade without matching CRDs silently prunes new fields | Documented below and in the Helm chart README |
| `phase` is not a liveness signal | Use `metadata.generation` vs `status.observedGeneration` |

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

True pre-auth strip (defence in depth before extAuth) is a kgateway
`ListenerPolicy` `earlyRequestHeaderModifier` on the shared Gateway — the
operator does not own that listener.

## Upgrading image vs CRDs

The operator image and the CRDs are separate artifacts. Applying a newer
image with older CRDs does **not** error: the API server **prunes** unknown
`spec` fields (`stripClientIdentityHeaders`, `manage`, `extraFilters`,
`path`, …). The operator looks upgraded and silently ignores the new
configuration.

Always apply `charts/vmcp-operator/crds/` at the **same tag** as the image
(`kubectl apply --server-side` before `helm upgrade --skip-crds`). See
[charts/vmcp-operator/README.md](../charts/vmcp-operator/README.md).

Release images are published only on `v*` tags ([docs/release.md](release.md)).

## Health: `phase` vs `observedGeneration`

`status.phase` is persisted on the CR. Scaling the operator to zero leaves
`phase=Applied` even though nothing is reconciling.

A live operator has caught up when `status.observedGeneration` equals
`metadata.generation`. `kubectl get vmcpgateway` prints an `Observed` column
for that field.
