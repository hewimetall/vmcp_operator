#!/usr/bin/env python3
"""Sandbox verify for issue #4 Gaps 1-3 against deploy/samples/gateway-authentik.yaml.

Requires KUBECONFIG (KWOK/kind). Expects Secrets already present (or creates them
via kubectl in the wrapper shell). Reconciles the sample Gateway and asserts
public strip / admin hop set / enableServiceLinks=false.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "deploy" / "samples" / "gateway-authentik.yaml"


async def main() -> int:
    if not os.environ.get("KUBECONFIG"):
        print("KUBECONFIG is required", file=sys.stderr)
        return 2

    from vmcp_operator.adapters.driven.k8s.kr8s_applier import Kr8sServerSideApplier
    from vmcp_operator.adapters.driven.k8s.secret_loader import Kr8sSecretValueLoader
    from vmcp_operator.adapters.driven.k8s.ssa import ServerSideApply
    from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
    from vmcp_operator.adapters.driving.k8s.mapping import map_gateway
    from vmcp_operator.adapters.driving.k8s.reconcile import GatewayReconcile
    from vmcp_operator.adapters.driving.k8s.runtime import EmptySkillLoader
    from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
    from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests

    doc = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    ns = doc["metadata"]["namespace"]
    name = doc["metadata"]["name"]
    gateway = map_gateway(ns, name, doc["spec"])
    hop_value = os.environ.get("VMCP_ISSUE4_HOP_SECRET", "sandbox-hop-secret-value")

    class _CaptureApply:
        def __init__(self, inner: ServerSideApply) -> None:
            self.inner = inner
            self.applied: list[dict] = []

        async def apply(self, body: dict) -> dict:
            result = await self.inner.apply(body)
            self.applied.append(body)
            return result

    apply = _CaptureApply(
        ServerSideApply(
            applier=Kr8sServerSideApplier(),
            field_manager="vmcp-issue4-sandbox",
        )
    )
    result = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(),
            skill_loader=EmptySkillLoader(),
        ),
        manifests=RenderGatewayManifests(),
        apply=apply,  # type: ignore[arg-type]
        secrets=Kr8sSecretValueLoader(),
    ).execute(gateway, [])

    public = next(
        b
        for b in apply.applied
        if b.get("kind") == "HTTPRoute" and b["metadata"]["name"].endswith("-public")
    )
    admin = next(
        b
        for b in apply.applied
        if b.get("kind") == "HTTPRoute" and b["metadata"]["name"].endswith("-admin")
    )
    deploy_body = next(b for b in apply.applied if b.get("kind") == "Deployment")

    public_remove = {
        h.lower()
        for h in public["spec"]["rules"][0]["filters"][0]["requestHeaderModifier"]["remove"]
    }
    required = {
        "x-authentik-username",
        "x-authentik-groups",
        "x-authentik-uid",
        "x-authentik-name",
        "x-authentik-email",
        "x-authentik-entitlements",
        "x-vmcp-forward-auth",
    }
    assert required <= public_remove, sorted(public_remove)

    hop_set = admin["spec"]["rules"][0]["filters"][0]["requestHeaderModifier"]["set"]
    assert hop_set[0]["name"].lower() == "x-vmcp-forward-auth"
    assert hop_set[0]["value"] == hop_value, hop_set

    assert deploy_body["spec"]["template"]["spec"]["enableServiceLinks"] is False

    # Live read-back via kubectl-shaped objects (kr8s api.get is a generator).
    from kr8s.asyncio.objects import Deployment, new_class

    deploy_live = await Deployment.get(name, namespace=ns)
    live_links = deploy_live.raw["spec"]["template"]["spec"].get("enableServiceLinks")
    assert live_links is False, live_links

    http_route_cls = new_class(
        kind="HTTPRoute",
        version="gateway.networking.k8s.io/v1",
        plural="httproutes",
        namespaced=True,
        asyncio=True,
    )
    pub_live = await http_route_cls.get(f"{name}-public", namespace=ns)
    adm_live = await http_route_cls.get(f"{name}-admin", namespace=ns)
    pub_rm = {
        h.lower()
        for h in pub_live.raw["spec"]["rules"][0]["filters"][0]["requestHeaderModifier"][
            "remove"
        ]
    }
    assert required <= pub_rm, sorted(pub_rm)
    assert (
        adm_live.raw["spec"]["rules"][0]["filters"][0]["requestHeaderModifier"]["set"][0][
            "value"
        ]
        == hop_value
    )

    out = {
        "cluster": "kwok" if "kwok" in os.environ.get("KUBECONFIG", "") else "kube",
        "gateway": gateway.key.as_str(),
        "sample": str(SAMPLE.relative_to(ROOT)),
        "reconcile": result,
        "publicStripHeaders": sorted(required),
        "adminHopHeaderValueMatchesSecret": True,
        "enableServiceLinks": False,
        "deploymentLiveEnableServiceLinks": live_links,
        "httpRouteLiveVerified": True,
        "adminHopHeaderInjected": result.get("adminHopHeaderInjected"),
    }
    path = Path(os.environ.get("VMCP_ISSUE4_RESULT", "/tmp/issue4-sandbox-result.json"))
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
