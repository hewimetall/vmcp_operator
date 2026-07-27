from __future__ import annotations

from pathlib import Path

import yaml

from vmcp_operator.adapters.driven.registry.engine import RegistryEngine
from vmcp_operator.domain.models.artifacts import (
    SkillArgDesired,
    SkillDesired,
    ToolOverrideArtifact,
    UpstreamArtifactsDesired,
    UpstreamDesired,
)

ROOT = Path(__file__).resolve().parents[1] / "deploy" / "profiles"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_profile_gateways_exist_for_acceptance_targets() -> None:
    for name in ("resurche", "code", "other"):
        gw = _load_yaml(ROOT / name / "gateway.yaml")
        assert gw["kind"] == "VmcpGateway"
        assert gw["metadata"]["name"] == name
        assert gw["spec"]["adminTokenSecretRef"]["name"]
        assert gw["spec"]["publicRoute"]["hostname"]


def test_blocked_entries_are_disabled_with_reason() -> None:
    blocked = [
        ROOT / "resurche" / "mcp-yandex-proxy.yaml",
        ROOT / "resurche" / "mcp-sourcegraph-proxy.yaml",
        ROOT / "code" / "mcp-gittree.yaml",
        ROOT / "other" / "mcp-presentation.yaml",
        ROOT / "other" / "mcp-notion.yaml",
    ]
    for path in blocked:
        doc = _load_yaml(path)
        assert doc["spec"]["enabled"] is False
        assert "vmcp.io/blocker" in doc["metadata"]["annotations"]


def test_ready_remote_and_architect_render_via_kernel() -> None:
    engine = RegistryEngine()
    skill = SkillDesired(
        name="research_docs",
        description="Research a library/topic using Context7 + Tavily read-only tools.",
        template="Library: {{library}}",
        arguments=(
            SkillArgDesired(name="library", required=True),
            SkillArgDesired(name="question", required=True),
        ),
    )
    bundle = engine.render_bundle(
        [
            UpstreamArtifactsDesired(
                upstream=UpstreamDesired(
                    name="context7",
                    url="https://mcp.context7.com/mcp",
                    bearer_env="CONTEXT7_TOKEN",
                ),
                tool_overrides=(
                    ToolOverrideArtifact(
                        name="resolve-library-id",
                        read_only=True,
                        task_support="forbidden",
                    ),
                ),
            ),
            UpstreamArtifactsDesired(
                upstream=UpstreamDesired(
                    name="architect-c4",
                    url="http://code-architect-c4.team-a.svc:8766/mcp",
                ),
                tool_overrides=(
                    ToolOverrideArtifact(
                        name="get_model",
                        read_only=True,
                        task_support="forbidden",
                    ),
                ),
            ),
        ],
        [skill],
    )
    assert "context7" in bundle.files["registry.json"].data
    assert "architect-c4" in bundle.files["registry.json"].data
    assert "skills/research_docs.yaml" in bundle.files
