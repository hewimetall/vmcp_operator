//! Deterministic digests for artifact verification.

use sha2::{Digest, Sha256};

/// Return a lowercase SHA-256 digest.
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
