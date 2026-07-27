//! Profile skill validation/rendering (vmcp skills contract, no defaults).

use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

use crate::error::{CoreError, CoreResult};
use crate::hash::sha256_hex;

/// Operator-authored skill before YAML projection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DesiredSkill {
    pub name: String,
    pub description: String,
    pub arguments: Vec<DesiredSkillArg>,
    pub template: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DesiredSkillArg {
    pub name: String,
    pub description: Option<String>,
    pub required: bool,
    /// Operator policy forbids defaults until upstream runtime applies them.
    pub default: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RenderedSkill {
    pub filename: String,
    pub text: String,
    pub sha256: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct SkillWire {
    name: String,
    description: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    arguments: Vec<SkillArgWire>,
    template: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct SkillArgWire {
    name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    description: Option<String>,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    required: bool,
}

fn valid_skill_name(name: &str) -> bool {
    let bytes = name.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'_' || *b == b'-')
        && !name.contains("__")
}

/// Validate and render one skill YAML file (`skills/<name>.yaml`).
pub fn render_skill(skill: &DesiredSkill) -> CoreResult<RenderedSkill> {
    if !valid_skill_name(&skill.name) {
        return Err(CoreError::msg(format!(
            "skill `{}` has invalid name (must match ^[a-z0-9_-]{{1,64}}$ without `__`)",
            skill.name
        )));
    }
    if skill.description.trim().is_empty() {
        return Err(CoreError::msg(format!(
            "skill `{}` has empty description",
            skill.name
        )));
    }
    if skill.template.trim().is_empty() {
        return Err(CoreError::msg(format!(
            "skill `{}` has empty template",
            skill.name
        )));
    }

    let mut seen = BTreeSet::new();
    let mut arguments = Vec::with_capacity(skill.arguments.len());
    for arg in &skill.arguments {
        if arg.name.trim().is_empty() {
            return Err(CoreError::msg(format!(
                "skill `{}` has empty argument name",
                skill.name
            )));
        }
        if !seen.insert(arg.name.clone()) {
            return Err(CoreError::msg(format!(
                "skill `{}` has duplicate argument `{}`",
                skill.name, arg.name
            )));
        }
        if arg.required && arg.default.is_some() {
            return Err(CoreError::msg(format!(
                "skill `{}` argument `{}` is required but has a default",
                skill.name, arg.name
            )));
        }
        if arg.default.is_some() {
            // Runtime currently ignores defaults; profiles must not rely on them.
            return Err(CoreError::msg(format!(
                "skill `{}` argument `{}` sets default; forbidden until vmcp applies defaults",
                skill.name, arg.name
            )));
        }
        arguments.push(SkillArgWire {
            name: arg.name.clone(),
            description: arg.description.clone(),
            required: arg.required,
        });
    }

    let wire = SkillWire {
        name: skill.name.clone(),
        description: skill.description.clone(),
        arguments,
        template: skill.template.clone(),
    };
    let text =
        serde_yaml::to_string(&wire).map_err(|e| CoreError::msg(format!("skill yaml: {e}")))?;
    let digest = sha256_hex(text.as_bytes());
    Ok(RenderedSkill {
        filename: format!("skills/{}.yaml", skill.name),
        text,
        sha256: digest,
    })
}

/// Ensure skill names are unique across a Gateway bundle.
pub fn reject_duplicate_skill_names(skills: &[DesiredSkill]) -> CoreResult<()> {
    let mut seen = BTreeSet::new();
    for skill in skills {
        if !seen.insert(skill.name.as_str()) {
            return Err(CoreError::msg(format!(
                "duplicate skill name `{}`",
                skill.name
            )));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> DesiredSkill {
        DesiredSkill {
            name: "search_docs".into(),
            description: "Find docs".into(),
            arguments: vec![DesiredSkillArg {
                name: "library".into(),
                description: Some("lib".into()),
                required: true,
                default: None,
            }],
            template: "use {{library}}".into(),
        }
    }

    #[test]
    fn renders_yaml_skill() {
        let out = render_skill(&sample()).unwrap();
        assert_eq!(out.filename, "skills/search_docs.yaml");
        assert!(out.text.contains("name: search_docs"));
        assert!(out.text.contains("required: true"));
    }

    #[test]
    fn rejects_dunder_and_defaults() {
        let mut bad = sample();
        bad.name = "a__b".into();
        assert!(render_skill(&bad).is_err());

        let mut bad = sample();
        bad.arguments[0].required = false;
        bad.arguments[0].default = Some("x".into());
        assert!(
            render_skill(&bad)
                .unwrap_err()
                .to_string()
                .contains("default")
        );
    }

    #[test]
    fn rejects_required_with_default() {
        let mut bad = sample();
        bad.arguments[0].default = Some("x".into());
        assert!(
            render_skill(&bad)
                .unwrap_err()
                .to_string()
                .contains("required")
        );
    }

    #[test]
    fn rejects_empty_fields_and_duplicate_args_or_names() {
        let mut bad = sample();
        bad.description.clear();
        assert!(render_skill(&bad).is_err());
        bad = sample();
        bad.template = "   ".into();
        assert!(render_skill(&bad).is_err());
        bad = sample();
        bad.arguments.push(DesiredSkillArg {
            name: "library".into(),
            description: None,
            required: false,
            default: None,
        });
        assert!(render_skill(&bad).is_err());
        bad = sample();
        bad.arguments[0].name.clear();
        assert!(render_skill(&bad).is_err());
        assert!(reject_duplicate_skill_names(&[sample(), sample()]).is_err());
    }

    #[test]
    fn rejects_invalid_slug() {
        let mut bad = sample();
        bad.name = "BadName".into();
        assert!(render_skill(&bad).is_err());
    }
}
