//! Atomic per-Gateway artifact bundle (registry + specs + skills).

use std::collections::BTreeMap;

use crate::error::{CoreError, CoreResult};
use crate::hash::sha256_hex;
use crate::registry::{DesiredHttpUpstream, RenderedRegistry, render_registry};
use crate::sidecar::{RenderedSidecar, ToolOverride, render_sidecar};
use crate::skills::{DesiredSkill, RenderedSkill, reject_duplicate_skill_names, render_skill};

/// Soft/hard ConfigMap payload budget (1 MiB).
pub const MAX_BUNDLE_BYTES: usize = 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DesiredUpstreamArtifacts {
    pub upstream: DesiredHttpUpstream,
    pub tool_overrides: Vec<ToolOverride>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactFile {
    pub path: String,
    pub data: String,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArtifactBundle {
    pub files: BTreeMap<String, ArtifactFile>,
    pub registry_sha256: String,
    pub bundle_sha256: String,
    pub total_bytes: usize,
}

/// Render one atomic artifact directory for a Gateway.
pub fn render_artifact_bundle(
    mut upstreams: Vec<DesiredUpstreamArtifacts>,
    skills: Vec<DesiredSkill>,
) -> CoreResult<ArtifactBundle> {
    reject_duplicate_skill_names(&skills)?;
    upstreams.sort_by(|a, b| a.upstream.name.cmp(&b.upstream.name));

    let mut files: BTreeMap<String, ArtifactFile> = BTreeMap::new();
    let mut desired_upstreams = Vec::with_capacity(upstreams.len());

    for entry in &upstreams {
        let sidecar: Option<RenderedSidecar> =
            render_sidecar(&entry.upstream.name, &entry.tool_overrides)?;
        let mut upstream = entry.upstream.clone();
        if let Some(sc) = sidecar {
            upstream.sidecar_relpath = Some(sc.filename.clone());
            files.insert(
                sc.filename.clone(),
                ArtifactFile {
                    path: sc.filename,
                    data: sc.text.clone(),
                    sha256: sc.sha256,
                },
            );
        } else {
            upstream.sidecar_relpath = None;
        }
        desired_upstreams.push(upstream);
    }

    let registry: RenderedRegistry = render_registry(desired_upstreams)?;
    files.insert(
        "registry.json".into(),
        ArtifactFile {
            path: "registry.json".into(),
            data: registry.text.clone(),
            sha256: registry.sha256.clone(),
        },
    );

    let mut rendered_skills: Vec<RenderedSkill> = Vec::with_capacity(skills.len());
    for skill in &skills {
        rendered_skills.push(render_skill(skill)?);
    }
    rendered_skills.sort_by(|a, b| a.filename.cmp(&b.filename));
    for skill in rendered_skills {
        files.insert(
            skill.filename.clone(),
            ArtifactFile {
                path: skill.filename,
                data: skill.text.clone(),
                sha256: skill.sha256,
            },
        );
    }

    let total_bytes = files.values().map(|f| f.data.len()).sum::<usize>();
    if total_bytes > MAX_BUNDLE_BYTES {
        return Err(CoreError::msg(format!(
            "artifact bundle is {total_bytes} bytes; max is {MAX_BUNDLE_BYTES}"
        )));
    }

    // Bundle digest over deterministic path→bytes concatenation.
    let mut material = String::new();
    for (path, file) in &files {
        material.push_str(path);
        material.push('\0');
        material.push_str(&file.data);
        material.push('\0');
    }

    Ok(ArtifactBundle {
        registry_sha256: registry.sha256,
        bundle_sha256: sha256_hex(material.as_bytes()),
        total_bytes,
        files,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::registry::DesiredHttpUpstream;
    use crate::sidecar::{TaskSupport, ToolOverride};
    use crate::skills::{DesiredSkill, DesiredSkillArg};

    #[test]
    fn builds_atomic_bundle_with_hashed_sidecar_and_skill() {
        let bundle = render_artifact_bundle(
            vec![DesiredUpstreamArtifacts {
                upstream: DesiredHttpUpstream {
                    name: "architect-c4".into(),
                    url: "http://architect-c4:8766/mcp".into(),
                    bearer_env: None,
                    description: Some("docs".into()),
                    sidecar_relpath: None,
                    enabled: true,
                },
                tool_overrides: vec![ToolOverride {
                    name: "get_model".into(),
                    read_only: true,
                    task_support: Some(TaskSupport::Forbidden),
                }],
            }],
            vec![DesiredSkill {
                name: "architect_overview".into(),
                description: "overview".into(),
                arguments: vec![DesiredSkillArg {
                    name: "topic".into(),
                    description: None,
                    required: true,
                    default: None,
                }],
                template: "topic={{topic}}".into(),
            }],
        )
        .unwrap();

        assert!(bundle.files.contains_key("registry.json"));
        assert!(
            bundle
                .files
                .keys()
                .any(|k| k.starts_with("specs/architect-c4-"))
        );
        assert!(bundle.files.contains_key("skills/architect_overview.yaml"));
        assert!(bundle.total_bytes < MAX_BUNDLE_BYTES);
        let registry = &bundle.files["registry.json"].data;
        assert!(registry.contains("specs/architect-c4-"));
        assert!(registry.contains("\"transport\": \"http\""));
    }

    #[test]
    fn rejects_oversized_bundle() {
        let huge_template = "x".repeat(MAX_BUNDLE_BYTES);
        let err = render_artifact_bundle(
            vec![],
            vec![DesiredSkill {
                name: "huge".into(),
                description: "d".into(),
                arguments: vec![],
                template: huge_template,
            }],
        )
        .unwrap_err();
        assert!(err.to_string().contains("max is"));
    }
}
