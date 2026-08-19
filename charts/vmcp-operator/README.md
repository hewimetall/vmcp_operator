# vmcp-operator Helm chart

Installs the singleton operator control plane only:

- CRDs: `VmcpGateway`, `VmcpMcpServer`
- ServiceAccount + Role/RoleBinding per `watchNamespaces` entry
- ClusterRole for leases/CRD discovery
- Operator Deployment (`replicaCount` hard-locked to 1)
- Optional dashboard Service + HTTPRoute

This chart never templates a vmcp Deployment, MCP workload, bootstrap Job,
NetworkPolicy, or ServiceMonitor.

## Required values

| Value | Meaning |
| --- | --- |
| `watchNamespaces` | Explicit namespace allowlist (non-empty) |
| `policy.allowedImagePrefixes` | Non-empty OCI repository prefix allowlist |

## Install

```bash
# Image: ghcr.io/hewimetall/vmcp_operator (published on git tag v* via release.yml)
# First install applies CRDs from charts/vmcp-operator/crds/
helm upgrade -i vmcp-operator ./charts/vmcp-operator \
  --namespace vmcp-system --create-namespace \
  --set image.tag=0.1.0 \
  --set 'watchNamespaces={team-a,team-b,shared}' \
  --set 'policy.allowedImagePrefixes={registry.example.com/ai}'

# CRD upgrades: ALWAYS apply charts/vmcp-operator/crds/ from the same tag as the
# image *before* helm upgrade --skip-crds. Helm does not upgrade CRDs in place.
# Installing a newer image with older CRDs is silent: the API server prunes every
# new spec field (stripClientIdentityHeaders, manage, extraFilters, path, …)
# and the operator looks upgraded while ignoring the configuration.
kubectl apply --server-side --force-conflicts \
  -f charts/vmcp-operator/crds/
helm upgrade vmcp-operator ./charts/vmcp-operator \
  --namespace vmcp-system --skip-crds
```

`status.phase` is not a liveness signal (it stays `Applied` with the operator
scaled to zero). Use `status.observedGeneration == metadata.generation`.

## After install

1. Create Secrets for each Gateway:
   - `adminTokenSecretRef` — `tokens.json` body (key default `token`)
   - `masterPasswordSecretRef` — argon2id hash from `vmcp hash-password`
   - optional `auth.authentik.forwardAuthSecretRef` for hop trust (vmcp ≥1.2)
2. Apply profile bundles under `deploy/profiles/` or sample CRs under `deploy/samples/`
   (use a vmcp **≥1.2** image for AuthFacade / hop trust / `forwardIdentity`).
3. Port-forward the dashboard Service when enabled.

See [docs/compatibility.md](../../docs/compatibility.md) and
[docs/issue-8-adoption.md](../../docs/issue-8-adoption.md).
