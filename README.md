# vmcp-operator

Kubernetes operator for managing multiple isolated
[vmcp](https://github.com/hewimetall/vmcp) gateway instances.

The project is being implemented from the architecture plan with:

- Python 3.15 free-threaded controller code;
- a pure Rust core plus a thin PyO3 `abi3t` extension;
- Helm-distributed CRDs/RBAC/operator control plane;
- TDD gates of at least 98% Python and 93% Rust core line coverage.

The first execution gate verifies that the selected Python/Kubernetes/PyO3
stack runs without silently re-enabling the GIL.
