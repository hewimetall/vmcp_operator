//! Sidecar spec rendering with operator-required explicit readOnly.

use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};
use vmcp_registry::{SidecarSpec, SidecarTool, TaskSupportHint};

use crate::error::{CoreError, CoreResult};
use crate::hash::sha256_hex;

/// Operator-facing tool override (camelCase CR field → snake wire).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolOverride {
    pub name: String,
    pub read_only: bool,
    pub task_support: Option<TaskSupport>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TaskSupport {
    Forbidden,
    Optional,
    Required,
}

impl From<TaskSupport> for TaskSupportHint {
    fn from(value: TaskSupport) -> Self {
        match value {
            TaskSupport::Forbidden => Self::Forbidden,
            TaskSupport::Optional => Self::Optional,
            TaskSupport::Required => Self::Required,
        }
    }
}

/// Rendered sidecar file destined for the atomic artifact ConfigMap.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RenderedSidecar {
    pub filename: String,
    pub text: String,
    pub sha256: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct SidecarWire {
    server: String,
    tools: Vec<SidecarToolWire>,
}

#[derive(Debug, Serialize, Deserialize)]
struct SidecarToolWire {
    name: String,
    read_only: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    task_support: Option<TaskSupportHint>,
}

/// Validate overrides and render a content-addressed sidecar JSON file.
pub fn render_sidecar(
    server: &str,
    overrides: &[ToolOverride],
) -> CoreResult<Option<RenderedSidecar>> {
    if overrides.is_empty() {
        return Ok(None);
    }
    if server.trim().is_empty() {
        return Err(CoreError::msg("sidecar server name must be non-empty"));
    }

    let mut seen = BTreeSet::new();
    let mut tools = Vec::with_capacity(overrides.len());
    for ov in overrides {
        if ov.name.trim().is_empty() {
            return Err(CoreError::msg("toolOverrides.name must be non-empty"));
        }
        if !seen.insert(ov.name.clone()) {
            return Err(CoreError::msg(format!(
                "duplicate tool override `{}` for server `{server}`",
                ov.name
            )));
        }
        tools.push(SidecarTool {
            name: ov.name.clone(),
            read_only: ov.read_only,
            description: None,
            task_support: ov.task_support.map(Into::into),
        });
    }

    // Serialize through vmcp_registry types for wire fidelity, then pretty-print
    // a deterministic object (sorted tool names already preserved by input order
    // after uniqueness checks; sort for stability).
    tools.sort_by(|a, b| a.name.cmp(&b.name));
    let spec = SidecarSpec {
        server: server.to_string(),
        tools: tools.clone(),
    };
    let wire = SidecarWire {
        server: spec.server,
        tools: tools
            .into_iter()
            .map(|t| SidecarToolWire {
                name: t.name,
                read_only: t.read_only,
                task_support: t.task_support,
            })
            .collect(),
    };
    let text = serde_json::to_string_pretty(&wire)
        .map_err(|e| CoreError::msg(format!("sidecar serialize: {e}")))?
        + "\n";
    let digest = sha256_hex(text.as_bytes());
    let short = &digest[..12];
    Ok(Some(RenderedSidecar {
        filename: format!("specs/{server}-{short}.json"),
        text,
        sha256: digest,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn requires_unique_tools_and_hashes_path() {
        let rendered = render_sidecar(
            "architect-c4",
            &[ToolOverride {
                name: "get_model".into(),
                read_only: true,
                task_support: Some(TaskSupport::Forbidden),
            }],
        )
        .unwrap()
        .unwrap();
        assert!(rendered.filename.starts_with("specs/architect-c4-"));
        assert!(rendered.filename.ends_with(".json"));
        assert!(rendered.text.contains("\"read_only\": true"));
        assert!(!rendered.text.contains("\"read_only\":true"));
    }

    #[test]
    fn duplicate_tool_rejected() {
        let err = render_sidecar(
            "x",
            &[
                ToolOverride {
                    name: "a".into(),
                    read_only: true,
                    task_support: None,
                },
                ToolOverride {
                    name: "a".into(),
                    read_only: false,
                    task_support: None,
                },
            ],
        )
        .unwrap_err();
        assert!(err.to_string().contains("duplicate"));
    }

    #[test]
    fn empty_overrides_skip_file() {
        assert!(render_sidecar("x", &[]).unwrap().is_none());
    }

    #[test]
    fn rejects_empty_server_or_tool_name() {
        assert!(
            render_sidecar(
                "",
                &[ToolOverride {
                    name: "a".into(),
                    read_only: true,
                    task_support: None,
                }]
            )
            .is_err()
        );
        assert!(
            render_sidecar(
                "x",
                &[ToolOverride {
                    name: " ".into(),
                    read_only: true,
                    task_support: None,
                }]
            )
            .is_err()
        );
    }
}
