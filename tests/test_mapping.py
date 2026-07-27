from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vmcp_operator.adapters.driving.k8s.mapping import map_gateway, map_mcp
from vmcp_operator.domain.models.mcp import ContainerImageSource, RemoteHttpSource

ROOT = Path(__file__).resolve().parents[1] / "deploy" / "profiles"


def test_map_profile_gateway_and_remote_mcp() -> None:
    gw_doc = yaml.safe_load((ROOT / "resurche" / "gateway.yaml").read_text())
    mcp_doc = yaml.safe_load((ROOT / "resurche" / "mcp-context7.yaml").read_text())
    gateway = map_gateway(
        gw_doc["metadata"]["namespace"],
        gw_doc["metadata"]["name"],
        gw_doc["spec"],
    )
    mcp = map_mcp(
        mcp_doc["metadata"]["namespace"],
        mcp_doc["metadata"]["name"],
        mcp_doc["spec"],
    )
    assert gateway.key.as_str() == "team-a/resurche"
    assert gateway.admin_route is not None
    assert isinstance(mcp.source, RemoteHttpSource)
    assert mcp.tool_overrides[0].read_only is True


def test_map_architect_container_and_web_exposure() -> None:
    doc = yaml.safe_load((ROOT / "code" / "mcp-architect-c4.yaml").read_text())
    mcp = map_mcp(doc["metadata"]["namespace"], doc["metadata"]["name"], doc["spec"])
    assert isinstance(mcp.source, ContainerImageSource)
    assert mcp.source.mcp_endpoint.port_name == "http"
    assert mcp.web_exposures[0].public_base_url_env == "ARCHITECT_C4_PUBLIC_BASE"


def test_map_rejects_unknown_source_type() -> None:
    with pytest.raises(ValueError, match=r"unsupported source\.type"):
        map_mcp(
            "team-a",
            "x",
            {
                "gatewayRef": {"name": "main"},
                "source": {"type": "Stdio"},
            },
        )


def test_map_skill_refs() -> None:
    gw_doc = yaml.safe_load((ROOT / "resurche" / "gateway.yaml").read_text())
    gw_doc["spec"]["skillRefs"] = [{"name": "research-docs", "key": "skill.yaml"}]
    gateway = map_gateway("team-a", "resurche", gw_doc["spec"])
    assert gateway.skill_refs[0].name == "research-docs"
    assert gateway.skill_refs[0].key == "skill.yaml"
