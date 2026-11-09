//! Ports of the ports & adapters architecture (see `docs/architecture.md`).
//!
//! - [`StoreBackend`] is implemented by the storage adapters (`cpm-nms` REST
//!   in V1, `cpm-imap` later) — it is the client side of the message store API
//!   (spec §6, §7.3; REST-NMS §5.2).
//! - [`MessageStorage`] and [`SyncStateStore`] are provided by the host
//!   (e.g. Linphone's SQLite store) and exposed over the C FFI as a vtable
//!   (ADR D3/D5).
//!
//! All ports are async and object-safe (`async_trait`): the host ports must be
//! usable as `&dyn MessageStorage` / `&dyn SyncStateStore` so that `cpm-ffi`
//! can wrap them in its C vtable and tests can substitute mocks. Native
//! `async fn` in traits (stable since 1.75) is *not* dyn-compatible, hence
//! `async-trait` (already a workspace dependency).
//!
//! No panic crosses a port boundary: every method returns `Result<T, CpmError>`.

pub mod backend;
pub mod storage;
pub mod sync_state;

pub use backend::{FolderPage, ObjectPage, StoreBackend};
pub use storage::{MessageStorage, StoredMessage};
pub use sync_state::SyncStateStore;
