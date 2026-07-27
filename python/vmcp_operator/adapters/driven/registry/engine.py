"""Driven adapter that calls the Rust artifact kernel via idiomatic PyO3."""

from __future__ import annotations

import vmcp_operator._kernel as _kernel
from vmcp_operator.domain.models.artifacts import (
    ArtifactBundle,
    ArtifactFile,
    SkillDesired,
    UpstreamArtifactsDesired,
    UpstreamDesired,
)


class RegistryEngine:
    """Thin façade over ``vmcp_operator._kernel`` (no business logic here)."""

    def render_registry(self, upstreams: list[UpstreamDesired]) -> tuple[str, str]:
        out = _kernel.render_registry(upstreams)
        return out.text, out.sha256

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
