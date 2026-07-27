from __future__ import annotations

from pathlib import Path

import yaml

from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.adapters.driving.k8s.mapping import map_gateway, map_mcp
from vmcp_operator.domain.models.artifacts import (
    SkillArgDesired,
    SkillDesired,
    ToolOverrideArtifact,
    UpstreamArtifactsDesired,
    UpstreamDesired,
)
from vmcp_operator.domain.models.mcp import ContainerImageSource
from vmcp_operator.domain.usecases.render_mcp_manifests import RenderMcpManifests

ROOT = Path(__file__).resolve().parents[1] / "deploy" / "profiles"


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_all_profiles_have_gateway_and_blocker_annotations() -> None:
    for profile in ("resurche", "code", "other"):
        gw = _yaml(ROOT / profile / "gateway.yaml")
        assert gw["metadata"]["name"] == profile
        assert gw["spec"]["adminTokenSecretRef"]["name"]
        blocked = list((ROOT / profile).glob("mcp-*.yaml"))
        assert blocked
        for path in blocked:
            doc = _yaml(path)
            if doc["spec"].get("enabled", True) is False:
                assert "vmcp.io/blocker" in doc["metadata"].get("annotations", {})


def test_resurche_ready_remotes_render_without_raw_secrets() -> None:
    engine = RegistryEngine()
    upstreams = []
    for name, url, env in (
        ("context7", "https://mcp.context7.com/mcp", "CONTEXT7_TOKEN"),
        ("tavily", "https://mcp.tavily.com/mcp", "TAVILY_TOKEN"),
        ("serpapi", "https://mcp.serpapi.com/mcp", "SERPAPI_TOKEN"),
    ):
        upstreams.append(
            UpstreamArtifactsDesired(
                upstream=UpstreamDesired(name=name, url=url, bearer_env=env),
                tool_overrides=(
                    ToolOverrideArtifact(name="search", read_only=True, task_support="forbidden"),
                ),
            )
        )
    skill = SkillDesired(
        name="research_docs",
        description="research",
        template="q={{question}}",
        arguments=(
            SkillArgDesired(name="library", required=True),
            SkillArgDesired(name="question", required=True),
        ),
    )
    bundle = engine.render_bundle(upstreams, [skill])
    text = bundle.files["registry.json"].data
    assert "context7" in text and "tavily" in text and "serpapi" in text
    assert "${CONTEXT7_TOKEN}" in text
    # No raw bearer material in rendered registry.
    assert "sk-" not in text
    assert "Bearer " not in text


def test_code_architect_contract_and_viewer_exposure() -> None:
    doc = _yaml(ROOT / "code" / "mcp-architect-c4.yaml")
    mcp = map_mcp(doc["metadata"]["namespace"], doc["metadata"]["name"], doc["spec"])
    assert isinstance(mcp.source, ContainerImageSource)
    assert mcp.source.mcp_endpoint.port_name == "http"
    assert mcp.source.mcp_endpoint.path == "/mcp"
    assert any(ov.name == "get_model" and ov.read_only for ov in mcp.tool_overrides)
    gw_doc = _yaml(ROOT / "code" / "gateway.yaml")
    gateway = map_gateway(
        gw_doc["metadata"]["namespace"],
        gw_doc["metadata"]["name"],
        gw_doc["spec"],
    )
    manifests = RenderMcpManifests().execute(gateway, mcp)
    route = next(m for m in manifests if m["kind"] == "HTTPRoute")
    assert route["spec"]["hostnames"] == ["architect.example.com"]
    paths = {
        match["path"]["value"]
        for match in route["spec"]["rules"][0]["matches"]
    }
    assert "/" in paths and "/adrs" in paths and "/view" in paths
    assert route["metadata"]["annotations"]["vmcp.io/status-independent-of-mcp"] == "true"
    env = {
        item["name"]: item["value"]
        for item in manifests[0]["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert env["ARCHITECT_C4_PUBLIC_BASE"] == "https://architect.example.com"


def test_blocked_entries_have_exact_reasons() -> None:
    expectations = {
        ROOT / "code" / "mcp-gittree.yaml": "SourceContractMissing",
        ROOT / "other" / "mcp-presentation.yaml": "RuntimeUnavailable",
        ROOT / "other" / "mcp-notion.yaml": "SourceContractMissing",
        ROOT / "resurche" / "mcp-yandex-proxy.yaml": "Requires org-registry HTTP proxy",
    }
    for path, needle in expectations.items():
        doc = _yaml(path)
        assert doc["spec"]["enabled"] is False
        assert needle in doc["metadata"]["annotations"]["vmcp.io/blocker"]


def test_architect_skill_fixture_forbids_defaults() -> None:
    skill = _yaml(ROOT / "code" / "skills" / "architect-overview.yaml")
    assert skill["name"] == "architect_overview"
    assert "__" not in skill["name"]
    for arg in skill.get("arguments") or []:
        assert not (arg.get("required") and arg.get("default"))
        assert "default" not in arg
