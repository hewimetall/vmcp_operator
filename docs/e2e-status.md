# E2E status

## Accepted in this environment

| Gate | Evidence |
| --- | --- |
| Python 3.15t free-threading + Kopf/PyO3 | `docs/phase-minus-one.md`, 30m KWOK soak |
| Multi-gateway reconcile / isolation / dashboard tokens | `scripts/phase5_kwok_e2e.py`, `tests/test_phase5_e2e.py` |
| VmcpProxy peer → registry upstream `/mcp-proxy` URL | `scripts/phase5_kwok_e2e.py` (`vmcpProxyInRegistry`), profile `other/mcp-code-via-proxy.yaml` |
| Helm lint/template/package + values schema | `make helm-package`, `tests/test_helm_chart.py` |
| OCI chart push/pull | `make helm-push-local` → `oci://127.0.0.1:5001/charts/vmcp-operator:0.1.0` |
| Coverage | Python ≥98%, Rust `vmcp-op-core` ≥93% |

## Blocked here (host limitation)

**kind / k3s kubelet pod e2e** cannot boot: nested cgroup v2 prevents
`kindest/node` from reaching `multi-user.target`. fuse-overlayfs was installed;
failure remains systemd/cgroup nesting, not missing tooling.

When a capable host is available:

```bash
kind create cluster --name vmcp --image kindest/node:v1.36.1
kubectl apply --server-side -f charts/vmcp-operator/crds/
helm upgrade -i vmcp-operator ./charts/vmcp-operator -n vmcp-system --create-namespace \
  --set 'watchNamespaces={team-a}' \
  --set 'policy.allowedImagePrefixes={registry.example.com/ai}'
# then apply deploy/profiles/* and run live pod assertions
```

Production OCI publish is the same as `make helm-push-local` with org registry
host/credentials instead of `127.0.0.1:5001`.
