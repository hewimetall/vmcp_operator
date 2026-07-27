# Phase −1 compatibility gate

## Proven

| Check | Result |
| --- | --- |
| CPython `3.15.0b4` free-threaded (`uv python install 3.15t`) | `sys._is_gil_enabled() is False` |
| Import `kopf`, `kr8s`, `aiohttp`, `httpx` | GIL stays disabled |
| PyO3 `abi3t-py315` extension `vmcp_operator._kernel` | Imports under free-threading |
| Concurrent Kopf watches on `VmcpGateway` + `VmcpMcpServer` | Both handlers fire |
| Kubernetes apply + local HTTP probe during soak | OK |

Artifacts:

- `scripts/phase_minus_one_kopf_spike.py`
- soak result JSON via `VMCP_SPIKE_RESULT` (default `/tmp/phase-minus-one-result.json`)

## Cluster note

This environment cannot boot kind/k3s kubelet because nested cgroup v2 / overlayfs mounts are unavailable (`overlay2` and cgroup domain controllers fail).

The API-level gate therefore runs against **KWOK** (`kwokctl`, Kubernetes `v1.36.1` apiserver), which is sufficient to prove free-threaded Kopf watch/apply concurrency. Full kind pod e2e remains Phase 5 when a host with working container runtime/cgroups is available.

## How to re-run

```bash
kwokctl create cluster --name vmcp-spike --wait 60s
kwokctl get kubeconfig --name vmcp-spike > /tmp/kwok.kubeconfig
export KUBECONFIG=/tmp/kwok.kubeconfig
kubectl apply -f charts/vmcp-operator/crds/
PYTHON_LAZY_IMPORTS=normal VMCP_SPIKE_SOAK_SECONDS=90 \
  .venv/bin/python scripts/phase_minus_one_kopf_spike.py
```
