# Issue #4 — adoption gaps

Tracker: https://github.com/hewimetall/vmcp_operator/issues/4

| Item | Status |
| --- | --- |
| Runnable operator image + GHCR release workflow | PR #5 (`.github/workflows/release.yml`, `Dockerfile` `ENTRYPOINT`) |
| Gap 1 — public HTTPRoute strips client Authentik / hop headers | This change |
| Gap 2 — admin HTTPRoute sets hop header from `forwardAuthSecretRef` | This change |
| Gap 3 — `enableServiceLinks: false` on Gateway pods | This change |
| `publicBaseUrl` override | This change |
| Writable admin tokens path / BYO HTTPRoute / TrafficPolicy | Still open (smaller notes) |

## Edge filters

**Public** (`stripClientIdentityHeaders`, default `true`):

Removes at least `X-authentik-{username,groups,uid,name,email,entitlements}` and
`X-Vmcp-Forward-Auth` (plus configured username/groups/hop header names).

**Admin** (`injectForwardAuthHeader`, default on when `forwardAuthSecretRef` is set):

Operator reads the Secret at reconcile and sets the hop header on the admin
HTTPRoute so browser `/admin` after Authentik forward-auth satisfies hop trust.

Note: Gateway API `RequestHeaderModifier.set` takes a literal value, so the hop
secret appears in the HTTPRoute object. Restrict `get/list` on HTTPRoutes
accordingly.
