//! Synchronization state blob (ADR D3).
//!
//! The library stores nothing itself: the host persists this single
//! serializable blob under **one key** via the
//! [`SyncStateStore`](crate::ports::SyncStateStore) port. It carries the
//! strict-synchronization tokens of spec §5.5/§6.3.2 (REST-NMS §5.1.4.3–§5.1.4.5):
//! the box-wide `restartToken`, the highest `lastModSeq` seen, and listing
//! cursors (REST-NMS §5.1.11). Sync is server-authoritative (ADR D8): on
//! conflict the server wins (last `lastModSeq`).

use std::collections::BTreeMap;

use rest_json::rest_json;
use serde::{Deserialize, Serialize};

use crate::error::CpmError;

/// Serializable synchronization state (strict sync, spec §6.3.2).
///
/// JSON field names are camelCase per the [REST_NetAPI_Common] conventions.
#[rest_json(default)]
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyncState {
    /// Box-wide restart token identifying the point in time at which the
    /// client last checked for changes (REST-NMS §5.1.4.3, spec §5.5).
    pub restart_token: Option<String>,
    /// Highest `lastModSeq` processed; used to detect reordering and
    /// duplication of notifications (REST-NMS §5.1.4.4, spec §5.4).
    pub last_mod_seq: Option<u64>,
    /// Listing cursors (REST-NMS §5.1.11), keyed by the listing resource
    /// (e.g. a folder resource URL or a search scope).
    #[serde(skip_serializing_if = "BTreeMap::is_empty")]
    pub cursors: BTreeMap<String, String>,
}

impl SyncState {
    pub fn new() -> Self {
        Self::default()
    }

    /// Serializes the blob to JSON (the single host key holds this string).
    // review: ignore duplicate-fn-bodies — to_json and from_json each wrap a distinct serde_json call (to_string vs from_str); AST normalization (idents/literals -> I/S) makes them identical. Intentional duplication, documented (known-patterns when_not_applicable).
    pub fn to_json(&self) -> Result<String, CpmError> {
        serde_json::to_string(self).map_err(|e: serde_json::Error| {
            CpmError::Parse(format!("SyncState serialization failed: {e}"))
        })
    }

    /// Parses a blob previously stored by the host.
    // review: ignore duplicate-fn-bodies — see to_json above.
    pub fn from_json(json: &str) -> Result<Self, CpmError> {
        serde_json::from_str(json).map_err(|e: serde_json::Error| {
            CpmError::Parse(format!("SyncState deserialization failed: {e}"))
        })
    }

    /// Records progress reported by the server (server-authoritative, ADR D8):
    /// the restart token is replaced when provided, and `lastModSeq` only
    /// ever moves forward.
    pub fn record_progress(&mut self, restart_token: Option<String>, last_mod_seq: Option<u64>) {
        if restart_token.is_some() {
            self.restart_token = restart_token;
        }
        if let Some(seq) = last_mod_seq {
            self.last_mod_seq = Some(self.last_mod_seq.map_or(seq, |cur: u64| cur.max(seq)));
        }
    }

    /// Stores the cursor of a paged listing under `key`; `None` clears it
    /// (listing complete, REST-NMS §5.1.11).
    pub fn set_cursor(&mut self, key: impl Into<String>, cursor: Option<String>) {
        match cursor {
            Some(c) => {
                self.cursors.insert(key.into(), c);
            }
            None => {
                self.cursors.remove(&key.into());
            }
        }
    }

    pub fn cursor(&self, key: &str) -> Option<&str> {
        self.cursors.get(key).map(String::as_str)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sync_state_json_round_trip() {
        let mut state = SyncState::new();
        state.record_progress(Some("rt-1".to_owned()), Some(41));
        state.set_cursor("http://s/folders/f1", Some("cur-9".to_owned()));
        let json = state.to_json().unwrap();
        let back = SyncState::from_json(&json).unwrap();
        assert_eq!(back, state);
        assert_eq!(back.restart_token.as_deref(), Some("rt-1"));
        assert_eq!(back.last_mod_seq, Some(41));
        assert_eq!(back.cursor("http://s/folders/f1"), Some("cur-9"));
    }

    #[test]
    fn last_mod_seq_only_moves_forward() {
        let mut state = SyncState::new();
        state.record_progress(None, Some(50));
        state.record_progress(Some("rt-2".to_owned()), Some(48));
        assert_eq!(state.last_mod_seq, Some(50));
        assert_eq!(state.restart_token.as_deref(), Some("rt-2"));
    }

    #[test]
    fn from_json_rejects_garbage() {
        let err = SyncState::from_json("{not json").unwrap_err();
        assert!(matches!(err, CpmError::Parse(_)));
    }

    #[test]
    fn empty_state_serializes_compact() {
        let state = SyncState::new();
        assert_eq!(state.to_json().unwrap(), "{}");
    }
}
