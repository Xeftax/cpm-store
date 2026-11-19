# AGENTS.md — cpm-store

Point d'entrée pour tout agent (humain ou LLM) travaillant sur ce dépôt.
Lire ce fichier **avant toute modification**, puis `docs/architecture.md` et
`docs/specs.md`.

## Objectif

Bibliothèque Rust cliente du standard **OMA CPM** (Converged Personal Messaging)
pour la **sauvegarde / synchronisation de conversations**. **Cas d'usage pilote :
Linphone** (client SIP/RCS) — cas concret qui oriente décisions, tests et direction ;
la bibliothèque elle-même reste générique (API C réutilisable par tout client C/C++).

- Périmètre V1 : CPM Message Storage via RESTful API (OMA REST_NetAPI_NMS).
- Hors périmètre V1 : signalisation SIP/MSRP, charging, interworking, binding IMAP
  (IMAP prévu en phase ultérieure, voir `docs/roadmap.md`).

## Langue et style

- Réponses à l'utilisateur : **français**. Code, identifiants, commentaires :
  **anglais**.
- Docs du dépôt (README, `docs/`, `AGENTS.md`) : français, termes techniques
  anglais conservés tels quels.
- Pas d'emoji, style direct et factuel.

## Commandes

```sh
cargo build --workspace
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings   # zéro warning toléré
cargo fmt --all -- --check
cargo doc --workspace --no-deps
```

La CI (`.github/workflows/ci.yml`) rejoue exactement ces commandes.
MSRV : **1.85** (`rust-version` du workspace), édition **2024**.

## Architecture et layering

Voir `docs/architecture.md`. Règles absolues :

```
cpm-ffi → cpm-client → { cpm-nms | cpm-imap (ph. 7) } → ports de cpm-core
                    └→ cpm-msg → cpm-core
```

Architecture **ports & adapters** (pattern doc-station) :

- les **ports** = traits dans `cpm-core::ports` (`StoreBackend`, `MessageStorage`,
  `SyncStateStore`) ; `cpm-core` est **pur** : aucune I/O, `#![forbid(unsafe_code)]` ;
- les **adapters** = un crate par implémentation (`cpm-nms` = REST, `cpm-imap` = IMAP) ;
- `Result<T, CpmError>` à chaque frontière d'adapter, aucun panic ne la traverse ;
- `unsafe` est interdit dans tout le workspace **sauf** `cpm-ffi` (FFI C pour
  liblinphone) ;
- Erreurs : `thiserror`. Jamais d'`unwrap`/`expect` hors tests.

## Tests et conformance

- Tests unitaires par module + tests d'intégration avec `wiremock` (serveur NMS
  mocké).
- Fixtures "golden" tirées des exemples des annexes des specs (`docs/specs/`).
- Chaque exigence cochée dans `docs/conformance.md` (SCR) doit être couverte par
  un test.

## Spécifications

Lire `docs/specs.md` avant toute implémentation. Citer le **numéro de section**
de la spec dans les commentaires de code et les messages de commit lorsqu'on
implémente une procédure normative. Ne jamais inventer une section de spec : si
un point n'est pas couvert par la spec, le noter explicitement dans la PR.

## Git

- Préférer **rebase** à merge ; combiner les PRs par **retarget** plutôt que
  d'en ouvrir plusieurs.
- Commits conventionnels en anglais (`feat:`, `fix:`, `docs:`, `test:`,
  `refactor:`, `chore:`).
- Pas d'emoji dans les commits.
- **Jamais de contournement de hooks pre-commit** (`git commit --no-verify` ou
  équivalent) sans **autorisation explicite par chat** de l'utilisateur : un approval
  de tool (smart-approve) n'est pas une autorisation. Si un hook échoue, on fixe le
  hook à la source, pas le commit (ex. 2026-11-17 : cargo-deny bloquait sur
  RUSTSEC-2026-0543, chrono unmaintained, migration vers jiff, commit c8f0200).
  Tout contournement exceptionnellement autorisé doit être déclaré dans le message de
  commit (trailer `Hooks-Bypassed: <hook> — <raison>`) : visible en revue, bloqué par
  le job CI `commit-hygiene` (`scripts/ci/check-commit-hygiene.sh`). Owner du
  domaine : `.vibe/skills/git-workflow-owner/SKILL.md`.

## Travailler avec un LLM sur ce dépôt

1. Lire `AGENTS.md`, puis `docs/architecture.md`, `docs/specs.md` et
   `docs/workflow.md` (stratégie de développement, owner agents, points de
   synchro humain).
2. Avancer phase par phase (`docs/roadmap.md`) — ne pas sauter de phase, ne pas
   commencer une phase avant que la précédente soit verte (tests + clippy).
3. Toute PR qui couvre une SCR met à jour `docs/conformance.md`.
4. Tests obligatoires avec chaque changement de comportement.
5. Délégation subagents (Vibe) : toujours spawner avec un `config_name` —
   `explore-flash` (glm-flash, read-only) pour lire/explorer le code,
   `plan-exec` (glm-flash, write autorisé) pour exécuter un plan étape par étape.
   Ne jamais spawner un subagent sans `config_name` pour du travail délégué.

## Monitoring de l'usage Vibe / Mistral (100% monitoré)

Ce projet est suivi intégralement côté usage des modèles : sessions, modèles,
contextes, tokens, coûts. Voir `docs/monitoring.md`.

```sh
python3 tools/dashboard.py --project cpm                          # snapshot terminal
python3 tools/dashboard.py --project cpm --watch 5                # temps réel (Ctrl-C)
python3 tools/dashboard.py --project cpm --html reports/dashboard.html --json reports/dashboard.json
python3 tools/usage_report.py --out-dir reports --project cpm     # rapport agrégé (tokens, coût)
```

- `tools/dashboard.py` lit `~/.vibe/logs/session` en direct (meta.json, journaux
  `unified/*/journal/*.jsonl`, locks `active/`) + `config.toml` +
  `experiment_eval_cache.json`. Ne lit jamais `~/.vibe/.env`.
- `reports/` (dashboard.html/json, usage.json/md) est versionné : c'est le
  snapshot durable, indépendant de la rétention des logs Vibe.
- Ne pas supprimer les sessions Vibe via `/resume` (touche `d` x2) tant que le
  monitoring est actif : les logs locaux n'ont pas d'expiration automatique.

## Licence

Apache-2.0 (`LICENSE`) — choisie pour sa compatibilité GPLv3/AGPL, afin que la
bibliothèque soit intégrable dans linphone-sdk.
