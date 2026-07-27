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

## Profiles

Apply after operator install + secrets:

```bash
kubectl apply -f deploy/profiles/resurche/
kubectl apply -f deploy/profiles/code/
kubectl apply -f deploy/profiles/other/
```

Disabled entries carry `vmcp.io/blocker` annotations explaining missing image/runtime contracts.
