#!/usr/bin/env python3
"""KWOK API-level e2e: map profile CRs → render → SSA apply ConfigMaps/Services."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import yaml

from vmcp_operator.adapters.driven.k8s.kr8s_applier import Kr8sServerSideApplier
from vmcp_operator.adapters.driven.k8s.ssa import ServerSideApply
from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.adapters.driving.k8s.mapping import map_gateway, map_mcp
from vmcp_operator.adapters.driving.k8s.reconcile import GatewayReconcile, McpReconcile
from vmcp_operator.domain.models.artifacts import SkillDesired
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests
from vmcp_operator.domain.usecases.render_mcp_manifests import RenderMcpManifests

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "deploy" / "profiles" / "resurche"


class ProfileSkills:
    async def load_skills(self, gateway, mcps):
        del gateway, mcps
        skill_path = PROFILE / "skills" / "research-docs.yaml"
        raw = yaml.safe_load(skill_path.read_text(encoding="utf-8"))
        return [
            SkillDesired(
                name=raw["name"],
                description=raw["description"],
                template=raw["template"],
                arguments=(),
            )
        ]


async def main() -> int:
    if not os.environ.get("KUBECONFIG"):
        print("KUBECONFIG is required", file=sys.stderr)
        return 2

    gw_doc = yaml.safe_load((PROFILE / "gateway.yaml").read_text(encoding="utf-8"))
    mcp_docs = [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(PROFILE.glob("mcp-*.yaml"))
        if path.name.startswith("mcp-")
    ]
    # Only enabled ready remotes for this API e2e.
    mcp_docs = [doc for doc in mcp_docs if doc.get("spec", {}).get("enabled", True)]

    gateway = map_gateway(
        gw_doc["metadata"]["namespace"],
        gw_doc["metadata"]["name"],
        gw_doc["spec"],
    )
    mcps = [
        map_mcp(doc["metadata"]["namespace"], doc["metadata"]["name"], doc["spec"])
        for doc in mcp_docs
    ]

    apply = ServerSideApply(
        applier=Kr8sServerSideApplier(),
        field_manager="vmcp-operator-e2e",
    )
    gateway_reconcile = GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(),
            skill_loader=ProfileSkills(),
        ),
        manifests=RenderGatewayManifests(),
        apply=apply,
    )
    mcp_reconcile = McpReconcile(manifests=RenderMcpManifests(), apply=apply)

    # Ensure namespace exists via SSA/create path.
    await apply.apply(
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": gateway.key.namespace},
        }
    )

    # Apply core/workload objects; Gateway API HTTPRoutes need CRDs not present
    # in bare KWOK, so filter them out for this API-level smoke.
    async def apply_without_httproute(body: dict) -> dict:
        if body.get("kind") == "HTTPRoute":
            return {"skipped": True, "kind": "HTTPRoute", "name": body["metadata"]["name"]}
        return await apply.apply(body)

    class _FilterApply:
        async def apply(self, body: dict) -> dict:
            return await apply_without_httproute(body)

    gateway_reconcile = GatewayReconcile(
        artifacts=gateway_reconcile.artifacts,
        manifests=gateway_reconcile.manifests,
        apply=_FilterApply(),  # type: ignore[arg-type]
    )
    mcp_reconcile = McpReconcile(
        manifests=mcp_reconcile.manifests,
        apply=_FilterApply(),  # type: ignore[arg-type]
    )

    gw_result = await gateway_reconcile.execute(gateway, mcps)
    mcp_results = []
    for mcp in mcps:
        mcp_results.append(await mcp_reconcile.execute(gateway, mcp))

    out = {
        "gateway": gw_result,
        "mcps": mcp_results,
        "enabledMcps": [mcp.name for mcp in mcps],
    }
    result_path = Path(
        os.environ.get("VMCP_E2E_RESULT", "/tmp/kwok-e2e-result.json")
    )
    result_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if gw_result.get("phase") == "Applied" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
