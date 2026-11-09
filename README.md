# cpm-store — client Rust pour OMA CPM (Converged Personal Messaging)

Bibliothèque client du standard **OMA CPM** pour la **sauvegarde / synchronisation
de conversations**. **Cas d'usage pilote** : l'intégration dans **Linphone**
(client SIP/RCS) — c'est le cas concret qui oriente les décisions, les tests et la
direction du projet, sans en être l'unique destination (l'API C de `cpm-ffi` reste
réutilisable par tout client C/C++).

- **Périmètre V1** : CPM Message Storage via RESTful API
  (`OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C`), bâti sur
  **OMA REST_NetAPI_NMS** (`OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C`).
- **Phase ultérieure** : binding IMAP (`OMA-TS-CPM_Message_Store-V2_2`).
- **Hors périmètre V1** : signalisation SIP/MSRP, charging, interworking.
- **Statut** : phase 0 — setup du workspace. Voir `docs/roadmap.md`.

## Démarrage rapide

```sh
cargo build --workspace
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
```

## Structure

```
crates/
├── cpm-core     ← modèle de données NMS/CPM (pur : pas d'I/O, pas d'unsafe)
├── cpm-nms      ← client REST_NetAPI_NMS (transport, auth, dossiers, objets, sync)
├── cpm-msg      ← format de message CPM (CPIM/MIME) + mapping conversation
├── cpm-client   ← moteur haut niveau backup/sync (first-time + steady-state)
└── cpm-ffi      ← API C (cbindgen, cdylib/staticlib) pour liblinphone
docs/
├── architecture.md   ← architecture et décisions (ADR)
├── specs.md          ← références normatives (+ copies locales dans docs/specs/)
├── conformance.md    ← checklist de conformance (SCR)
└── roadmap.md        ← plan par phases
```

## Documentation

- `AGENTS.md` — point d'entrée pour contribuer (y compris avec un LLM)
- `docs/architecture.md` — architecture, layering, décisions
- `docs/specs.md` — specs OMA de référence et où les trouver localement
- `docs/conformance.md` — exigences SCR suivies item par item
- `docs/roadmap.md` — phases et critères de sortie

## Licence

Apache-2.0 (voir `LICENSE`) — compatible GPLv3/AGPL, donc intégrable dans
linphone-sdk.
