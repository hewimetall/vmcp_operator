//! Desired HTTP upstreams → vmcp `registry.json` wire via `vmcp-registry`.

use std::collections::BTreeMap;
use std::path::PathBuf;

use vmcp_registry::{MAX_UPSTREAMS, Registry, UpstreamSpec, UpstreamTransport};

use crate::error::{CoreError, CoreResult};
use crate::hash::sha256_hex;
use crate::naming::reject_graphql_name_collisions;

/// Operator desired state for one HTTP upstream (stdio is forbidden).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DesiredHttpUpstream {
    pub name: String,
    pub url: String,
    /// When set, rendered as `bearer: ${ENV_NAME}`.
    pub bearer_env: Option<String>,
    pub description: Option<String>,
    /// Relative path inside the artifact volume, e.g. `specs/foo-abcd.json`.
    pub sidecar_relpath: Option<String>,
    pub enabled: bool,
    /// Forward caller identity (`X-Vmcp-Subject` / `X-Vmcp-Groups`) to this
    /// upstream on `tools/call`. Default `false` — enable only for internal
    /// adapters (vmcp v1.2+).
    pub forward_identity: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RenderedRegistry {
    pub text: String,
    pub sha256: String,
}

fn validate_env_token(name: &str) -> CoreResult<()> {
    if name.is_empty() || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Err(CoreError::msg(format!(
            "invalid bearer env name `{name}` (must match [A-Za-z0-9_]+)"
        )));
    }
    Ok(())
}

fn to_upstream_spec(desired: &DesiredHttpUpstream) -> CoreResult<UpstreamSpec> {
    if desired.name.trim().is_empty() {
        return Err(CoreError::msg("upstream name must be non-empty"));
    }
    if desired.url.trim().is_empty() {
        return Err(CoreError::msg(format!(
            "upstream `{}` requires a non-empty HTTP url",
            desired.name
        )));
    }
    let bearer = match &desired.bearer_env {
        Some(env_name) => {
            validate_env_token(env_name)?;
            Some(format!("${{{env_name}}}"))
        }
        None => None,
    };
    let sidecar_spec = desired.sidecar_relpath.as_ref().map(PathBuf::from);

    Ok(UpstreamSpec {
        name: desired.name.clone(),
        description: desired.description.clone(),
        transport: UpstreamTransport::Http,
        url: Some(desired.url.clone()),
        bearer,
        command: String::new(),
        args: Vec::new(),
        env: BTreeMap::new(),
        cwd: None,
        sidecar_spec,
        enabled: desired.enabled,
        forward_identity: desired.forward_identity,
    })
}

/// Render a deterministic `registry.json` containing only HTTP upstreams.
pub fn render_registry(mut upstreams: Vec<DesiredHttpUpstream>) -> CoreResult<RenderedRegistry> {
    if upstreams.len() > MAX_UPSTREAMS {
        return Err(CoreError::msg(format!(
            "too many upstreams ({}); max is {MAX_UPSTREAMS}",
            upstreams.len()
        )));
    }

    upstreams.sort_by(|a, b| a.name.cmp(&b.name));
    let names: Vec<String> = upstreams.iter().map(|u| u.name.clone()).collect();
    let mut seen = std::collections::BTreeSet::new();
    for name in &names {
        if !seen.insert(name.clone()) {
            return Err(CoreError::msg(format!("duplicate upstream name: {name}")));
        }
    }
    reject_graphql_name_collisions(&names)?;

    let specs = upstreams
        .iter()
        .map(to_upstream_spec)
        .collect::<CoreResult<Vec<_>>>()?;

    let registry = Registry { upstreams: specs };
    // Round-trip through vmcp-registry types so deny_unknown_fields / wire shape
    // stay aligned with upstream. Pretty JSON + trailing newline for stable sha.
    let text = serde_json::to_string_pretty(&registry)
        .map_err(|e| CoreError::msg(format!("registry serialize: {e}")))?
        + "\n";

    // Hard fail if serialized payload accidentally contains stdio defaults that
    // omit transport — operator always emits explicit http.
    if text.contains("\"transport\": \"stdio\"") || !text.contains("\"transport\": \"http\"") {
        // Empty registry is allowed (no transport key).
        if !registry.upstreams.is_empty() {
            return Err(CoreError::msg(
                "registry renderer must emit explicit http transport only",
            ));
        }
    }

    Ok(RenderedRegistry {
        sha256: sha256_hex(text.as_bytes()),
        text,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use vmcp_registry::Registry as WireRegistry;

    fn sample(name: &str, url: &str) -> DesiredHttpUpstream {
        DesiredHttpUpstream {
            name: name.into(),
            url: url.into(),
            bearer_env: Some("DOCS_TOKEN".into()),
            description: Some("docs".into()),
            sidecar_relpath: Some("specs/docs-aaaa.json".into()),
            enabled: true,
            forward_identity: false,
        }
    }

    #[test]
    fn renders_forward_identity_when_enabled() {
        let mut up = sample("stand_api", "http://stand-api.svc/mcp");
        up.forward_identity = true;
        up.bearer_env = None;
        let rendered = render_registry(vec![up]).unwrap();
        assert!(rendered.text.contains("\"forward_identity\": true"));
        let parsed: WireRegistry = serde_json::from_str(&rendered.text).unwrap();
        assert!(parsed.upstreams[0].forward_identity);
    }

    #[test]
    fn renders_sorted_http_upstreams() {
        let rendered = render_registry(vec![
            sample("tavily", "https://tavily.example/mcp"),
            sample("context7", "https://context7.example/mcp"),
        ])
        .unwrap();
        let parsed: WireRegistry = serde_json::from_str(&rendered.text).unwrap();
        assert_eq!(parsed.upstreams.len(), 2);
        assert_eq!(parsed.upstreams[0].name, "context7");
        assert_eq!(parsed.upstreams[0].transport, UpstreamTransport::Http);
        assert_eq!(parsed.upstreams[0].bearer.as_deref(), Some("${DOCS_TOKEN}"));
        assert!(rendered.text.contains("\"upstreams\""));
        assert!(!rendered.text.contains("\"servers\""));
    }

    #[test]
    fn rejects_duplicate_and_graphql_collision() {
        assert!(
            render_registry(vec![
                sample("a", "https://a/mcp"),
                sample("a", "https://b/mcp"),
            ])
            .is_err()
        );
        assert!(
            render_registry(vec![
                sample("rust-demo", "https://a/mcp"),
                sample("rust_demo", "https://b/mcp"),
            ])
            .is_err()
        );
    }

    #[test]
    fn rejects_over_max_upstreams() {
        let many = (0..=MAX_UPSTREAMS)
            .map(|i| sample(&format!("u{i}"), "https://x/mcp"))
            .collect::<Vec<_>>();
        assert!(
            render_registry(many)
                .unwrap_err()
                .to_string()
                .contains("too many")
        );
    }

    #[test]
    fn legacy_servers_key_rejected_by_upstream_type() {
        let err = serde_json::from_str::<WireRegistry>(r#"{"servers":[]}"#).unwrap_err();
        assert!(
            err.to_string().contains("servers") || err.to_string().contains("unknown field"),
            "{err}"
        );
    }

    #[test]
    fn empty_registry_ok() {
        let rendered = render_registry(vec![]).unwrap();
        assert_eq!(rendered.text, "{\n  \"upstreams\": []\n}\n");
    }

    #[test]
    fn rejects_missing_url_and_bad_env() {
        let mut bad = sample("x", "");
        assert!(render_registry(vec![bad.clone()]).is_err());
        bad.url = "https://x/mcp".into();
        bad.bearer_env = Some("BAD-ENV".into());
        assert!(render_registry(vec![bad]).is_err());
        let mut anon = sample("ok", "https://x/mcp");
        anon.bearer_env = None;
        anon.name = String::new();
        assert!(render_registry(vec![anon]).is_err());
    }
}
