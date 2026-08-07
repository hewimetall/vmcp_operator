# vmcp-operator

Kubernetes operator for managing multiple isolated
[vmcp](https://github.com/hewimetall/vmcp) gateway instances.

One singleton operator watches an explicit namespace allowlist and reconciles
independent `{namespace}/{VmcpGateway}` stacks (Deployment, Service, PVC,
atomic artifact ConfigMap, credentials, public/admin HTTPRoutes) plus attached
`VmcpMcpServer` upstreams (`ContainerImage` or `RemoteHttp`).

## Stack

- Python 3.15 free-threaded controller (`PYTHON_LAZY_IMPORTS=normal`)
- Pure Rust `vmcp-op-core` + thin PyO3 `vmcp-op-pyo3` (`abi3t-py315`)
- Helm chart installs CRDs/RBAC/operator/dashboard only (never vmcp workloads)
- Vendored Grid.js 6.2.0 + Tabler 1.4.0 dashboard assets
- TDD gates: Python ≥98%, Rust core ≥93%

## Layout

```text
charts/vmcp-operator/   Helm install surface
python/vmcp_operator/   HEX controller + dashboard static
crates/                 vmcp-op-core, vmcp-op-pyo3
deploy/samples/         example CRs
deploy/profiles/        resurche / code / other bundles
scripts/                compatibility spike helpers
docs/                   gate notes
```

## Quick checks

```bash
uv sync --extra dev
uv run maturin develop
make test-py test-rs helm-lint
```

Phase −1 compatibility results: [docs/phase-minus-one.md](docs/phase-minus-one.md).

Gateway contract (vmcp **≥1.2** AuthFacade / hop trust / `forward_identity`):
[docs/compatibility.md](docs/compatibility.md).

Operator control plane **above** vmcp (MCP add/remove/update + NL CRUD,
peer Gateways via `VmcpProxy` / vmcp-proxy):
[docs/control-plane.md](docs/control-plane.md).
