from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "vmcp-operator"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def test_helm_lint_and_template_operator_only() -> None:
    _run(["helm", "lint", str(CHART)])
    rendered = _run(
        [
            "helm",
            "template",
            "test",
            str(CHART),
            "--namespace",
            "vmcp-system",
        ]
    ).stdout
    assert "kind: Deployment" in rendered
    assert "app.kubernetes.io/component: operator" in rendered
    # Chart must never template a bare vmcp application Deployment.
    assert "name: vmcp\n" not in rendered
    assert "containerPort: 8080" in rendered


def test_helm_fails_without_watch_namespaces_or_replicas() -> None:
    bad_watch = subprocess.run(
        [
            "helm",
            "template",
            "bad",
            str(CHART),
            "--set",
            "watchNamespaces=null",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad_watch.returncode != 0
    assert "watchNamespaces" in bad_watch.stderr

    bad_replicas = subprocess.run(
        [
            "helm",
            "template",
            "bad",
            str(CHART),
            "--set",
            "replicaCount=2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad_replicas.returncode != 0
    assert "replicaCount" in bad_replicas.stderr


def test_crd_files_present_for_server_side_apply_upgrade() -> None:
    crds = sorted(p.name for p in (CHART / "crds").glob("*.yaml"))
    assert crds == ["vmcpgateway.yaml", "vmcpmcpserver.yaml"]
    gateway = (CHART / "crds" / "vmcpgateway.yaml").read_text(encoding="utf-8")
    mcp = (CHART / "crds" / "vmcpmcpserver.yaml").read_text(encoding="utf-8")
    assert "kind: CustomResourceDefinition" in gateway
    assert "kind: CustomResourceDefinition" in mcp
    assert "VmcpGateway" in gateway
    assert "VmcpMcpServer" in mcp
    # Upgrade path documented: kubectl apply --server-side before helm --skip-crds
    assert "vmcpgateways.vmcp.io" in gateway
    assert "vmcpmcpservers.vmcp.io" in mcp
