//! `cpm-nms` — RESTful client for OMA REST_NetAPI_NMS, as bound to CPM by
//! OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C.
//!
//! Planned modules (implemented phase by phase, see `docs/roadmap.md`):
//!
//! - `auth`      — Bearer (OIDC/OAuth2 JWT), Basic/Digest credentials (spec §5.2.1)
//! - `transport` — reqwest-based HTTP client; JSON only (NMS JSON is Mandatory, SCR B.2)
//! - `folders`   — folder CRUD, list, search, move/copy (spec §7.3.2)
//! - `objects`   — object CRUD, bulk ops, payload parts, flags (spec §6.4, §7.3.3)
//! - `sync`      — subscriptions, notifications, strict synchronization with
//!   `restartToken` / `lastModSeq` (spec §5.5, §6.3)
//!
//! Resource root: `{nmsHost}/nms/v1/base/{boxId}/...`

#![forbid(unsafe_code)]
