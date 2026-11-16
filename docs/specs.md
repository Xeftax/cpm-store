# Spécifications de référence

Lire cette page avant toute implémentation. Les copies markdown locales sont dans
`docs/specs/` (voir `docs/specs/README.md` pour l'attribution).

## Références normatives principales

| Ref         | Document                                                     | Version         | URL officielle                                                                                                                  | Copie locale                                                                                                                 |
| ----------- | ------------------------------------------------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| [CPM-REST]  | OMA-TS-CPM_Message_Storage_Using_RESTFul_API                 | V1_0-20200907-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C.pdf | `docs/specs/OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C.md`                                                 |
| [REST-NMS]  | OMA-TS-REST_NetAPI_NMS                                       | V1_0-20190528-C | https://www.openmobilealliance.org/release/REST_NETAPI_NMS/V1_0-20190528-C/OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C.pdf           | `docs/specs/OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C.md` (embarquée 2026-11-08, conversion docling dans `docs/specs/docling/`) |
| [CPM-STORE] | OMA-TS-CPM_Message_Store (binding IMAP)                      | V2_2-20170926-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Message_Store-V2_2-20170926-C.pdf                     | `docs/specs/OMA-TS-CPM_Message_Store-V2_2-20170926-C.md`                                                                     |
| [CPM-CONF]  | OMA-TS-CPM_Conversation_Function                             | V2_2-20200907-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Conversation_Function-V2_2-20200907-C.pdf             | `docs/specs/OMA-TS-CPM_Conversation_Function-V2_2-20200907-C.md`                                                             |
| [CPM-AD]    | OMA-AD-CPM (architecture)                                    | V2_2-20170926-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-AD-CPM-V2_2-20170926-C.pdf                                   | `docs/specs/OMA-AD-CPM-V2_2-20170926-C.md`                                                                                   |
| [CPM-RD]    | OMA-RD-CPM (requirements)                                    | V2_2-20170926-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-RD-CPM-V2_2-20170926-C.pdf                                   | `docs/specs/OMA-RD-CPM-V2_2-20170926-C.md`                                                                                   |
| [CPM-SD]    | OMA-TS-CPM_System_Description                                | V2_2-20170926-C | https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_System_Description-V2_2-20170926-C.pdf                | `docs/specs/OMA-TS-CPM_System_Description-V2_2-20170926-C.md`                                                                |
| [RCC.11]    | GSMA — RCS Endorsement of OMA CPM 2.2 Conversation Functions | v12.0           | https://www.gsma.com (rubrique Networks / RCS)                                                                                  | —                                                                                                                            |

## Références IETF / 3GPP utiles

- RFC 3862 — CPIM (Content-Type `message/CPIM`), le format des messages CPM.
- RFC 7519 — JWT (ID Token OIDC), RFC 6749 — OAuth 2.0 (auth REST, spec §5.2.1).
- RFC 3501 — IMAP4rev1 (binding IMAP, phase ultérieure), RFC 5464 — METADATA,
  RFC 5257 — ANNOTATE.
- 3GPP TS 32.220 — GBA (auth alternative, spec §5.2.1).

## Carte des sections clés de [CPM-REST] (la spec qu'on implémente en V1)

| Section     | Contenu                                                                                                               | Implémenté dans                |
| ----------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| §5.2.1      | Auth : Bearer JWT (OIDC/OAuth2), GBA, Basic/Digest                                                                    | `cpm-nms::auth`                |
| §5.3        | Ressources : message object, folders, session info, group state, file transfer history                                | `cpm-core`, `cpm-nms`          |
| §5.5        | Subscriptions/notifications, strict sync, `restartToken`, `lastModSeq`                                                | `cpm-nms::sync`                |
| §5.6        | Flags de métadonnées (`\Seen`, `\Answered`, `\Flagged`, `\Deleted`, `\Draft`, `\Recent`, `$Forwarded`, `Archived`...) | `cpm-core`, `cpm-nms::objects` |
| §6.1–6.6    | Procédures client : opérations générales, subscriptions, **sync §6.3**, objets §6.4, références, métadonnées          | `cpm-nms`, `cpm-client`        |
| §6.3.3      | First-time sync / steady-state sync                                                                                   | `cpm-client`                   |
| §7.3        | Ressources exposées par le serveur (folders, objects, bulk, search, move/copy)                                        | `cpm-nms` (endpoints)          |
| Annexe B    | SCR (Static Conformance Requirements) → `docs/conformance.md`                                                         | tests                          |
| Annexes C–H | Exemples JSON/MIME (message object, session, file transfer, group state, call log) → fixtures golden                  | `crates/*/tests`               |

Ressource racine : `{nmsHost}/nms/v1/base/{boxId}/objects|folders|subscriptions|notifications/...`
