# Monitoring of Vibe / Mistral usage

This project is **100% monitored**: every Vibe session opened on this repository is
captured (cwd recorded in the session meta), with model, context, tokens and cost.
This page documents the data sources, the tools and the pitfalls, as verified on
2026-11-08.

## Tools

| command                                                                                                | output                    | usage                                                                                                             |
| ------------------------------------------------------------------------------------------------------ | ------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `python3 tools/dashboard.py --project cpm`                                                             | terminal                  | snapshot: active (parallel) sessions, durations, models, current/max context vs threshold, tokens, estimated cost |
| `python3 tools/dashboard.py --project cpm --watch 5`                                                   | terminal                  | real time, refreshed every 5 s (Ctrl-C to quit)                                                                   |
| `python3 tools/dashboard.py --project cpm --html reports/dashboard.html --json reports/dashboard.json` | files                     | HTML dashboard with auto-refresh (meta refresh 5 s, openable in a browser) + JSON snapshot                        |
| `python3 tools/usage_report.py --out-dir reports --project cpm`                                        | `reports/usage.{json,md}` | aggregate report: totals, per model, per session, retention                                                       |

`reports/` is versioned: durable snapshot of the aggregates.

## Data sources (in `~/.vibe/`)

- `logs/session/unified/*/meta.json` and `logs/session/session_*/meta.json`:
  id, start/end, cwd, `config.active_model`, `config.models` (list or dict
  depending on versions), `stats` (tokens + USD cost, filled at session end).
- `logs/session/unified/*/journal/*.jsonl`: one file per block; each LLM
  call has its usage in `payload.result.result.usage` (`input_tokens`,
  `output_tokens`, `cached_input_tokens`, `reasoning_tokens`, `total_tokens`).
  **There is no per-call `model` field**: each call is attributed to the
  session's `active_model`.
- `logs/session/active/*.lock.json`: live sessions (session_id, acquired_at,
  process_id).
- `config.toml`: global `auto_compact_threshold` (200000), `[[models]]` with
  alias → name/provider/price. **Never read or display `~/.vibe/.env`**.
- `experiment_eval_cache.json`: defaults pushed by the server (feature flags
  `vibe_cli_default_routing_model`, `vibe_cli_extra_models`) — useful as a
  fallback when a local entry is incomplete (e.g. the 800000 threshold of
  `mistral-large-4-0-3` → `mistral-large-4-0` on the server side, masked locally
  by an orphan entry that falls back to the global 200000).
- `vibe -p ... --output-dir DIR`: writes `export.json` (tokens, cost, stop
  reason) at each headless run exit.

## Estimated cost computation

Per call, from the journal: `(input - cached) × input_price + cached × cached_input_price + (output + reasoning) × output_price`, all /1M
(prices in $/M tokens). If the resolved model has no local price → cost `n/a`
(this is the case of the orphan alias `mistral-large-4-0-3`; the reliable cost comes
with `stats.session_cost` when the session closes).

## Retention (verified on 2026-11-08)

- Local session logs: **no automatic expiration** found (config
  `[session_logging]` = enabled/save_dir/session_prefix/generate_titles
  only). Manual deletion is possible via `/resume` (`d` key x2):
  **do not do it** while monitoring is active.
- `vibe.log`: rotation at `LOG_MAX_BYTES` (10 MiB default).
- Mistral server telemetry (`enable_telemetry = true`): retention viewable
  through `/data-retention` in Vibe.

## Verified pitfall: model alias vs context window

- Local config: `active_model = ""`; alias `large` → `mistral-large-4`
  (explicit auto_compact_threshold 200000); orphan alias
  `mistral-large-4-0-3` (just `thinking="high"`, no name/price/threshold →
  inherits the global 200000, and the name sent to the API is the alias itself).
- Server default (A/B test `ml408-rollout-default-cli-ab-test`):
  `mistral-large-4-0-3` → name `mistral-large-4-0`, `auto_compact_threshold: 800000`.
- Consequence: a session started with the `mistral-large-4-0-3` alias hits the
  orphan local entry and compacts at **200k**, not 800k. The dashboard
  displays the effective per-session threshold to spot this. To target 800k:
  give the local entry a `name` + `auto_compact_threshold = 800000`, or
  raise the `large` alias threshold.
