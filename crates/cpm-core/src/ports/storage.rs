//! `MessageStorage` — host-provided port for local message persistence and the
//! `objectId ↔ local id` mapping (ADR D3).
//!
//! The library stores nothing itself; the host (e.g. Linphone's SQLite store)
//! implements this port and `cpm-ffi` exposes it to C as a vtable (ADR D5).

use async_trait::async_trait;

use crate::error::CpmError;
use crate::model::{LocalId, NmsObject, ObjectId};

/// A message as stored locally by the host: metadata plus the opaque payload
/// (ADR D7).
#[derive(Debug, Clone, PartialEq)]
pub struct StoredMessage {
    pub object: NmsObject,
    pub payload: Vec<u8>,
}

/// Local message storage provided by the integrator.
#[async_trait]
pub trait MessageStorage: Send + Sync {
    /// Insert or replace the local message `local_id` (metadata + payload).
    async fn store_message(
        &self,
        local_id: &LocalId,
        object: &NmsObject,
        payload: &[u8],
    ) -> Result<(), CpmError>;

    /// Fetch a local message by its local id.
    async fn get_message(&self, local_id: &LocalId) -> Result<Option<StoredMessage>, CpmError>;

    /// List all local message ids (used by first-time sync upload, spec
    /// §6.3.3.1).
    async fn list_messages(&self) -> Result<Vec<LocalId>, CpmError>;

    /// Delete a local message.
    async fn delete_message(&self, local_id: &LocalId) -> Result<(), CpmError>;

    /// Record the `objectId ↔ local id` association (spec §5.4; ADR D3).
    async fn set_mapping(&self, object_id: &ObjectId, local_id: &LocalId) -> Result<(), CpmError>;

    /// Local id for a server object, if known.
    async fn local_id_for(&self, object_id: &ObjectId) -> Result<Option<LocalId>, CpmError>;

    /// Server object id for a local message, if known.
    async fn object_id_for(&self, local_id: &LocalId) -> Result<Option<ObjectId>, CpmError>;

    /// Drop an association (e.g. after the object was deleted server-side).
    async fn remove_mapping(&self, object_id: &ObjectId) -> Result<(), CpmError>;
}
