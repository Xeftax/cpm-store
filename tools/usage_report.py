#!/usr/bin/env python3
"""Rapport d'usage Vibe / modèles Mistral pour ce projet (monitoring 100%).

Sources (VIBE_HOME, défaut ~/.vibe) :
- logs/session/session_*/meta.json        -> stats session (tokens, coût USD), start/end, cwd
- logs/session/unified/*/meta.json        -> config de session (active_model, modèles, prix)
- logs/session/unified/*/journal/*.jsonl  -> usage par appel LLM (payload.result.result.usage)
                                             (pas de champ "model" par appel : on attribue
                                             chaque appel au active_model de la session)

Sortie : <out-dir>/usage.json (brut) + <out-dir>/usage.md (rapport lisible).

Usage :
    python3 tools/usage_report.py                          # tout l'historique
    python3 tools/usage_report.py --project cpm            # sessions dont le cwd contient "cpm"
    python3 tools/usage_report.py --since 2026-11-01 --out-dir reports

Rétention (vérifié le 2026-11-08) : pas d'expiration automatique des logs de
session (config [session_logging] : enabled/save_dir/session_prefix/generate_titles
seulement) ; vibe.log tourne à LOG_MAX_BYTES (10 MiB défaut) ; suppression manuelle
possible via /resume (touche d x2) — à éviter tant que le monitoring est actif ;
rétention serveur Mistral via /data-retention ; runs headless : export.json via
--output-dir. Ce script snapshot les agrégats dans reports/.
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

USAGE_KEYS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "total_tokens")


def resolve_models(cfg: dict[str, Any]) -> dict[str, Any]:
    """Normalise la config des modèles en alias -> entry.

    `config.models` peut être une liste de dicts (avec 'alias') ou un dict alias -> entry.
    Chaque entrée reçoit un 'name' par défaut égal à l'alias.
    """
    out: dict[str, Any] = {}
    models = (cfg or {}).get("models")
    if isinstance(models, list):
        for mo in models:
            if isinstance(mo, dict) and mo.get("alias"):
                out[mo["alias"]] = mo
    elif isinstance(models, dict):
        for alias, entry in models.items():
            if isinstance(entry, dict):
                mo = dict(entry)
                mo.setdefault("alias", alias)
                out[alias] = mo
    for alias, mo in out.items():
        mo.setdefault("name", alias)
    return out


def find_usage(obj: object, found: dict[str, float]) -> None:
    """Extrait récursivement les compteurs d'usage d'un objet JSON (journal)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in USAGE_KEYS and isinstance(v, (int, float)):
                found[k] = found.get(k, 0) + v
            else:
                find_usage(v, found)
    elif isinstance(obj, list):
        for v in obj:
            find_usage(v, found)


def parse_iso(s: str) -> datetime | None:
    """Convertit une chaîne ISO 8601 en datetime (UTC-compatible), None si illisible."""
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def load_session_meta(path: Path) -> dict[str, Any] | None:
    """Lit un meta.json de session ; None si le fichier est illisible ou vide."""
    try:
        return cast("dict[str, Any] | None", json.loads(path.read_text()))
    except Exception:
        return None


def load_sessions_by_id(session_root: Path) -> dict[str, Any]:
    """Fusionne session_*/meta.json et unified/*/meta.json (dédup par session_id)."""
    by_id: dict[str, Any] = {}
    for meta_path in sorted(session_root.glob("session_*/meta.json")) + sorted(
        (session_root / "unified").glob("*/meta.json")
    ):
        meta = load_session_meta(meta_path)
        if not meta:
            continue
        sid = meta.get("session_id") or meta_path.parent.name
        cur = by_id.get(sid)
        # garder la version la plus riche (celle qui a des stats)
        if cur is None or (not cur.get("stats") and meta.get("stats")):
            meta["_dir"] = meta_path.parent.name
            by_id[sid] = meta
    return by_id


def session_rows(by_id: dict[str, Any], project: str | None, since: datetime | None) -> list[dict[str, Any]]:
    """Construit une ligne de rapport par session, filtrée par projet et par date."""
    sessions: list[dict[str, Any]] = []
    for sid, meta in by_id.items():
        start = parse_iso(meta.get("start_time") or "")
        if since and start and start < since:
            continue
        cwd = (meta.get("environment") or {}).get("working_directory") or meta.get("cwd") or ""
        if project and project not in cwd:
            continue
        stats = meta.get("stats") or {}
        cfg = meta.get("config") or {}
        models = resolve_models(cfg)
        active = cfg.get("active_model") or ""
        active_info = models.get(active, {})
        end = parse_iso(meta.get("end_time") or "")
        dur = (end - start).total_seconds() if start and end else None
        sessions.append(
            {
                "session_id": sid,
                "dir": meta.get("_dir"),
                "start": meta.get("start_time"),
                "duration_s": round(dur, 1) if dur is not None else None,
                "cwd": cwd,
                "active_model_alias": active,
                "model_name": active_info.get("name") or active,
                "provider": active_info.get("provider"),
                "input_price": active_info.get("input_price"),
                "output_price": active_info.get("output_price"),
                "prompt_tokens": stats.get("session_prompt_tokens"),
                "completion_tokens": stats.get("session_completion_tokens"),
                "cached_tokens": stats.get("session_cached_tokens"),
                "total_tokens": stats.get("session_total_llm_tokens"),
                "cost_usd": stats.get("session_cost"),
            }
        )
    sessions.sort(key=lambda s: s["start"] or "")
    return sessions


def llm_call_usage(session_root: Path) -> tuple[dict[str, dict[str, Any]], int]:
    """Usage par appel LLM depuis les journaux unified, attribuée au active_model de la session."""
    per_model: dict[str, dict[str, Any]] = {}
    n_calls = 0
    for udir in sorted((session_root / "unified").glob("*/journal/*.jsonl")):
        session_dir = udir.parent.parent
        meta = load_session_meta(session_dir / "meta.json") or {}
        cfg = meta.get("config") or {}
        models = resolve_models(cfg)
        active = cfg.get("active_model") or ""
        model_name = models.get(active, {}).get("name") or active or "unknown"
        for line in udir.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or "input_tokens" not in stripped:
                continue
            try:
                obj = json.loads(stripped)
            except Exception:
                logger.debug("ligne de journal illisible dans %s", udir, exc_info=True)
                continue
            found: dict[str, float] = {}
            find_usage(obj.get("payload", obj), found)
            if "input_tokens" not in found:
                continue
            n_calls += 1
            agg = per_model.setdefault(model_name, dict.fromkeys(USAGE_KEYS, 0) | {"calls": 0})
            agg["calls"] += 1
            for k in USAGE_KEYS:
                agg[k] += found.get(k, 0)
    return per_model, n_calls


def totals(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrège les totaux de tokens et de coût sur les sessions."""
    return {
        "sessions": len(sessions),
        "prompt_tokens": sum(s["prompt_tokens"] or 0 for s in sessions),
        "completion_tokens": sum(s["completion_tokens"] or 0 for s in sessions),
        "cached_tokens": sum(s["cached_tokens"] or 0 for s in sessions),
        "total_tokens": sum(s["total_tokens"] or 0 for s in sessions),
        "cost_usd": round(sum(s["cost_usd"] or 0 for s in sessions), 6),
    }


def markdown_report(
    data: dict[str, Any], sessions: list[dict[str, Any]], per_model: dict[str, dict[str, Any]], n_calls: int
) -> str:
    """Construit le rapport markdown (usage.md) à partir des agrégats."""
    vibe_home = data["vibe_home"]
    lines: list[str] = []
    lines.append("# Usage Vibe / Mistral — cpm-store")
    lines.append("")
    lines.append(
        f"Généré le {data['generated_at']} — source `{vibe_home}/logs/session`"
        + (f" — filtre projet `{data['project_filter']}`" if data["project_filter"] else " — toutes sessions")
    )
    lines.append("")
    lines.append("## Totaux")
    lines.append("")
    t = data["totals"]
    lines.append(f"- sessions : **{t['sessions']}**")
    lines.append(
        f"- tokens prompt : **{t['prompt_tokens']:,}** · completion : **{t['completion_tokens']:,}**"
        f" · cached : **{t['cached_tokens']:,}** · total : **{t['total_tokens']:,}**"
    )
    lines.append(f"- coût total (stats Vibe) : **${t['cost_usd']:.4f}**")
    lines.append(f"- appels LLM journalisés : **{n_calls}**")
    lines.append("")
    lines.append("## Par modèle (appels LLM journalisés, attribués au active_model de chaque session)")
    lines.append("")
    lines.append("| modèle | appels | input | output | cached | reasoning | total |")
    lines.append("|---|---|---|---|---|---|---|")
    for m, a in sorted(per_model.items(), key=lambda kv: -kv[1]["total_tokens"]):
        lines.append(
            f"| {m} | {a['calls']} | {a['input_tokens']:,} | {a['output_tokens']:,} | "
            f"{a['cached_input_tokens']:,} | {a['reasoning_tokens']:,} | {a['total_tokens']:,} |"
        )
    lines.append("")
    lines.append("## Par session")
    lines.append("")
    lines.append(
        "| session | début | durée (s) | cwd | alias | modèle | prompt | completion | cached | total | coût ($) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in sessions:
        sid = (s["session_id"] or "")[:8]
        lines.append(
            f"| {sid} | {s['start'][:19] if s['start'] else '?'} | {s['duration_s']} | `{s['cwd']}` | "
            f"{s['active_model_alias']} | {s['model_name']} | "
            f"{s['prompt_tokens'] or 0:,} | {s['completion_tokens'] or 0:,} | {s['cached_tokens'] or 0:,} | "
            f"{s['total_tokens'] or 0:,} | {(s['cost_usd'] or 0):.4f} |"
        )
    lines.append("")
    lines.append("## Rétention des données (vérifié le 2026-11-08)")
    lines.append("")
    lines.append(
        "- Logs de session locaux (`~/.vibe/logs/session/`) : **pas d'expiration automatique** "
        "(config `[session_logging]` = enabled/save_dir/session_prefix/generate_titles uniquement). "
        "Suppression manuelle possible via `/resume` (touche `d` x2) : à éviter tant que le monitoring est actif."
    )
    lines.append("- `vibe.log` : rotation à `LOG_MAX_BYTES` (10 MiB par défaut).")
    lines.append(
        "- Télémétrie serveur (Mistral, `enable_telemetry = true`) : rétention consultable via `/data-retention`."
    )
    lines.append(
        "- Runs headless : `vibe -p ... --output-dir reports/vibe-export` écrit `export.json` "
        "(tokens, coût, stop reason) à chaque sortie."
    )
    lines.append(
        "- Note : les journaux unified ne contiennent pas de champ `model` par appel LLM ; ce rapport attribue "
        "chaque appel au `active_model` de la session (résolu via la config) — fiable tant qu'on ne switch pas "
        "de modèle en cours de session."
    )
    lines.append("- Ce rapport (`reports/usage.json` + `usage.md`) sert de snapshot durable des agrégats.")
    return "\n".join(lines) + "\n"


def main() -> int:
    """Point d'entrée : lit les logs Vibe et écrit usage.json + usage.md dans --out-dir."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--vibe-home", default=str(Path.home() / ".vibe"))
    ap.add_argument("--out-dir", default="reports")
    ap.add_argument("--project", default=None, help="filtre: sessions dont le cwd contient cette chaîne")
    ap.add_argument("--since", default=None, help="date ISO YYYY-MM-DD")
    args = ap.parse_args()

    vibe_home = Path(args.vibe_home)
    session_root = vibe_home / "logs" / "session"
    since = datetime.fromisoformat(args.since).replace(tzinfo=UTC) if args.since else None

    by_id = load_sessions_by_id(session_root)
    sessions = session_rows(by_id, args.project, since)
    per_model, n_calls = llm_call_usage(session_root)
    t = totals(sessions)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "vibe_home": str(vibe_home),
        "project_filter": args.project,
        "since": args.since,
        "sessions": sessions,
        "per_model_llm_calls": per_model,
        "llm_calls_count": n_calls,
        "totals": t,
    }
    (out_dir / "usage.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "usage.md").write_text(markdown_report(data, sessions, per_model, n_calls), encoding="utf-8")

    print(
        f"OK: {out_dir}/usage.json + usage.md — {len(sessions)} sessions, {n_calls} appels LLM, "
        f"{t['total_tokens']:,} tokens, ${t['cost_usd']:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
