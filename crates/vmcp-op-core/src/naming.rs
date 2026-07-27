//! GraphQL identifier transforms mirrored from vmcp-graphql.
//!
//! Upstream source of truth:
//! `hewimetall/vmcp` `crates/vmcp-graphql/src/lib.rs` (`pascal_case` / `camel_case`)
//! at rev `f6664e6be8d6926b7bd81683eb47981736d642c3`.
//! We keep a local copy so `vmcp-op-core` does not pull the heavy GraphQL crate.

use std::collections::BTreeMap;

use crate::error::{CoreError, CoreResult};

/// Convert `rust_demo` / `rust-demo` → `RustDemo`.
#[must_use]
pub fn pascal_case(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut upper_next = true;
    for ch in s.chars() {
        if ch == '_' || ch == '-' || ch.is_whitespace() {
            upper_next = true;
            continue;
        }
        if upper_next {
            for u in ch.to_uppercase() {
                out.push(u);
            }
            upper_next = false;
        } else {
            out.push(ch);
        }
    }
    out
}

/// Convert `rust_demo` → `rustDemo`.
#[must_use]
pub fn camel_case(s: &str) -> String {
    let p = pascal_case(s);
    let mut chars = p.chars();
    match chars.next() {
        Some(c) => {
            let mut out = String::with_capacity(p.len());
            for l in c.to_lowercase() {
                out.push(l);
            }
            out.extend(chars);
            out
        }
        None => String::new(),
    }
}

/// Reject upstream names that collide after GraphQL Pascal/camel transforms.
pub fn reject_graphql_name_collisions(names: &[String]) -> CoreResult<()> {
    let mut by_pascal: BTreeMap<String, String> = BTreeMap::new();
    let mut by_camel: BTreeMap<String, String> = BTreeMap::new();
    for name in names {
        let pascal = pascal_case(name);
        let camel = camel_case(name);
        if pascal.is_empty() || camel.is_empty() {
            return Err(CoreError::msg(format!(
                "upstream `{name}` produces an empty GraphQL identifier"
            )));
        }
        if let Some(prev) = by_pascal.insert(pascal.clone(), name.clone()) {
            return Err(CoreError::msg(format!(
                "GraphQL PascalCase collision between `{prev}` and `{name}` → `{pascal}`"
            )));
        }
        if let Some(prev) = by_camel.insert(camel.clone(), name.clone()) {
            return Err(CoreError::msg(format!(
                "GraphQL camelCase collision between `{prev}` and `{name}` → `{camel}`"
            )));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pascal_camel_match_upstream_examples() {
        assert_eq!(pascal_case("rust_demo"), "RustDemo");
        assert_eq!(pascal_case("rust-demo"), "RustDemo");
        assert_eq!(camel_case("rust_demo"), "rustDemo");
        assert_eq!(camel_case("query_graphql"), "queryGraphql");
    }

    #[test]
    fn hyphen_underscore_collide() {
        let names = vec!["rust-demo".into(), "rust_demo".into()];
        let err = reject_graphql_name_collisions(&names).unwrap_err();
        assert!(err.to_string().contains("collision"));
    }

    #[test]
    fn distinct_names_ok() {
        let names = vec!["context7".into(), "tavily".into()];
        assert!(reject_graphql_name_collisions(&names).is_ok());
    }

    #[test]
    fn empty_identifier_rejected() {
        let err = reject_graphql_name_collisions(&[String::new()]).unwrap_err();
        assert!(err.to_string().contains("empty GraphQL identifier"));
    }

    #[test]
    fn camel_empty_input() {
        assert_eq!(camel_case(""), "");
        assert_eq!(pascal_case("---"), "");
    }
}
