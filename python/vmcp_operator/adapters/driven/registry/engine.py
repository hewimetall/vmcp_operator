"""Driven adapter that calls the Rust artifact kernel via idiomatic PyO3."""

from __future__ import annotations

from dataclasses import dataclass

import vmcp_operator._kernel as _kernel


@dataclass(frozen=True, slots=True)
class UpstreamDesired:
    name: str
    url: str
    bearer_env: str | None = None
    description: str | None = None
    sidecar_relpath: str | None = None
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ToolOverrideDesired:
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
    tool_overrides: tuple[ToolOverrideDesired, ...] = ()


@dataclass(frozen=True, slots=True)
class RenderedRegistry:
    text: str
    sha256: str


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


class RegistryEngine:
    """Thin façade over ``vmcp_operator._kernel`` (no business logic here)."""

    def render_registry(self, upstreams: list[UpstreamDesired]) -> RenderedRegistry:
        out = _kernel.render_registry(upstreams)
        return RenderedRegistry(text=out.text, sha256=out.sha256)

    def render_bundle(
        self,
        upstreams: list[UpstreamArtifactsDesired],
        skills: list[SkillDesired],
    ) -> ArtifactBundle:
        out = _kernel.render_artifact_bundle(upstreams, skills)
        files = {
            path: ArtifactFile(path=item.path, data=item.data, sha256=item.sha256)
            for path, item in out.files.items()
        }
        return ArtifactBundle(
            files=files,
            registry_sha256=out.registry_sha256,
            bundle_sha256=out.bundle_sha256,
            total_bytes=out.total_bytes,
        )

    def ensure_image_allowed(self, image: str, prefixes: list[str]) -> None:
        _kernel.image_allowed(image, prefixes)
