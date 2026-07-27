//! Pure Rust core for vmcp-operator.
//!
//! Kubernetes and PyO3 types are intentionally forbidden here. The crate owns
//! deterministic validation/rendering helpers that are shared by the thin
//! Python extension.

use sha2::{Digest, Sha256};

/// Return a lowercase SHA-256 digest for deterministic artifact verification.
#[must_use]
pub fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha256_is_stable() {
        assert_eq!(
            sha256_hex(b"vmcp-operator"),
            "a78dc5576bf47b2fc53a63ee91392950bc99054b4a084b88d4c2843ba0352d58"
        );
    }
}
