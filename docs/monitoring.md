# Monitoring de l'usage Vibe / Mistral

Le projet est **100% monitoré** : chaque session Vibe ouverte sur ce dépôt est
capturée (cwd enregistré dans les meta de session), avec modèle, contexte,
tokens et coût. Cette page documente les sources de données, les outils et les
pièges vérifiés le 2026-11-08.

## Outils

| commande | sortie | usage |
|---|---|---|
| `python3 tools/dashboard.py --project cpm` | terminal | snapshot : sessions actives (parallèles), durées, modèles, contexte courant/max vs seuil, tokens, coût estimé |
| `python3 tools/dashboard.py --project cpm --watch 5` | terminal | temps réel, rafraîchi toutes les 5 s (Ctrl-C pour quitter) |
| `python3 tools/dashboard.py --project cpm --html reports/dashboard.html --json reports/dashboard.json` | fichiers | dashboard HTML auto-refresh (meta refresh 5 s, ouvrable dans un navigateur) + snapshot JSON |
| `python3 tools/usage_report.py --out-dir reports --project cpm` | `reports/usage.{json,md}` | rapport agrégé : totaux, par modèle, par session, rétention |

`reports/` est versionné : snapshot durable des agrégats.

## Sources de données (dans `~/.vibe/`)

- `logs/session/unified/*/meta.json` et `logs/session/session_*/meta.json` :
  id, start/end, cwd, `config.active_model`, `config.models` (liste ou dict
  selon les versions), `stats` (tokens + coût USD, renseigné à la fin de session).
- `logs/session/unified/*/journal/*.jsonl` : un fichier par bloc ; chaque appel
  LLM a son usage dans `payload.result.result.usage` (`input_tokens`,
  `output_tokens`, `cached_input_tokens`, `reasoning_tokens`, `total_tokens`).
  **Il n'y a pas de champ `model` par appel** : on attribue chaque appel au
  `active_model` de la session.
- `logs/session/active/*.lock.json` : sessions vivantes (session_id, acquired_at,
  process_id).
- `config.toml` : `auto_compact_threshold` global (200000), `[[models]]` avec
  alias → name/provider/prix. **Ne jamais lire ni afficher `~/.vibe/.env`**.
- `experiment_eval_cache.json` : defaults poussés par le serveur (feature flags
  `vibe_cli_default_routing_model`, `vibe_cli_extra_models`) — utile comme
  fallback quand une entrée locale est incomplète (ex. seuil 800000 de
  `mistral-large-4-0-3` → `mistral-large-4-0` côté serveur, masqué localement
  par une entrée orpheline qui retombe sur le global 200000).
- `vibe -p ... --output-dir DIR` : écrit `export.json` (tokens, coût, stop
  reason) à chaque sortie de run headless.

## Calcul du coût estimé

Par appel, depuis le journal : `(input - cached) × input_price + cached ×
cached_input_price + (output + reasoning) × output_price`, le tout /1M
(prix en $/M tokens). Si le modèle résolu n'a pas de prix local → coût `n/a`
(c'est le cas de l'alias orphelin `mistral-large-4-0-3` ; le coût fiable arrive
avec `stats.session_cost` à la clôture de session).

## Rétention (vérifié le 2026-11-08)

- Logs de session locaux : **pas d'expiration automatique** trouvée (config
  `[session_logging]` = enabled/save_dir/session_prefix/generate_titles
  uniquement). Suppression manuelle possible via `/resume` (touche `d` x2) :
  **ne pas le faire** tant que le monitoring est actif.
- `vibe.log` : rotation à `LOG_MAX_BYTES` (10 MiB par défaut).
- Télémétrie serveur Mistral (`enable_telemetry = true`) : rétention consultable
  via `/data-retention` dans Vibe.

## Piège vérifié : alias modèle vs context window

- Config locale : `active_model = ""` ; alias `large` → `mistral-large-4`
  (auto_compact_threshold 200000 explicite) ; alias orphelin
  `mistral-large-4-0-3` (juste `thinking="high"`, pas de name/prix/seuil →
  hérite du global 200000, et le nom envoyé à l'API est l'alias lui-même).
- Défaut serveur (A/B test `ml408-rollout-default-cli-ab-test`) :
  `mistral-large-4-0-3` → name `mistral-large-4-0`, `auto_compact_threshold:
  800000`.
- Conséquence : une session lancée avec l'alias `mistral-large-4-0-3` tombe sur
  l'entrée locale orpheline et compacte à **200k**, pas 800k. Le dashboard
  affiche le seuil effectif par session pour le repérer. Pour viser 800k :
  donner un `name` + `auto_compact_threshold = 800000` à l'entrée locale, ou
  relever le seuil de l'alias `large`.
