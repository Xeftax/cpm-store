# Usage Vibe / Mistral — cpm-store

Généré le 2026-11-08T13:25:37.011788+00:00 — source `/Users/quentin/.vibe/logs/session` — filtre projet `cpm`

## Totaux

- sessions : **2**
- tokens prompt : **0** · completion : **0** · cached : **0** · total : **0**
- coût total (stats Vibe) : **$0.0000**
- appels LLM journalisés : **354**

## Par modèle (appels LLM journalisés, attribués au active_model de chaque session)

| modèle              | appels | input      | output  | cached     | reasoning | total      |
| ------------------- | ------ | ---------- | ------- | ---------- | --------- | ---------- |
| mistral-large-4-0-3 | 172    | 26,775,189 | 175,791 | 24,011,008 | 78,079    | 26,950,980 |
| unknown             | 134    | 4,197,420  | 45,383  | 3,749,888  | 1,126     | 4,242,803  |
| large               | 42     | 918,309    | 16,776  | 640,256    | 5,417     | 935,085    |
| glm                 | 3      | 28,800     | 9       | 14,208     | 0         | 28,809     |
| glm-flash           | 3      | 28,800     | 9       | 0          | 0         | 28,809     |

## Par session

| session  | début               | durée (s) | cwd                                     | alias               | modèle              | prompt | completion | cached | total | coût ($) |
| -------- | ------------------- | --------- | --------------------------------------- | ------------------- | ------------------- | ------ | ---------- | ------ | ----- | -------- |
| 075d2779 | 2026-11-08T12:18:32 | 135.1     | `/Users/quentin/Documents/perso/cpm_rs` | large               | large               | 0      | 0          | 0      | 0     | 0.0000   |
| 06df58af | 2026-11-08T12:22:11 | 3438.7    | `/Users/quentin/Documents/perso/cpm_rs` | mistral-large-4-0-3 | mistral-large-4-0-3 | 0      | 0          | 0      | 0     | 0.0000   |

## Rétention des données (vérifié le 2026-11-08)

- Logs de session locaux (`~/.vibe/logs/session/`) : **pas d'expiration automatique** (config `[session_logging]` = enabled/save_dir/session_prefix/generate_titles uniquement). Suppression manuelle possible via `/resume` (touche `d` x2) : à éviter tant que le monitoring est actif.
- `vibe.log` : rotation à `LOG_MAX_BYTES` (10 MiB par défaut).
- Télémétrie serveur (Mistral, `enable_telemetry = true`) : rétention consultable via `/data-retention`.
- Runs headless : `vibe -p ... --output-dir reports/vibe-export` écrit `export.json` (tokens, coût, stop reason) à chaque sortie.
- Note : les journaux unified ne contiennent pas de champ `model` par appel LLM ; ce rapport attribue chaque appel au `active_model` de la session (résolu via la config) — fiable tant qu'on ne switch pas de modèle en cours de session.
- Ce rapport (`reports/usage.json` + `usage.md`) sert de snapshot durable des agrégats.
