"""Immutable domain models."""

from vmcp_operator.domain.models.artifacts import ArtifactBundle, SkillDesired, UpstreamDesired
from vmcp_operator.domain.models.gateway import GatewayDesired, GatewayKey
from vmcp_operator.domain.models.mcp import McpServerDesired, SourceType

__all__ = [
    "ArtifactBundle",
    "GatewayDesired",
    "GatewayKey",
    "McpServerDesired",
    "SkillDesired",
    "SourceType",
    "UpstreamDesired",
]
