# Testing

## Local gates

```bash
uv sync --extra dev
uv run maturin develop
make test-py test-rs cov-rs helm-lint
```

Coverage floors:

- Python `vmcp_operator`: ≥98% (`pytest --cov`)
- Rust `vmcp-op-core`: ≥93% lines (`cargo llvm-cov -p vmcp-op-core --fail-under-lines 93`)

## Compatibility spike

```bash
kwokctl create cluster --name vmcp-spike --wait 60s
kwokctl get kubeconfig --name vmcp-spike > /tmp/kwok.kubeconfig
export KUBECONFIG=/tmp/kwok.kubeconfig
kubectl apply -f charts/vmcp-operator/crds/
PYTHON_LAZY_IMPORTS=normal PYTHONUNBUFFERED=1 \
  VMCP_SPIKE_SOAK_SECONDS=120 \
  .venv/bin/python -u scripts/phase_minus_one_kopf_spike.py
```

Kind/k3s full kubelet e2e needs a host with working overlayfs + cgroup v2 nesting.
In constrained VMs use KWOK for API-level concurrency proof.

## Driven adapters covered by unit tests

- `VmcpApiClient` / `VmcpTokenIssuer` (httpx; reload sha match + mcp:use issuance)
- `RenderMcpManifests` (ContainerImage Deploy/Service + independent webExposure routes)
- `PlanSkillsSync` / finalizer helpers (admin-owned skills preserved; unregister-before-GC)
- `Kr8sServerSideApplier` + `ServerSideApply` conflict retry

## Helm package / OCI push

```bash
make helm-package
# → dist/charts/vmcp-operator-0.1.0.tgz

# Prove OCI push/pull against a local registry (no org credentials):
make helm-push-local
# → oci://127.0.0.1:5001/charts/vmcp-operator:0.1.0

# Production push when registry credentials are available:
# helm push dist/charts/vmcp-operator-0.1.0.tgz oci://$REGISTRY/charts
```

## KWOK / API e2e (no kubelet)

```bash
kwokctl get kubeconfig --name vmcp-spike > /tmp/kwok.kubeconfig
export KUBECONFIG=/tmp/kwok.kubeconfig
.venv/bin/python scripts/kwok_e2e_apply.py
# Applies resurche Gateway artifacts (ConfigMap/Service/Deployment/PVC).

# Phase 5 acceptance (multi-gateway isolation, reconnect, delete, dashboard):
.venv/bin/python scripts/phase5_kwok_e2e.py
# Also covered in-memory by tests/test_phase5_e2e.py in CI.
```

Kind/k3s full kubelet e2e remains environment-dependent (nested cgroup v2 must
reach multi-user.target). This VM cannot boot `kindest/node` successfully.

## Profiles

Apply after operator install + secrets:

```bash
kubectl apply -f deploy/profiles/resurche/
kubectl apply -f deploy/profiles/code/
kubectl apply -f deploy/profiles/other/
```

Disabled entries carry `vmcp.io/blocker` annotations explaining missing image/runtime contracts.
