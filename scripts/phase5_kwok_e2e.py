#!/usr/bin/env python3
"""Phase 5 API-level e2e on KWOK (no kubelet required).

Covers multi-gateway isolation, architect web exposure independence,
checksum reconnect planning, MCP delete/unregister registry filtering,
dashboard environment listing + mcp:use issuance, and VmcpProxy peering
(consumer registry upstream URL → peer /mcp-proxy ClusterIP).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import yaml

from vmcp_operator.adapters.driven.k8s.kr8s_applier import Kr8sServerSideApplier
from vmcp_operator.adapters.driven.k8s.ssa import InMemoryApplier, ServerSideApply
from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.adapters.driving.dashboard.app import DashboardAuth, create_app
from vmcp_operator.adapters.driving.k8s.mapping import map_gateway, map_mcp
from vmcp_operator.adapters.driving.k8s.reconcile import GatewayReconcile, McpReconcile
from vmcp_operator.domain.models.artifacts import SkillDesired
from vmcp_operator.domain.models.gateway import GatewayKey
from vmcp_operator.domain.usecases.connection_strategy import McpConnectionStrategy
from vmcp_operator.domain.usecases.issue_use_token import IssueUseToken
from vmcp_operator.domain.usecases.list_environments import ListEnvironments
from vmcp_operator.domain.usecases.reconcile_artifacts import ReconcileGatewayArtifacts
from vmcp_operator.domain.usecases.render_gateway_manifests import RenderGatewayManifests
from vmcp_operator.domain.usecases.render_mcp_manifests import RenderMcpManifests
from vmcp_operator.domain.usecases.skills_sync import PlanSkillsSync, SkillFile

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "deploy" / "profiles"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _enabled_mcps(profile: str) -> list[dict]:
    docs = []
    for path in sorted((PROFILES / profile).glob("mcp-*.yaml")):
        doc = _load(path)
        if doc.get("spec", {}).get("enabled", True):
            docs.append(doc)
    return docs


class ProfileSkills:
    def __init__(self, profile: str) -> None:
        self.profile = profile

    async def load_skills(self, gateway, mcps):
        del gateway, mcps
        skills_dir = PROFILES / self.profile / "skills"
        out: list[SkillDesired] = []
        if not skills_dir.exists():
            return out
        for path in sorted(skills_dir.glob("*.yaml")):
            raw = _load(path)
            out.append(
                SkillDesired(
                    name=raw["name"],
                    description=raw["description"],
                    template=raw["template"],
                    arguments=(),
                )
            )
        return out


class _FilterApply:
    def __init__(self, inner: ServerSideApply) -> None:
        self.inner = inner

    async def apply(self, body: dict) -> dict:
        if body.get("kind") == "HTTPRoute":
            return {"skipped": True, "kind": "HTTPRoute", "name": body["metadata"]["name"]}
        return await self.inner.apply(body)


async def _apply_profile(profile: str, apply: _FilterApply) -> dict:
    gw_doc = _load(PROFILES / profile / "gateway.yaml")
    gateway = map_gateway(
        gw_doc["metadata"]["namespace"],
        gw_doc["metadata"]["name"],
        gw_doc["spec"],
    )
    mcps = [
        map_mcp(doc["metadata"]["namespace"], doc["metadata"]["name"], doc["spec"])
        for doc in _enabled_mcps(profile)
    ]
    gateway_reconcile = GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(),
            skill_loader=ProfileSkills(profile),
        ),
        manifests=RenderGatewayManifests(),
        apply=apply,  # type: ignore[arg-type]
    )
    mcp_reconcile = McpReconcile(
        manifests=RenderMcpManifests(),
        apply=apply,  # type: ignore[arg-type]
    )
    await apply.apply(
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": gateway.key.namespace},
        }
    )
    gw_result = await gateway_reconcile.execute(gateway, mcps)
    mcp_results = [await mcp_reconcile.execute(gateway, mcp) for mcp in mcps]
    return {
        "gateway": gateway,
        "mcps": mcps,
        "gw_result": gw_result,
        "mcp_results": mcp_results,
    }


async def _dashboard_check(gateways) -> dict:
    class Store:
        def __init__(self, items):
            self._items = {g.key.as_str(): g for g in items}

        async def get(self, key: GatewayKey):
            return self._items.get(key.as_str())

        async def list_all(self):
            return list(self._items.values())

    class Issuer:
        def __init__(self):
            self.seen: set[str] = set()
            self.tokens: list[str] = []

        async def issue_use_token(self, key: GatewayKey, client_name: str) -> str:
            marker = f"{key.as_str()}:{client_name}"
            if marker in self.seen:
                raise FileExistsError("duplicate")
            self.seen.add(marker)
            token = f"tok-{client_name}"
            self.tokens.append(token)
            return token

    store = Store(gateways)
    issuer = Issuer()
    from vmcp_operator.adapters.driven.k8s.mcp_catalog import InMemoryMcpCatalog
    from vmcp_operator.adapters.driving.dashboard.control_plane import build_control_plane

    control = build_control_plane(gateways=store, catalog=InMemoryMcpCatalog())
    app = create_app(
        auth=DashboardAuth(username="admin", password="secret"),
        list_environments=ListEnvironments(
            gateways=store,
            phases={g.key.as_str(): "Ready" for g in gateways},
        ),
        issue_use_token=IssueUseToken(gateways=store, issuer=issuer),
        list_mcps=control.list_mcps,
        get_mcp=control.get_mcp,
        add_mcp=control.add_mcp,
        update_mcp=control.update_mcp,
        remove_mcp=control.remove_mcp,
        nl_crud=control.nl_crud,
    )
    from aiohttp.test_utils import TestClient, TestServer

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        import base64

        headers = {
            "Authorization": "Basic "
            + base64.b64encode(b"admin:secret").decode("ascii")
        }
        resp = await client.get("/api/environments", headers=headers)
        envs = await resp.json()
        assert resp.status == 200
        keys = sorted(row["key"] for row in envs)
        assert keys == ["team-a/code", "team-a/other", "team-a/resurche"]
        assert all(row.get("adminUrl") for row in envs)
        resp = await client.post(
            "/api/tokens",
            headers=headers,
            json={"gateway": "team-a/code", "clientName": "cursor"},
        )
        payload = await resp.json()
        assert resp.status == 200
        assert payload["scope"] == "mcp:use"
        assert payload["token"] == "tok-cursor"
        # Token shown once to client; operator issuer keeps no secret store beyond set membership.
        assert issuer.tokens == ["tok-cursor"]
        resp = await client.post(
            "/api/tokens",
            headers=headers,
            json={"gateway": "team-a/code", "clientName": "cursor"},
        )
        assert resp.status == 409
        return {"environments": keys, "tokenScope": payload["scope"], "duplicate": 409}
    finally:
        await client.close()


async def main() -> int:
    use_cluster = bool(os.environ.get("KUBECONFIG"))
    if use_cluster:
        apply = _FilterApply(
            ServerSideApply(
                applier=Kr8sServerSideApplier(),
                field_manager="vmcp-phase5-e2e",
            )
        )
    else:
        apply = _FilterApply(ServerSideApply(applier=InMemoryApplier()))

    resurche = await _apply_profile("resurche", apply)
    code = await _apply_profile("code", apply)
    other = await _apply_profile("other", apply)

    # VmcpProxy: other mounts code's [proxy] surface; registry must point at ClusterIP /mcp-proxy.
    peer_url = "http://code.team-a.svc:8080/mcp-proxy"
    other_proxy = next(m for m in other["mcps"] if m.name == "code-via-proxy")
    assert type(other_proxy.source).__name__ == "VmcpProxySource"
    assert other_proxy.source.cluster_url() == peer_url
    other_bundle = await ReconcileGatewayArtifacts(
        renderer=RegistryEngine(),
        skill_loader=ProfileSkills("other"),
    ).execute(other["gateway"], other["mcps"])
    other_registry = other_bundle.files["registry.json"].data
    assert peer_url in other_registry, other_registry
    assert "code-via-proxy" in other_registry
    assert "forward_identity" in other_registry
    # Peer Gateway itself must advertise proxy.enabled (profile contract).
    assert code["gateway"].proxy.enabled is True
    assert code["gateway"].proxy.path == "/mcp-proxy"

    # Isolation: admin skill mutation plan for resurche must not delete code skills.
    resurche_plan = PlanSkillsSync().execute(
        desired_managed=(
            SkillFile(name="research_docs", content="new", managed=True),
        ),
        existing_names=("research_docs", "admin_only_resurche"),
        previously_managed_names=("research_docs",),
    )
    code_plan = PlanSkillsSync().execute(
        desired_managed=(
            SkillFile(name="architect_overview", content="new", managed=True),
        ),
        existing_names=("architect_overview", "admin_only_code"),
        previously_managed_names=("architect_overview",),
    )
    assert resurche_plan.keep == ("admin_only_resurche",)
    assert code_plan.keep == ("admin_only_code",)
    assert "architect_overview" not in resurche_plan.delete
    assert "research_docs" not in code_plan.delete

    # Architect web exposure independent from MCP connect status.
    architect = next(m for m in code["mcps"] if m.name == "architect-c4")
    manifests = RenderMcpManifests().execute(code["gateway"], architect)
    route = next(m for m in manifests if m["kind"] == "HTTPRoute")
    assert route["metadata"]["annotations"]["vmcp.io/status-independent-of-mcp"] == "true"
    assert "vmcp.io/workload-checksum" in manifests[0]["metadata"]["annotations"]

    # Reconnect plan for unchanged Service URL after checksum/image roll.
    plan = McpConnectionStrategy().plan_rollout(
        rolled_names=("architect-c4",),
        service_url_unchanged=True,
    )
    assert plan.reload_after_remove and plan.reload_after_add

    # Delete MCP → registry names exclude removed upstream (artifact-level).
    remaining = [m for m in resurche["mcps"] if m.name != "tavily"]
    gw_after_delete = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(),
            skill_loader=ProfileSkills("resurche"),
        ),
        manifests=RenderGatewayManifests(),
        apply=apply,  # type: ignore[arg-type]
    ).execute(resurche["gateway"], remaining)
    # Bundle changes after removal.
    assert gw_after_delete["bundleSha256"] != resurche["gw_result"]["bundleSha256"]

    # No raw secrets in applied/rendered registry ConfigMap data.
    if use_cluster:
        import kr8s

        api = await kr8s.asyncio.api()
        cms = [
            obj
            async for obj in api.get(
                "configmaps",
                namespace="team-a",
                label_selector="vmcp.io/gateway=resurche",
            )
        ]
        assert cms, "expected resurche artifacts ConfigMap"
        data = cms[0].raw.get("data") or {}
        joined = "\n".join(data.values())
        assert "Bearer " not in joined
        assert "sk-" not in joined

    dashboard = await _dashboard_check(
        [resurche["gateway"], code["gateway"], other["gateway"]]
    )

    # Level reconcile recovery: re-run gateway reconcile after "operator restart".
    recovered = await GatewayReconcile(
        artifacts=ReconcileGatewayArtifacts(
            renderer=RegistryEngine(),
            skill_loader=ProfileSkills("code"),
        ),
        manifests=RenderGatewayManifests(),
        apply=apply,  # type: ignore[arg-type]
    ).execute(code["gateway"], code["mcps"])
    assert recovered["phase"] == "Applied"

    out = {
        "cluster": "kwok" if use_cluster else "memory",
        "gateways": ["team-a/resurche", "team-a/code", "team-a/other"],
        "resurcheObjects": resurche["gw_result"]["objects"],
        "codeObjects": code["gw_result"]["objects"],
        "otherObjects": other["gw_result"]["objects"],
        "architectWebIndependent": True,
        "reconnect": plan.phase,
        "skillsIsolation": True,
        "dashboard": dashboard,
        "levelReconcileRecovered": True,
        "deleteChangedBundle": True,
        "vmcpProxyPeerUrl": peer_url,
        "vmcpProxyInRegistry": True,
    }
    result_path = Path(os.environ.get("VMCP_PHASE5_RESULT", "/tmp/phase5-e2e-result.json"))
    result_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
