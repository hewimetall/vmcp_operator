//! OCI image allowlist checks (parsed references, not string prefix hacks).

use crate::error::{CoreError, CoreResult};

/// Parsed OCI image reference components used for policy checks.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImageRef {
    pub repository: String,
    pub tag: Option<String>,
    pub digest: Option<String>,
}

/// Parse `registry/path/name:tag` or `registry/path/name@sha256:...`.
pub fn parse_image_ref(image: &str) -> CoreResult<ImageRef> {
    let image = image.trim();
    if image.is_empty() {
        return Err(CoreError::msg("image reference is empty"));
    }
    if image.contains(char::is_whitespace) {
        return Err(CoreError::msg(format!(
            "image reference `{image}` contains whitespace"
        )));
    }

    let (repo_and_tag, digest) = match image.split_once('@') {
        Some((left, dig)) => {
            if dig.is_empty() {
                return Err(CoreError::msg(format!(
                    "image reference `{image}` has empty digest"
                )));
            }
            (left, Some(dig.to_string()))
        }
        None => (image, None),
    };

    // Tag is only the final `:segment` after the last slash, so registry ports
    // like `registry.example.com:5000/ai/vmcp:1` keep the port in repository.
    let (repository, tag) = match repo_and_tag.rsplit_once(':') {
        Some((repo, maybe_tag)) if !repo.rsplit('/').next().unwrap_or("").contains('.') => {
            if maybe_tag.is_empty() {
                return Err(CoreError::msg(format!(
                    "image reference `{image}` has empty tag"
                )));
            }
            if maybe_tag.contains('/') {
                (repo_and_tag.to_string(), None)
            } else {
                (repo.to_string(), Some(maybe_tag.to_string()))
            }
        }
        _ => (repo_and_tag.to_string(), None),
    };

    if repository.is_empty() || !repository.contains('/') {
        return Err(CoreError::msg(format!(
            "image reference `{image}` must include a registry/repository path"
        )));
    }

    Ok(ImageRef {
        repository,
        tag,
        digest,
    })
}

/// Return true when the image repository equals or is under an allowlisted prefix.
pub fn image_allowed(image: &str, allowed_prefixes: &[String]) -> CoreResult<()> {
    if allowed_prefixes.is_empty() {
        return Err(CoreError::msg(
            "policy.allowedImagePrefixes must be a non-empty OCI allowlist",
        ));
    }
    let parsed = parse_image_ref(image)?;
    for prefix in allowed_prefixes {
        let prefix = prefix.trim_end_matches('/');
        if prefix.is_empty() {
            continue;
        }
        if parsed.repository == prefix || parsed.repository.starts_with(&(prefix.to_string() + "/"))
        {
            return Ok(());
        }
    }
    Err(CoreError::msg(format!(
        "image `{}` is outside allowed prefixes {:?}",
        parsed.repository, allowed_prefixes
    )))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_tag_and_digest() {
        let r = parse_image_ref("harbor.example.com/ai/vmcp:1.2.3").unwrap();
        assert_eq!(r.repository, "harbor.example.com/ai/vmcp");
        assert_eq!(r.tag.as_deref(), Some("1.2.3"));

        let r = parse_image_ref("harbor.example.com/ai/vmcp@sha256:abc").unwrap();
        assert_eq!(r.digest.as_deref(), Some("sha256:abc"));
    }

    #[test]
    fn allowlist_is_path_aware() {
        let allow = vec!["harbor.example.com/ai".into()];
        assert!(image_allowed("harbor.example.com/ai/vmcp:1", &allow).is_ok());
        assert!(image_allowed("harbor.example.com/ai-evil/vmcp:1", &allow).is_err());
        assert!(image_allowed("evil-harbor.example.com/ai/vmcp:1", &allow).is_err());
    }

    #[test]
    fn empty_allowlist_rejected() {
        assert!(image_allowed("harbor.example.com/ai/vmcp:1", &[]).is_err());
    }

    #[test]
    fn rejects_malformed_refs() {
        assert!(parse_image_ref("").is_err());
        assert!(parse_image_ref("no-slash").is_err());
        assert!(parse_image_ref("registry.example.com/ai/vmcp:").is_err());
        assert!(parse_image_ref("registry.example.com/ai/vmcp@").is_err());
        assert!(parse_image_ref("registry.example.com/ai/vmcp :1").is_err());
    }

    #[test]
    fn keeps_registry_port_in_repository() {
        let r = parse_image_ref("harbor.example.com:5000/ai/vmcp:9").unwrap();
        assert_eq!(r.repository, "harbor.example.com:5000/ai/vmcp");
        assert_eq!(r.tag.as_deref(), Some("9"));
        let allow = vec!["harbor.example.com:5000/ai".into()];
        assert!(image_allowed("harbor.example.com:5000/ai/vmcp:9", &allow).is_ok());
    }
}
