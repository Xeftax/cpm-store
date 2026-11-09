//! Error type shared by all `cpm_*` crates.

use thiserror::Error;

/// Errors returned by the CPM client library.
#[derive(Debug, Error)]
pub enum CpmError {
    /// HTTP/TLS/transport level failure (client side).
    #[error("transport error: {0}")]
    Transport(String),
    /// Authentication or authorization rejected by the server.
    #[error("authentication error: {0}")]
    Auth(String),
    /// The server answered with a non-success HTTP status.
    #[error("server error (HTTP {status}): {body}")]
    Server { status: u16, body: String },
    /// A payload (JSON, MIME, CPIM) could not be parsed.
    #[error("parse error: {0}")]
    Parse(String),
    /// The synchronization state machine failed.
    #[error("synchronization error: {0}")]
    Sync(String),
    /// The local storage backend (provided by the integrator) failed.
    #[error("local storage error: {0}")]
    Storage(String),
    /// An object does not conform to the CPM/NMS model.
    #[error("invalid CPM object: {0}")]
    InvalidObject(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn error_display_is_stable() {
        let e = CpmError::Server {
            status: 404,
            body: "not found".into(),
        };
        assert_eq!(e.to_string(), "server error (HTTP 404): not found");
    }
}
