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
# First install applies CRDs from charts/vmcp-operator/crds/
helm upgrade -i vmcp-operator ./charts/vmcp-operator \
  --namespace vmcp-system --create-namespace \
  --set image.repository=registry.example.com/vmcp-operator \
  --set image.tag=0.1.0 \
  --set 'watchNamespaces={team-a,team-b,shared}' \
  --set 'policy.allowedImagePrefixes={registry.example.com/ai}'

# CRD upgrades: server-side apply before helm upgrade --skip-crds
kubectl apply --server-side --force-conflicts \
  -f charts/vmcp-operator/crds/
helm upgrade vmcp-operator ./charts/vmcp-operator \
  --namespace vmcp-system --skip-crds
```

## After install

1. Create `tokens.json` Secrets for each Gateway (`adminTokenSecretRef`).
2. Apply profile bundles under `deploy/profiles/` or sample CRs under `deploy/samples/`.
3. Port-forward the dashboard Service when enabled.
