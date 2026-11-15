# Architecture

Cas d'usage pilote : intégration dans **Linphone** (backup/sync de conversations).
La bibliothèque reste générique — voir README.

## Vue d'ensemble — ports & adapters

`cpm-store` est un workspace Cargo organisé en **ports & adapters** (pattern calqué
sur doc-station : ports dans le core sans dépendances externes, adapters dans des
crates séparés, `Result` à chaque frontière) :

```
┌──────────────────────────────────────────────────────────────┐
│  cpm-core   domain + PORTS — pur : aucune I/O, pas d'unsafe  │
│  model/     Object, Folder, flags, SyncState, mapping ids    │
│  ports/     traits : StoreBackend, MessageStorage,           │
│             SyncStateStore                                   │
│  error.rs   CpmError — Result<T, CpmError> partout           │
└───────────▲──────────────────────────────────────────────────┘
            │ port StoreBackend            │ ports MessageStorage + SyncStateStore
   ┌────────┴───────────┐                  │ (implémentés par l'hôte)
   │  ADAPTERS entrants │                  ▼
┌──┴──────────┐  ┌───────────────┐   ┌───────────┐
│ cpm-nms     │  │ cpm-imap      │   │  l'hôte   │ (Linphone, SQLite)
│ adapter REST│  │ adapter IMAP  │   └─────┬─────┘
│ (V1)        │  │ (phase 7)     │         │
└──┬──────────┘  └───────────────┘         │
   └──────────┬────────────┘               │
              ▼                            │
        ┌────────────┐  port MessageCodec  │
        │ cpm-client │ ───────────────► ┌──┴───────┐
        │ moteur de  │                  │ cpm-msg  │ (CPIM / MIME)
        │ synchro,   │                  └──────────┘
        │ binding-   │
        │ agnostic   │
        └─────┬──────┘
              │ API Rust
        ┌─────┴──────┐   adapter sortant C (vtable, catch_unwind)
        │ cpm-ffi    │ ─────────────────────────────► liblinphone (C/C++)
        │ (cbindgen) │
        └────────────┘
```

Règles :

- les **ports** (traits) vivent dans `cpm-core::ports` ; `cpm-core` ne dépend que de
  serde/thiserror/chrono/uuid — aucune I/O, aucun `unsafe` ;
- chaque **adapter** implémente un port dans son propre crate (`cpm-nms`, `cpm-imap`) ;
- aucun panic ne traverse une frontière d'adapter : `Result<T, CpmError>` partout ;
- un seul point d'HTTP par adapter (centralisé dans son `http.rs`), config immutable
  passée au constructeur (pas de lecture d'env dans la lib) ;
- les ports fournis par l'hôte (`MessageStorage`, `SyncStateStore`) sont exposés en C
  via une **vtable de function pointers** dans `cpm-ffi` (cbindgen ne la génère pas seul).

## Crates

| Crate        | Rôle                                                                                                                                                                                                   | Type                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------- |
| `cpm-core`   | Modèle de données NMS/CPM + **ports** (`StoreBackend`, `MessageStorage`, `SyncStateStore`), `CpmError`, `SyncState`, mapping `objectId ↔ id local`.                                                    | domain, pur             |
| `cpm-msg`    | Port `MessageCodec` + impl CPIM (`message/CPIM`, RFC 3862) / MIME multipart ; mapping payload ↔ conversation de l'intégrateur.                                                                         | codec                   |
| `cpm-nms`    | **Adapter REST** : implémente `StoreBackend` sur REST_NetAPI_NMS (auth, boxes, dossiers, objets CRUD/bulk/payload/flags, subscriptions, notifications, strict sync). `http.rs` centralise tout l'HTTP. | adapter entrant (V1)    |
| `cpm-imap`   | **Adapter IMAP** : implémente `StoreBackend` sur `OMA-TS-CPM_Message_Store-V2_2` (créé en phase 7).                                                                                                    | adapter entrant (ph. 7) |
| `cpm-client` | Moteur de synchro **binding-agnostic** : first-time + steady-state (strict sync §6.3), orchestre `StoreBackend` + `MessageStorage` + `SyncStateStore` + `MessageCodec`. Ne stocke rien.                | orchestration           |
| `cpm-ffi`    | **Adapter C sortant** : API C pour liblinphone (cbindgen, `cdylib`/`staticlib`), vtable des ports hôte, runtime tokio global (`OnceLock`), `catch_unwind` à la frontière. Seul crate avec `unsafe`.    | adapter sortant         |

## Décisions (ADR)

- **D1 — Le binding est un adapter, pas un choix du core.** Le port `StoreBackend`
  définit les opérations du message store (dossiers, objets, payloads, flags,
  subscriptions, notifications, sync). Adapter par défaut en V1 : **REST**
  (`cpm-nms`) ; adapter IMAP (`cpm-imap`) en phase 7. La spec de base
  `OMA-TS-REST_NetAPI_NMS` est embarquée et QA'ée (2026-11-08). **Critère
  d'inversion** : un déploiement NMS nommé n'exposant que l'IMAP → l'IMAP devient
  l'adapteur par défaut.
- **D2 — Licence Apache-2.0.** Compatible GPLv3/AGPL → intégrable dans
  linphone-sdk tout en restant réutilisable ailleurs.
- **D3 — La bibliothèque ne stocke rien.** Deux ports fournis par l'hôte :
  `MessageStorage` (messages + mapping `objectId ↔ id local`) et `SyncStateStore`
  (blob `SyncState` sérialisable en JSON — `restartToken`/`lastModSeq`/curseurs —
  stocké en **une seule clé** par l'hôte, ex. SQLite Linphone). `cpm-client`
  orchestre via ces ports.
- **D4 — Workspace `crates/*`, dépendances centralisées** dans
  `[workspace.dependencies]`, MSRV 1.85, édition 2024.
- **D5 — FFI en C via cbindgen** (`cdylib` + `staticlib`). **Contrat FFI à écrire
  avant la phase 6** : runtime tokio global possédé par `cpm-ffi` via `OnceLock`
  (créé à l'init, jamais recréé par appel) ; vtable C explicite des ports hôte ;
  `catch_unwind` systématique à la frontière ; aucun panic ne traverse l'ABI.
- **D6 — JSON uniquement côté REST.** Le SCR serveur rend le JSON Mandatory ;
  le XML est Optional — non supporté en V1.
- **D7 — Chiffrement E2E hors scope V1.** La bibliothèque transporte des payloads
  **opaques** ; le chiffrement de bout en bout (E2EE RCS) est une couche applicative
  au-dessus du message store. Garde des clés et effacement/GDPR côté serveur sont du
  ressort du déploiement, à documenter côté intégration.
- **D8 — Sync « server-authoritative ».** `restartToken`/`lastModSeq` font foi ; en
  cas de conflit de flags, le serveur gagne (dernier `lastModSeq`). Les changements
  locaux sont uploadés (first-time / steady-state). La **migration d'historique**
  Linphone = first-time sync + remplissage du mapping via `MessageStorage`.
- **D9 — Publication : le code est publiable, pas les specs OMA.** Le code de
  cpm-store (Apache-2.0, œuvre originale) peut être publié en open source librement.
  En revanche les documents OMA (PDF, conversions markdown, images, fixtures
  extraits des annexes) sont sous copyright OMA — usage interne/éducatif uniquement,
  redistribution soumise à permission écrite (Use Agreement omaspecworks.org) :
  ils sont gitignorés et récupérés localement via `tools/specs_fetch.py` (voir
  `docs/specs/README.md`, section « Publication »). Deuxième condition avant toute
  intégration dans linphone-sdk : validation juridique de la compatibilité
  Apache-2.0 ↔ AGPLv3 au linkage statique (combined work, clause brevet, §13 AGPL,
  versioning ABI C) — action externe, ne bloque pas la publication du code.
- **D10 — Interop : aucun serveur NMS/CPM open-source n'existe** (recherche
  2026-11-08). Critère de conformité = annexes des specs (golden tests extraits du
  PDF) + `wiremock` ; l'interop contre un vrai serveur se fera quand un déploiement
  NMS sera nommé par l'équipe d'intégration.

## Gestion des erreurs

`cpm-core::CpmError` est l'erreur commune. Chaque crate peut l'enrichir, mais toute
erreur publique doit pouvoir se convertir en `CpmError`. Pas de panic sur des données
serveur invalides : elles deviennent `CpmError::Parse` / `CpmError::Server`. Aucune
erreur ne traverse une frontière d'adapter autrement que par `Result`.

## Synchronisation (cpm-client)

Implémentation de la **strict synchronization** (spec §5.5, §6.3), binding-agnostic :

1. **First-time sync** : download de tout l'existant via `StoreBackend` + upload du
   local manquant ; remplissage du mapping via `MessageStorage`.
2. **Steady-state sync** : subscription aux notifications + polling, traitement des
   changements via `restartToken` / `lastModSeq` (persistés via `SyncStateStore`),
   corrélation avec le cache local. En cas d'erreur irrécupérable : repli sur un
   first-time sync (spec §6.3.3.2).

## Tests

- Unitaires par module.
- Intégration : `wiremock` mocke le serveur NMS au niveau transport (endpoints
  `/nms/v1/...`), jamais les méthodes internes de l'adapter.
- Golden fixtures : exemples JSON/MIME des annexes C–H, **extraits du PDF officiel**
  (`pdftotext`).
- Conformance : chaque SCR de `docs/conformance.md` a son test.

## Dépendances

Toutes les versions sont épinglées dans `[workspace.dependencies]` du `Cargo.toml`
racine. Pas de dépendance directe hors workspace. TLS via rustls. Licences +
advisories vérifiées en CI par `cargo-deny` (`deny.toml`).

## Revue LLM council (2026-11-08)

5 conseillers + peer review anonymisée + chairman (transcription :
`reports/council-phase0-transcript.md`, visuel : `reports/council-phase0.html`,
skill `llm-council`). Validé : D2, D4, D6 ; D1 (via port/adapter) ; D3 re-scopé en
ports ; D5 avec contrat FFI.

### Zones d'ombre du council → résolution

| Zone d'ombre                                           | Résolution                                                                                                                                      | Où            |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| Clash D1 REST vs IMAP                                  | port `StoreBackend` + adapters (`cpm-nms` REST par défaut, `cpm-imap` ph. 7) ; inversion si déploiement IMAP-only nommé                         | D1, D10       |
| Qui possède l'état de synchro                          | `SyncStateStore` (blob, 1 clé hôte) + `MessageStorage` (messages/mapping) ; `cpm-client` orchestre                                              | D3            |
| Droits OMA / publication publique                      | usage interne OK, redistribution = permission écrite OMA → **code publiable**, specs/fixtures gitignorés + fetch local (`tools/specs_fetch.py`) | D9            |
| Juridique Apache-2.0 ↔ AGPLv3 au linkage               | action externe (juriste) avant intégration linphone-sdk ; repo privé entre-temps                                                                | D9            |
| Chiffrement E2E / garde des clés / GDPR                | hors scope V1 — payloads opaques, E2E = couche applicative                                                                                      | D7            |
| Mobile : taille binaire, batterie, CI NDK vs MSRV 1.85 | check en phase 6 ; MSRV ajustable si les vieux builders NDK bloquent                                                                            | roadmap ph. 6 |
| Conflits multi-appareils + migration historiques       | server-authoritative (serveur gagne), migration = first-time sync + mapping                                                                     | D8            |
| Serveur NMS / qui pilote l'intégration                 | aucun serveur NMS public ; conformité = annexes + wiremock ; déploiement à nommer par l'équipe d'intégration                                    | D10           |
