# cpm-store — Rust client for OMA CPM (Converged Personal Messaging)

Client library for the **OMA CPM** standard for **conversation backup / synchronization**.
**Pilot use case**: integration into **Linphone** (SIP/RCS client) — the concrete case
that drives decisions, tests and project direction, without being the only destination
(the C API of `cpm-ffi` remains reusable by any C/C++ client).

- **V1 scope**: CPM Message Storage via RESTful API
  (`OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C`), built on
  **OMA REST_NetAPI_NMS** (`OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C`).
- **Later phase**: IMAP binding (`OMA-TS-CPM_Message_Store-V2_2`).
- **Out of V1 scope**: SIP/MSRP signaling, charging, interworking.
- **Status**: phase 0 — workspace setup. See `docs/roadmap.md`.

## Quick start

```sh
cargo build --workspace
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
```

## Structure

```
crates/
├── cpm-core     ← NMS/CPM data model (pure: no I/O, no unsafe)
├── cpm-nms      ← REST_NetAPI_NMS client (transport, auth, folders, objects, sync)
├── cpm-msg      ← CPM message format (CPIM/MIME) + conversation mapping
├── cpm-client   ← high-level backup/sync engine (first-time + steady-state)
└── cpm-ffi      ← C API (cbindgen, cdylib/staticlib) for liblinphone
docs/
├── architecture.md   ← architecture and decisions (ADR)
├── specs.md          ← normative references (+ local copies in docs/specs/)
├── conformance.md    ← conformance checklist (SCR)
└── roadmap.md        ← phase plan
```

## Documentation

- `AGENTS.md` — entry point for contributing (including with an LLM)
- `docs/architecture.md` — architecture, layering, decisions
- `docs/specs.md` — reference OMA specs and where to find them locally
- `docs/conformance.md` — SCR requirements tracked item by item
- `docs/roadmap.md` — phases and exit criteria
- `docs/workflow.md` — dev strategy, agent workflow (owners), role of the human

## License

Apache-2.0 (see `LICENSE`) — GPLv3/AGPL compatible, so it can be integrated into
linphone-sdk.
