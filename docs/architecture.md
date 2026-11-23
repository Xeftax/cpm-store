# Architecture

Pilot use case: integration into **Linphone** (conversation backup/sync).
The library stays generic — see the README.

## Overview — ports & adapters

`cpm-store` is a Cargo workspace organized as **ports & adapters** (pattern borrowed
from doc-station: ports in the core with no external dependencies, adapters in separate
crates, `Result` at every boundary):

```
┌──────────────────────────────────────────────────────────────┐
│  cpm-core   domain + PORTS — pure: no I/O, no unsafe         │
│  model/     Object, Folder, flags, SyncState, id mapping     │
│  ports/     traits: StoreBackend, MessageStorage,            │
│             SyncStateStore                                   │
│  error.rs   CpmError — Result<T, CpmError> everywhere        │
└───────────▲──────────────────────────────────────────────────┘
            │ port StoreBackend            │ ports MessageStorage + SyncStateStore
   ┌────────┴───────────┐                  │ (implemented by the host)
   │  INBOUND ADAPTERS  │                  ▼
┌──┴──────────┐  ┌───────────────┐   ┌───────────┐
│ cpm-nms     │  │ cpm-imap      │   │  the host │ (Linphone, SQLite)
│ REST adapter│  │ IMAP adapter  │   └─────┬─────┘
│ (V1)        │  │ (phase 7)     │         │
└──┬──────────┘  └───────────────┘         │
   └──────────┬────────────┘               │
              ▼                            │
        ┌────────────┐  port MessageCodec  │
        │ cpm-client │ ───────────────► ┌──┴───────┐
        │ sync       │                  │ cpm-msg  │ (CPIM / MIME)
        │ engine,    │                  └──────────┘
        │ binding-   │
        │ agnostic   │
        └─────┬──────┘
              │ Rust API
        ┌─────┴──────┐   outbound C adapter (vtable, catch_unwind)
        │ cpm-ffi    │ ─────────────────────────────► liblinphone (C/C++)
        │ (cbindgen) │
        └────────────┘
```

Rules:

- the **ports** (traits) live in `cpm-core::ports`; `cpm-core` depends only on
  serde/thiserror/chrono/uuid — no I/O, no `unsafe`;
- each **adapter** implements a port in its own crate (`cpm-nms`, `cpm-imap`);
- no panic crosses an adapter boundary: `Result<T, CpmError>` everywhere;
- one single HTTP entry point per adapter (centralized in its `http.rs`), immutable
  config passed to the constructor (no env reads in the library);
- the host-provided ports (`MessageStorage`, `SyncStateStore`) are exposed in C
  through a **vtable of function pointers** in `cpm-ffi` (cbindgen does not generate
  it by itself).

## Crates

| Crate        | Role                                                                                                                                                                                                   | Type                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------- |
| `cpm-core`   | NMS/CPM data model + **ports** (`StoreBackend`, `MessageStorage`, `SyncStateStore`), `CpmError`, `SyncState`, `objectId ↔ local id` mapping.                                                           | domain, pure            |
| `cpm-msg`    | `MessageCodec` port + CPIM impl (`message/CPIM`, RFC 3862) / MIME multipart; payload ↔ integrator conversation mapping.                                                                                | codec                   |
| `cpm-nms`    | **REST adapter**: implements `StoreBackend` on REST_NetAPI_NMS (auth, boxes, folders, objects CRUD/bulk/payload/flags, subscriptions, notifications, strict sync). `http.rs` centralizes all HTTP.     | inbound adapter (V1)    |
| `cpm-imap`   | **IMAP adapter**: implements `StoreBackend` on `OMA-TS-CPM_Message_Store-V2_2` (created in phase 7).                                                                                                   | inbound adapter (ph. 7) |
| `cpm-client` | **Binding-agnostic** sync engine: first-time + steady-state (strict sync §6.3), orchestrates `StoreBackend` + `MessageStorage` + `SyncStateStore` + `MessageCodec`. Stores nothing.                    | orchestration           |
| `cpm-ffi`    | **Outbound C adapter**: C API for liblinphone (cbindgen, `cdylib`/`staticlib`), vtable of the host ports, global tokio runtime (`OnceLock`), `catch_unwind` at the boundary. Only crate with `unsafe`. | outbound adapter        |

## Decisions (ADR)

- **D1 — The binding is an adapter, not a core choice.** The `StoreBackend` port
  defines the message store operations (folders, objects, payloads, flags,
  subscriptions, notifications, sync). Default adapter in V1: **REST**
  (`cpm-nms`); IMAP adapter (`cpm-imap`) in phase 7. The base spec
  `OMA-TS-REST_NetAPI_NMS` is embedded and QA'ed (2026-11-08). **Inversion
  criterion**: a named NMS deployment exposing only IMAP → IMAP becomes the
  default adapter.
- **D2 — Apache-2.0 license.** GPLv3/AGPL compatible → can be integrated into
  linphone-sdk while remaining reusable elsewhere.
- **D3 — The library stores nothing.** Two host-provided ports:
  `MessageStorage` (messages + `objectId ↔ local id` mapping) and `SyncStateStore`
  (a `SyncState` blob serializable to JSON — `restartToken`/`lastModSeq`/cursors —
  stored under **a single key** by the host, e.g. Linphone SQLite). `cpm-client`
  orchestrates through these ports.
- **D4 — Workspace `crates/*`, centralized dependencies** in
  `[workspace.dependencies]`, MSRV 1.85, edition 2024.
- **D5 — C FFI via cbindgen** (`cdylib` + `staticlib`). **FFI contract to be written
  before phase 6**: global tokio runtime owned by `cpm-ffi` via `OnceLock`
  (created at init, never recreated per call); explicit C vtable of the host ports;
  systematic `catch_unwind` at the boundary; no panic crosses the ABI.
- **D6 — JSON only on the REST side.** The server SCR makes JSON Mandatory;
  XML is Optional — not supported in V1.
- **D7 — E2E encryption out of V1 scope.** The library transports **opaque**
  payloads; end-to-end encryption (RCS E2EE) is an application layer on top of the
  message store. Key custody and erasure/GDPR server-side are the deployment's
  responsibility, to be documented on the integration side.
- **D8 — "Server-authoritative" sync.** `restartToken`/`lastModSeq` are the source of
  truth; on a flag conflict the server wins (latest `lastModSeq`). Local changes are
  uploaded (first-time / steady-state). The Linphone **history migration** =
  first-time sync + filling the mapping via `MessageStorage`.
- **D9 — Publication: the code is publishable, not the OMA specs.** The cpm-store
  code (Apache-2.0, original work) can be published as open source freely.
  The OMA documents (PDF, markdown conversions, images, fixtures extracted from
  the annexes) are under OMA copyright — internal/educational use only,
  redistribution requires written permission (Use Agreement omaspecworks.org):
  they are gitignored and fetched locally via `tools/specs_fetch.py` (see
  `docs/specs/README.md`, "Publication" section). Second condition before any
  integration into linphone-sdk: legal review of the Apache-2.0 ↔ AGPLv3
  compatibility under static linking (combined work, patent clause, AGPL §13,
  C ABI versioning) — external action, does not block publishing the code.
- **D10 — Interop: no open-source NMS/CPM server exists** (research of
  2026-11-08). Conformance criterion = spec annexes (golden tests extracted from
  the PDF) + `wiremock`; interop against a real server will happen when an NMS
  deployment is named by the integration team.

## Error handling

`cpm-core::CpmError` is the common error. Each crate may extend it, but every
public error must convert into `CpmError`. No panic on invalid server data: such
data becomes `CpmError::Parse` / `CpmError::Server`. No error crosses an adapter
boundary other than through `Result`.

## Synchronization (cpm-client)

Implementation of **strict synchronization** (spec §5.5, §6.3), binding-agnostic:

1. **First-time sync**: download everything existing via `StoreBackend` + upload the
   missing local data; fill the mapping via `MessageStorage`.
2. **Steady-state sync**: subscribe to notifications + polling, process changes via
   `restartToken` / `lastModSeq` (persisted through `SyncStateStore`),
   correlate with the local cache. On an unrecoverable error: fall back to a
   first-time sync (spec §6.3.3.2).

## Tests

- Unit tests per module.
- Integration: `wiremock` mocks the NMS server at the transport level (endpoints
  `/nms/v1/...`), never the adapter's internal methods.
- Golden fixtures: JSON/MIME examples from annexes C–H, **extracted from the official
  PDF** (`pdftotext`).
- Conformance: every SCR in `docs/conformance.md` has its test.

## Dependencies

All versions are pinned in the root `Cargo.toml`'s `[workspace.dependencies]`.
No direct dependency outside the workspace. TLS via rustls. Licenses +
advisories checked in CI by `cargo-deny` (`deny.toml`).

## LLM council review (2026-11-08)

5 advisors + anonymized peer review + chairman (transcript:
`reports/council-phase0-transcript.md`, visual: `reports/council-phase0.html`,
skill `llm-council`). Validated: D2, D4, D6; D1 (via port/adapter); D3 re-scoped as
ports; D5 with the FFI contract.

### Council open questions → resolution

| Open question                                     | Resolution                                                                                                                                        | Where         |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| D1 clash REST vs IMAP                             | `StoreBackend` port + adapters (`cpm-nms` REST default, `cpm-imap` ph. 7); inversion if a named IMAP-only deployment appears                      | D1, D10       |
| Who owns the sync state                           | `SyncStateStore` (blob, 1 host key) + `MessageStorage` (messages/mapping); `cpm-client` orchestrates                                              | D3            |
| OMA rights / public publication                   | internal use OK, redistribution = written OMA permission → **code publishable**, specs/fixtures gitignored + local fetch (`tools/specs_fetch.py`) | D9            |
| Legal: Apache-2.0 ↔ AGPLv3 at link time           | external action (lawyer) before linphone-sdk integration; private repo in the meantime                                                            | D9            |
| E2E encryption / key custody / GDPR               | out of V1 scope — opaque payloads, E2E = application layer                                                                                        | D7            |
| Mobile: binary size, battery, NDK CI vs MSRV 1.85 | check in phase 6; MSRV adjustable if old NDK builders block                                                                                       | roadmap ph. 6 |
| Multi-device conflicts + history migration        | server-authoritative (server wins), migration = first-time sync + mapping                                                                         | D8            |
| NMS server / who drives the integration           | no public NMS server; conformance = annexes + wiremock; deployment to be named by the integration team                                            | D10           |
