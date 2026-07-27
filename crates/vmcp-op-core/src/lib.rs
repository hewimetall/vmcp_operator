//! Pure Rust core for vmcp-operator.
//!
//! Kubernetes and PyO3 types are intentionally forbidden here. The crate owns
//! deterministic validation/rendering helpers that are shared by the thin
//! Python extension.

mod bundle;
mod error;
mod hash;
mod image_policy;
mod naming;
mod registry;
mod sidecar;
mod skills;

pub use bundle::{
    ArtifactBundle, ArtifactFile, DesiredUpstreamArtifacts, MAX_BUNDLE_BYTES,
    render_artifact_bundle,
};
pub use error::{CoreError, CoreResult};
pub use hash::sha256_hex;
pub use image_policy::{ImageRef, image_allowed, parse_image_ref};
pub use naming::{camel_case, pascal_case, reject_graphql_name_collisions};
pub use registry::{DesiredHttpUpstream, RenderedRegistry, render_registry};
pub use sidecar::{RenderedSidecar, TaskSupport, ToolOverride, render_sidecar};
pub use skills::{
    DesiredSkill, DesiredSkillArg, RenderedSkill, reject_duplicate_skill_names, render_skill,
};
