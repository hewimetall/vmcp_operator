//! Shared error type for pure core validation/rendering.

use thiserror::Error;

/// Operator-policy or artifact rendering failure.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum CoreError {
    #[error("{0}")]
    Message(String),
}

impl CoreError {
    #[must_use]
    pub fn msg(message: impl Into<String>) -> Self {
        Self::Message(message.into())
    }
}

pub type CoreResult<T> = Result<T, CoreError>;
