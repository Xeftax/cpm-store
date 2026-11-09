//! `cpm-msg` — CPM message format (CPIM / MIME) parsing and serialization.
//!
//! CPM messages are stored as `message/CPIM` payloads (RFC 3862) wrapped in
//! NMS objects; see OMA-TS-CPM_Conversation_Function-V2_2 and the examples in
//! appendix C of the RESTful Message Storage spec (local copy in `docs/specs/`).
//! This crate converts between the wire format and the domain model in
//! `cpm-core`, and provides the mapping towards the integrator's conversation
//! model (e.g. Linphone chat rooms / chat messages).

#![forbid(unsafe_code)]
