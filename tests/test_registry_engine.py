from __future__ import annotations

import sys

import pytest

from vmcp_operator.adapters.driven.registry.engine import (
    RegistryEngine,
    SkillArgDesired,
    SkillDesired,
    ToolOverrideDesired,
    UpstreamArtifactsDesired,
    UpstreamDesired,
)


def test_free_threading_still_enabled() -> None:
    assert sys._is_gil_enabled() is False


def test_render_registry_sorted_http() -> None:
    engine = RegistryEngine()
    out = engine.render_registry(
        [
            UpstreamDesired(
                name="tavily",
                url="https://tavily.example/mcp",
                bearer_env="TAVILY_API_KEY",
            ),
            UpstreamDesired(
                name="context7",
                url="https://context7.example/mcp",
                bearer_env="CONTEXT7_API_KEY",
            ),
        ]
    )
    assert '"name": "context7"' in out.text
    assert '"transport": "http"' in out.text
    assert "${CONTEXT7_API_KEY}" in out.text
    assert out.sha256


def test_render_bundle_includes_sidecar_and_skill() -> None:
    engine = RegistryEngine()
    bundle = engine.render_bundle(
        [
            UpstreamArtifactsDesired(
                upstream=UpstreamDesired(
                    name="architect-c4",
                    url="http://architect-c4:8766/mcp",
                    description="docs",
                ),
                tool_overrides=(
                    ToolOverrideDesired(
                        name="get_model",
                        read_only=True,
                        task_support="forbidden",
                    ),
                ),
            )
        ],
        [
            SkillDesired(
                name="architect_overview",
                description="overview",
                template="topic={{topic}}",
                arguments=(SkillArgDesired(name="topic", required=True),),
            )
        ],
    )
    assert "registry.json" in bundle.files
    assert any(path.startswith("specs/architect-c4-") for path in bundle.files)
    assert "skills/architect_overview.yaml" in bundle.files


def test_image_policy_rejects_outside_prefix() -> None:
    engine = RegistryEngine()
    engine.ensure_image_allowed(
        "harbor.example.com/ai/vmcp:1",
        ["harbor.example.com/ai"],
    )
    with pytest.raises(ValueError, match="outside allowed prefixes"):
        engine.ensure_image_allowed(
            "harbor.example.com/ai-evil/vmcp:1",
            ["harbor.example.com/ai"],
        )
