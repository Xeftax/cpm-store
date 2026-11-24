//! `SyncStateStore` — host-provided port persisting the [`SyncState`] blob
//! under a single key (ADR D3).
//!
//! `cpm-client` reads/writes the strict-sync tokens (`restartToken`,
//! `lastModSeq`, cursors — spec §5.5/§6.3.2) exclusively through this port.

use async_trait::async_trait;

use crate::error::CpmError;
use crate::model::SyncState;

/// Persistence of the synchronization state blob, provided by the host.
#[async_trait]
pub trait SyncStateStore: Send + Sync {
    /// Load the stored blob; `Ok(None)` when the client never synchronized.
    async fn load(&self) -> Result<Option<SyncState>, CpmError>;

    /// Persist the blob (single host key, ADR D3).
    async fn save(&self, state: &SyncState) -> Result<(), CpmError>;
}
