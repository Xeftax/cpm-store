//! `cpm-client` — high-level backup/synchronization engine for CPM conversations.
//!
//! Combines `cpm-nms` (transport) and `cpm-msg` (message format) behind a small
//! API used by `cpm-ffi` (and therefore by Linphone). Implements first-time sync
//! and steady-state strict synchronization (spec §6.3.3). Local persistence is
//! delegated to the integrator through storage traits, so the library itself
//! stays stateless.

#![forbid(unsafe_code)]
