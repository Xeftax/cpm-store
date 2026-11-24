# Reference specifications

Read this page before any implementation. The local markdown copies are in
`docs/specs/` (see `docs/specs/README.md` for attribution).

## Main normative references

| Ref         | Document                                                     | Version         | Official URL                                                                                                                    | Local copy                                                                                                                |
| ----------- | ------------------------------------------------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| [CPM-REST]  | OMA-TS-CPM_Message_Storage_Using_RESTFul_API                 | V1_0-20200907-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C.pdf | `docs/specs/OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C.md`                                              |
| [REST-NMS]  | OMA-TS-REST_NetAPI_NMS                                       | V1_0-20190528-C | https://www.openmobilealliance.org/release/REST_NETAPI_NMS/V1_0-20190528-C/OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C.pdf           | `docs/specs/OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C.md` (embedded 2026-11-08, docling conversion in `docs/specs/docling/`) |
| [CPM-STORE] | OMA-TS-CPM_Message_Store (IMAP binding)                      | V2_2-20170926-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Message_Store-V2_2-20170926-C.pdf                     | `docs/specs/OMA-TS-CPM_Message_Store-V2_2-20170926-C.md`                                                                  |
| [CPM-CONF]  | OMA-TS-CPM_Conversation_Function                             | V2_2-20200907-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Conversation_Function-V2_2-20200907-C.pdf             | `docs/specs/OMA-TS-CPM_Conversation_Function-V2_2-20200907-C.md`                                                          |
| [CPM-AD]    | OMA-AD-CPM (architecture)                                    | V2_2-20170926-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-AD-CPM-V2_2-20170926-C.pdf                                   | `docs/specs/OMA-AD-CPM-V2_2-20170926-C.md`                                                                                |
| [CPM-RD]    | OMA-RD-CPM (requirements)                                    | V2_2-20170926-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-RD-CPM-V2_2-20170926-C.pdf                                   | `docs/specs/OMA-RD-CPM-V2_2-20170926-C.md`                                                                                |
| [CPM-SD]    | OMA-TS-CPM_System_Description                                | V2_2-20170926-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_System_Description-V2_2-20170926-C.pdf                | `docs/specs/OMA-TS-CPM_System_Description-V2_2-20170926-C.md`                                                             |
| [RCC.11]    | GSMA — RCS Endorsement of OMA CPM 2.2 Conversation Functions | v12.0           | https://www.gsma.com (Networks / RCS section)                                                                                   | —                                                                                                                         |

## Useful IETF / 3GPP references

- RFC 3862 — CPIM (Content-Type `message/CPIM`), the format of CPM messages.
- RFC 7519 — JWT (OIDC ID Token), RFC 6749 — OAuth 2.0 (REST auth, spec §5.2.1).
- RFC 3501 — IMAP4rev1 (IMAP binding, later phase), RFC 5464 — METADATA,
  RFC 5257 — ANNOTATE.
- 3GPP TS 32.220 — GBA (alternative auth, spec §5.2.1).

## Map of the key sections of [CPM-REST] (the spec we implement in V1)

| Section     | Content                                                                                                         | Implemented in                 |
| ----------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| §5.2.1      | Auth: Bearer JWT (OIDC/OAuth2), GBA, Basic/Digest                                                               | `cpm-nms::auth`                |
| §5.3        | Resources: message object, folders, session info, group state, file transfer history                            | `cpm-core`, `cpm-nms`          |
| §5.5        | Subscriptions/notifications, strict sync, `restartToken`, `lastModSeq`                                          | `cpm-nms::sync`                |
| §5.6        | Metadata flags (`\Seen`, `\Answered`, `\Flagged`, `\Deleted`, `\Draft`, `\Recent`, `$Forwarded`, `Archived`...) | `cpm-core`, `cpm-nms::objects` |
| §6.1–6.6    | Client procedures: general operations, subscriptions, **sync §6.3**, objects §6.4, references, metadata         | `cpm-nms`, `cpm-client`        |
| §6.3.3      | First-time sync / steady-state sync                                                                             | `cpm-client`                   |
| §7.3        | Resources exposed by the server (folders, objects, bulk, search, move/copy)                                     | `cpm-nms` (endpoints)          |
| Annex B     | SCR (Static Conformance Requirements) → `docs/conformance.md`                                                   | tests                          |
| Annexes C–H | JSON/MIME examples (message object, session, file transfer, group state, call log) → golden fixtures            | `crates/*/tests`               |

Root resource: `{nmsHost}/nms/v1/base/{boxId}/objects|folders|subscriptions|notifications/...`
