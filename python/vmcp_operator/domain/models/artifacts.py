"""Desired artifact inputs and rendered bundle value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpstreamDesired:
    name: str
    url: str
    bearer_env: str | None = None
    description: str | None = None
    sidecar_relpath: str | None = None
    enabled: bool = True
    forward_identity: bool = False


@dataclass(frozen=True, slots=True)
class ToolOverrideArtifact:
    name: str
    read_only: bool
    task_support: str | None = None


@dataclass(frozen=True, slots=True)
class SkillArgDesired:
    name: str
    description: str | None = None
    required: bool = False
    default: str | None = None


@dataclass(frozen=True, slots=True)
class SkillDesired:
    name: str
    description: str
    template: str
    arguments: tuple[SkillArgDesired, ...] = ()


@dataclass(frozen=True, slots=True)
class UpstreamArtifactsDesired:
    upstream: UpstreamDesired
    tool_overrides: tuple[ToolOverrideArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactFile:
    path: str
    data: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactBundle:
    files: dict[str, ArtifactFile]
    registry_sha256: str
    bundle_sha256: str
    total_bytes: int
