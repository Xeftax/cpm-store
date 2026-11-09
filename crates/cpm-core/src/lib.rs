//! `cpm-core` — core data model for OMA CPM (Converged Personal Messaging).
//!
//! This crate is pure: no I/O, no network, no `unsafe`. It defines the types
//! shared by the whole workspace (NMS objects, folders, metadata flags, CPM
//! object kinds) and the common error type.
//!
//! Normative references: OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C
//! and OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C (see `docs/specs.md`).

#![forbid(unsafe_code)]

pub mod error;

pub use error::CpmError;

/// Crate version, also exposed through the C FFI for diagnostics.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
