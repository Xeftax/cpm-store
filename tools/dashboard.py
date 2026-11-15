#!/usr/bin/env python3
"""Dashboard temps réel de l'usage Vibe / Mistral (monitoring du projet cpm-store).

Lit en direct les logs de ~/.vibe/logs/session et affiche :
- sessions actives maintenant (parallèles), temps écoulé, dernière activité
- modèle utilisé par session (alias -> name résolu, prix, seuil d'auto-compact)
- taille du contexte (dernier input_tokens observé dans le journal, max, % du seuil)
- tokens consommés et coût estimé par session (prix /1M tokens du modèle résolu)
- totaux globaux

Sources :
- ~/.vibe/config.toml (tomllib) : auto_compact_threshold global, [[models]] (prix)
- ~/.vibe/experiment_eval_cache.json : defaults serveur (routing model, extra models,
  auto_compact_threshold / max_context_length par modèle) — fallback si l'entrée
  locale est incomplète
- logs/session/unified/*/meta.json + session_*/meta.json : sessions, config, stats
- logs/session/unified/*/journal/*.jsonl : usage par appel LLM (payload...usage)
- logs/session/active/*.lock.json : sessions vivantes (locks)

Usage :
    python3 tools/dashboard.py                          # snapshot terminal
    python3 tools/dashboard.py --watch 5                # rafraîchit toutes les 5 s
    python3 tools/dashboard.py --project cpm            # filtre cwd
    python3 tools/dashboard.py --html reports/dashboard.html --json reports/dashboard.json
    python3 tools/dashboard.py --watch 5 --html reports/dashboard.html   # HTML auto-refresh (meta refresh) + terminal

Ne lit jamais ~/.vibe/.env et n'affiche aucune clé.
"""

import argparse
import contextlib
import json
import logging
import sys
import time
import tomllib
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

USAGE_KEYS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "total_tokens")
ACTIVE_WINDOW_S = 300  # une session est "vivante" si activité < 5 min


def parse_iso(s: str) -> datetime | None:
    """Convertit une chaîne ISO 8601 en datetime, None si illisible."""
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def load_config(vibe_home: Path) -> tuple[Any, dict[str, Any]]:
    """config.toml -> (global_threshold, models_by_alias). Ne touche pas aux clés API."""
    threshold: Any = None
    models: dict[str, Any] = {}
    p = vibe_home / "config.toml"
    if p.exists():
        try:
            cfg = tomllib.loads(p.read_text())
            threshold = cfg.get("auto_compact_threshold")
            for mo in cfg.get("models", []) or []:
                if isinstance(mo, dict) and mo.get("alias"):
                    models[mo["alias"]] = mo
        except Exception:
            logger.debug("config.toml illisible: %s", p, exc_info=True)
    return threshold, models


def load_server_defaults(vibe_home: Path) -> dict[str, Any]:
    """experiment_eval_cache.json -> model configs poussés par le serveur (par alias)."""
    out: dict[str, Any] = {}
    p = vibe_home / "experiment_eval_cache.json"
    if not p.exists():
        return out
    try:
        cache = json.loads(p.read_text())
    except Exception:
        return out
    for entry in cache.values():
        feats = ((entry or {}).get("payload") or {}).get("features") or {}
        for fname in ("vibe_cli_default_routing_model", "vibe_cli_extra_models"):
            f = feats.get(fname) or {}
            dv = f.get("defaultValue") or {}
            mcs = []
            if isinstance(dv, dict):
                if "model_config" in dv:
                    mcs.append(dv["model_config"])
                mcs.extend(dv.get("models", []) or [])
            for mc in mcs:
                if isinstance(mc, dict) and mc.get("alias"):
                    out[mc["alias"]] = mc
    return out


def resolve_model(
    alias: str, local_models: dict[str, Any], server_models: dict[str, Any], global_threshold: int | None
) -> dict[str, Any]:
    """Résout un alias -> dict(name, prices, threshold, source)."""
    src = None
    mo = local_models.get(alias)
    if mo:
        src = "local"
    else:
        mo = server_models.get(alias)
        src = "server-default"
    mo = dict(mo or {})
    mo.setdefault("name", alias)
    thr = mo.get("auto_compact_threshold", global_threshold)
    return {
        "alias": alias,
        "name": mo.get("name") or alias,
        "display": mo.get("display_name") or mo.get("name") or alias,
        "input_price": mo.get("input_price"),
        "output_price": mo.get("output_price"),
        "cached_input_price": mo.get("cached_input_price") or mo.get("cached_price"),
        "auto_compact_threshold": thr,
        "max_context_length": mo.get("max_context_length"),
        "source": src or "alias-brut",
    }


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


def journal_stats(journal_dir: Path) -> dict[str, Any]:
    """Agrège l'usage LLM d'un journal unified.

    Retourne aussi le dernier input_tokens (= taille de contexte courante) et le max observé.
    """
    agg: dict[str, float] = dict.fromkeys(USAGE_KEYS, 0.0)
    calls = 0
    last_input = 0.0
    max_input = 0.0
    last_mtime = 0.0
    for jf in sorted(journal_dir.glob("*.jsonl")):
        last_mtime = max(last_mtime, jf.stat().st_mtime)
        for line in jf.read_text(errors="replace").splitlines():
            if "input_tokens" not in line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                logger.debug("ligne de journal illisible dans %s", jf, exc_info=True)
                continue
            f: dict[str, float] = {}
            find_usage(obj.get("payload", obj), f)
            if "input_tokens" not in f:
                continue
            calls += 1
            for k in USAGE_KEYS:
                agg[k] += f.get(k, 0)
            last_input = f.get("input_tokens", 0)
            max_input = max(max_input, last_input)
    return {"calls": calls, "usage": agg, "last_input": last_input, "max_input": max_input, "last_mtime": last_mtime}


def est_cost(usage: dict[str, float], model: dict[str, Any]) -> float | None:
    """Estime le coût USD d'un usage à partir des prix du modèle ; None si prix inconnus."""
    ip, op, cp = model["input_price"], model["output_price"], model["cached_input_price"]
    if ip is None or op is None:
        return None
    cp = cp if cp is not None else ip
    inp = usage["input_tokens"]
    cached = min(usage["cached_input_tokens"], inp)
    return float(
        (inp - cached) * ip / 1e6 + cached * cp / 1e6 + (usage["output_tokens"] + usage["reasoning_tokens"]) * op / 1e6
    )


def collect(vibe_home: Path, project: str | None = None) -> tuple[list[dict[str, Any]], int | None]:
    """Récupère les sessions (métas, journaux, locks) et résout le modèle de chacune."""
    session_root = vibe_home / "logs" / "session"
    global_threshold, local_models = load_config(vibe_home)
    server_models = load_server_defaults(vibe_home)

    # locks = sessions vivantes
    active_locks: dict[str, Any] = {}
    for lf in (session_root / "active").glob("*.lock.json"):
        try:
            d = json.loads(lf.read_text())
            active_locks[d.get("session_id")] = d.get("acquired_at")
        except Exception:
            logger.debug("lock illisible: %s", lf, exc_info=True)

    by_id: dict[str, Any] = {}
    for meta_path in sorted(session_root.glob("session_*/meta.json")) + sorted(
        (session_root / "unified").glob("*/meta.json")
    ):
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            logger.debug("meta illisible: %s", meta_path, exc_info=True)
            continue
        sid = meta.get("session_id") or meta_path.parent.name
        cur = by_id.get(sid)
        if cur is None or (not cur.get("stats") and meta.get("stats")):
            meta["_dir"] = meta_path.parent.name
            by_id[sid] = meta

    now = datetime.now(UTC)
    sessions: list[dict[str, Any]] = []
    for sid, meta in by_id.items():
        cfg = meta.get("config") or {}
        cwd = (meta.get("environment") or {}).get("working_directory") or ""
        if project and project not in cwd:
            continue
        alias = cfg.get("active_model") or ""
        model = resolve_model(alias, local_models, server_models, global_threshold)
        jdir = session_root / "unified" / sid / "journal"
        js: dict[str, Any]
        if jdir.exists():
            js = journal_stats(jdir)
        else:
            js = {
                "calls": 0,
                "usage": dict.fromkeys(USAGE_KEYS, 0.0),
                "last_input": 0.0,
                "max_input": 0.0,
                "last_mtime": 0.0,
            }
        stats = meta.get("stats") or {}
        start = parse_iso(meta.get("start_time") or "")
        end = parse_iso(meta.get("end_time") or "")
        live = sid in active_locks or (
            end is None and js["last_mtime"] and (time.time() - js["last_mtime"]) < ACTIVE_WINDOW_S
        )
        if end is None and start is not None and live:
            end = None
        elapsed = ((end or now) - start).total_seconds() if start else None
        cost = est_cost(js["usage"], model)
        sessions.append(
            {
                "id": sid,
                "short": sid[:8],
                "cwd": cwd,
                "start": meta.get("start_time"),
                "end": meta.get("end_time"),
                "elapsed_s": round(elapsed) if elapsed is not None else None,
                "live": live,
                "lock_since": active_locks.get(sid),
                "model": model,
                "calls": js["calls"],
                "usage": js["usage"],
                "ctx_now": js["last_input"],
                "ctx_max": js["max_input"],
                "last_activity": js["last_mtime"],
                "cost_est": cost,
                "cost_stats": stats.get("session_cost"),
                "stats_total": stats.get("session_total_llm_tokens"),
            }
        )
    sessions.sort(key=lambda s: s["start"] or "")
    return sessions, global_threshold


def fmt_dur(s: float | None) -> str:
    """Convertit une durée en secondes en texte (ex. 1h05m03s, 5m03s)."""
    if s is None:
        return "-"
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{sec:02d}s" if h else f"{m}m{sec:02d}s"


def fmt_ts(ts: str | None) -> str:
    """Convertit un timestamp ISO en dd/mm HH:MM:SS (tronqué à 19 car. sinon)."""
    if not ts:
        return "-"
    d = parse_iso(ts)
    return d.strftime("%d/%m %H:%M:%S") if d else ts[:19]


def bar(frac: float, width: int = 18) -> str:
    """Barre de progression ASCII de `width` caractères pour une fraction entre 0 et 1."""
    frac = max(0.0, min(1.0, frac))
    n = int(frac * width)
    return "#" * n + "-" * (width - n)


def render_text(sessions: list[dict[str, Any]], global_threshold: int | None, project: str | None) -> str:
    """Rendu terminal du dashboard (texte)."""
    now = datetime.now(UTC)
    out: list[str] = []
    out.append(
        f"VIBE USAGE DASHBOARD — {now.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        + (f" — filtre cwd: {project}" if project else "")
    )
    live = [s for s in sessions if s["live"]]
    out.append(
        f"sessions: {len(sessions)} total, {len(live)} active(s) maintenant (parallèles)"
        f" — seuil auto-compact global: {global_threshold}"
    )
    out.append("")
    if live:
        out.append("== ACTIVES MAINTENANT ==")
        out.append(
            f"{'session':10} {'depuis':17} {'durée':10} {'modèle':28} {'contexte':>10} {'seuil':>8} {'util':>5}  cwd"
        )
        for s in live:
            m = s["model"]
            thr = m["auto_compact_threshold"]
            frac = s["ctx_now"] / thr if thr else 0
            out.append(
                f"{s['short']:10} {fmt_ts(s['start']):17} {fmt_dur(s['elapsed_s']):10} "
                f"{(m['alias'] + ' -> ' + m['name'])[:28]:28} {s['ctx_now']:>10,} {thr or '-':>8} "
                f"{bar(frac)} {s['cwd']}"
            )
        out.append("")
    out.append("== SESSIONS ==")
    out.append(
        f"{'session':10} {'début':17} {'durée':10} {'état':7} {'modèle (alias -> name)':34} "
        f"{'ctx now':>9} {'ctx max':>9} {'appels':>6} {'total tok':>11} {'coût est.':>9}  cwd"
    )
    for s in sessions:
        m = s["model"]
        state = "LIVE" if s["live"] else "fin"
        cost = (
            f"${s['cost_est']:.4f}"
            if s["cost_est"] is not None
            else (f"${s['cost_stats']:.4f}" if s["cost_stats"] is not None else "n/a")
        )
        tot = s["stats_total"] or s["usage"]["total_tokens"]
        out.append(
            f"{s['short']:10} {fmt_ts(s['start']):17} {fmt_dur(s['elapsed_s']):10} {state:7} "
            f"{(m['alias'] + ' -> ' + m['name'])[:34]:34} {s['ctx_now']:>9,} {s['ctx_max']:>9,} "
            f"{s['calls']:>6} {tot:>11,} {cost:>9}  {s['cwd']}"
        )
    tot_tok = sum(s["usage"]["total_tokens"] for s in sessions)
    tot_cost = sum(s["cost_est"] or 0 for s in sessions)
    n_calls = sum(s["calls"] for s in sessions)
    out.append("")
    out.append(
        f"TOTAUX: {len(sessions)} sessions, {n_calls} appels LLM, {tot_tok:,} tokens, coût estimé ${tot_cost:.4f}"
    )
    per_model: dict[str, dict[str, Any]] = {}
    for s in sessions:
        a = per_model.setdefault(s["model"]["name"], {"calls": 0, "tok": 0, "cost": 0.0})
        a["calls"] += s["calls"]
        a["tok"] += s["usage"]["total_tokens"]
        a["cost"] += s["cost_est"] or 0
    if per_model:
        out.append("")
        out.append("== PAR MODÈLE ==")
        for name, a in sorted(per_model.items(), key=lambda kv: -kv[1]["tok"]):
            out.append(f"  {name:32} appels={a['calls']:>4}  tokens={a['tok']:>11,}  coût=${a['cost']:.4f}")
    return "\n".join(out)


HTML_HEAD = (
    """<!doctype html><html><head><meta charset="utf-8">
"""
    """<meta http-equiv="refresh" content="5">
"""
    """<title>Vibe usage dashboard — cpm-store</title>
"""
    """<style>
"""
    """body{font-family:-apple-system,Menlo,monospace;background:#0f1117;color:#e6e6e6;margin:2em}
"""
    """h1{font-size:1.2em} h2{font-size:1em;color:#8ab4f8;margin-top:1.6em}
"""
    """table{border-collapse:collapse;font-size:0.85em} td,th{padding:3px 10px;border-bottom:1px solid #232"""
    """62f;text-align:right}\n"""
    """td.l,th.l{text-align:left} .live{color:#7ee787;font-weight:bold} .dim{color:#8b949e}
"""
    """.bar{font-family:monospace;color:#8ab4f8} .foot{margin-top:1.5em;color:#8b949e;font-size:0.85em}
"""
    """</style></head><body>"""
)


def render_html(sessions: list[dict[str, Any]], global_threshold: int | None, project: str | None) -> str:
    """Rendu HTML statique du dashboard (auto-refresh via meta refresh)."""
    now = datetime.now(UTC)
    live = [s for s in sessions if s["live"]]
    h: list[str] = [
        HTML_HEAD,
        "<h1>Vibe usage dashboard — cpm-store</h1>",
        f"<p class='dim'>généré le {now.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        + (f" — filtre cwd <code>{project}</code>" if project else "")
        + f" — auto-refresh 5 s — {len(sessions)} sessions, <b>{len(live)} active(s) maintenant</b>"
        f" — seuil auto-compact global {global_threshold}</p>",
    ]
    if live:
        h.append(
            "<h2>Actives maintenant (parallèles)</h2><table><tr><th class='l'>session</th><th class='l'>depuis</th>"
            "<th>durée</th><th class='l'>modèle</th><th>contexte</th><th>seuil</th>"
            "<th class='l'>utilisation</th><th class='l'>cwd</th></tr>"
        )
        for s in live:
            m = s["model"]
            thr = m["auto_compact_threshold"]
            frac = (s["ctx_now"] / thr) if thr else 0
            h.append(
                f"<tr><td class='l live'>{s['short']}</td><td class='l'>{fmt_ts(s['start'])}</td>"
                f"<td>{fmt_dur(s['elapsed_s'])}</td>"
                f"<td class='l'>{m['alias']} &rarr; {m['name']}</td><td>{s['ctx_now']:,}</td><td>{thr or '-'}</td>"
                f"<td class='l bar'>{bar(frac)} {frac * 100:.1f}%</td><td class='l'>{s['cwd']}</td></tr>"
            )
        h.append("</table>")
    h.append(
        "<h2>Sessions</h2><table><tr><th class='l'>session</th><th class='l'>début</th><th>durée</th><th>état</th>"
        "<th class='l'>modèle</th><th>ctx now</th><th>ctx max</th><th>appels</th><th>total tok</th>"
        "<th>coût est.</th><th class='l'>cwd</th></tr>"
    )
    for s in sessions:
        m = s["model"]
        state = "<span class='live'>LIVE</span>" if s["live"] else "fin"
        cost = (
            f"${s['cost_est']:.4f}"
            if s["cost_est"] is not None
            else (f"${s['cost_stats']:.4f}" if s["cost_stats"] is not None else "n/a")
        )
        tot = s["stats_total"] or s["usage"]["total_tokens"]
        h.append(
            f"<tr><td class='l'>{s['short']}</td><td class='l'>{fmt_ts(s['start'])}</td>"
            f"<td>{fmt_dur(s['elapsed_s'])}</td><td>{state}</td>"
            f"<td class='l'>{m['alias']} &rarr; {m['name']}</td><td>{s['ctx_now']:,}</td><td>{s['ctx_max']:,}</td>"
            f"<td>{s['calls']}</td><td>{tot:,}</td><td>{cost}</td><td class='l'>{s['cwd']}</td></tr>"
        )
    h.append("</table>")
    tot_tok = sum(s["usage"]["total_tokens"] for s in sessions)
    tot_cost = sum(s["cost_est"] or 0 for s in sessions)
    n_calls = sum(s["calls"] for s in sessions)
    h.append(
        f"<p class='foot'>TOTAUX : {len(sessions)} sessions · {n_calls} appels LLM · {tot_tok:,} tokens · "
        f"coût estimé ${tot_cost:.4f}<br>"
        "sources : ~/.vibe/logs/session (meta.json, journaux unified, locks active) + config.toml + "
        "experiment_eval_cache.json — aucune clé API lue</p>"
    )
    h.append("</body></html>")
    return "\n".join(h)


LIVE_PAGE = (
    """<!doctype html><html><head><meta charset="utf-8">
"""
    """<title>Vibe usage dashboard — cpm-store</title>
"""
    """<style>
"""
    """body{font-family:-apple-system,Menlo,monospace;background:#0f1117;color:#e6e6e6;margin:2em}
"""
    """h1{font-size:1.2em} h2{font-size:1em;color:#8ab4f8;margin:1.6em 0 .4em}
"""
    """table{border-collapse:collapse;font-size:.85em} td,th{padding:3px 10px;border-bottom:1px solid #2326"""
    """2f;text-align:right}\n"""
    """td.l,th.l{text-align:left} .live{color:#7ee787;font-weight:bold} .dim{color:#8b949e}
"""
    """.barbg{background:#23262f;width:130px;height:10px;display:inline-block;vertical-align:middle}
"""
    """.barfg{background:#8ab4f8;height:10px} .foot{margin-top:1.5em;color:#8b949e;font-size:.85em}
"""
    """</style></head><body>
"""
    """<h1>Vibe usage dashboard — cpm-store</h1>
"""
    """<div id="meta" class="dim">chargement…</div>
"""
    """<h2>Actives maintenant (parallèles)</h2><div id="live"></div>
"""
    """<h2>Sessions</h2><div id="sessions"></div>
"""
    """<h2>Par modèle</h2><div id="models"></div>
"""
    """<div id="totals" class="foot"></div>
"""
    """<script>
"""
    """const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
"""
    """const fmtDur = s => { if (s == null) return '-'; const m=Math.floor(s/60), sec=s%60, h=Math.floor(m/"""
    """60); return h? h+'h'+String(m%60).padStart(2,'0')+'m'+String(sec).padStart(2,'0')+'s' : m+'m'+String"""
    """(sec).padStart(2,'0')+'s'; };\n"""
    """const fmtTs = t => t ? t.slice(5,19).replace('T',' ') : '-';
"""
    """const bar = (ctx, thr) => { const f = thr ? Math.min(1, ctx/thr) : 0;
"""
    """  return `<span class="barbg"><span class="barfg" style="width:${(f*100).toFixed(1)}%"></span></span"""
    """> ${(f*100).toFixed(1)}%`; };\n"""
    """const row = (s, live) => `<tr><td class="l">${s.short}</td><td class="l">${fmtTs(s.start)}</td><td>$"""
    """{fmtDur(s.elapsed_s)}</td>\n"""
    """<td>${live?'<span class="live">LIVE</span>':'fin'}</td><td class="l">${esc(s.model.alias)} &rarr; ${"""
    """esc(s.model.name)}</td>\n"""
    """<td>${s.ctx_now.toLocaleString()}</td><td>${s.ctx_max.toLocaleString()}</td><td>${(s.model.auto_comp"""
    """act_threshold ?? '-')}</td>\n"""
    """<td class="l">${bar(s.ctx_now, s.model.auto_compact_threshold)}</td><td>${s.calls}</td>
"""
    """<td>${(s.stats_total || s.usage.total_tokens).toLocaleString()}</td>
"""
    """<td>${s.cost_est != null ? '$'+s.cost_est.toFixed(4) : (s.cost_stats != null ? '$'+s.cost_stats.toFi"""
    """xed(4)+' (stats)' : 'n/a')}</td>\n"""
    """<td class="l">${esc(s.cwd)}</td></tr>`;
"""
    """async function refresh(){
"""
    """  const d = await (await fetch('/api', {cache:'no-store'})).json();
"""
    """  document.getElementById('meta').textContent =
"""
    """    `généré le ${d.generated_at.slice(0,19).replace('T',' ')} UTC — refresh 2 s` +
"""
    """    (d.project ? ` — filtre cwd ${d.project}` : '') +
"""
    """    ` — ${d.sessions.length} sessions, ${d.sessions.filter(s=>s.live).length} active(s) maintenant —"""
    """ seuil auto-compact global ${d.global_threshold ?? '-'}`;\n"""
    """  const live = d.sessions.filter(s=>s.live);
"""
    """  document.getElementById('live').innerHTML = live.length ? '<table><tr><th class="l">session</th><t"""
    """h class="l">depuis</th><th>durée</th><th class="l">modèle</th><th>ctx now</th><th>seuil</th><th clas"""
    """s="l">utilisation</th><th class="l">cwd</th></tr>'\n"""
    """    + live.map(s=>`<tr><td class="l live">${s.short}</td><td class="l">${fmtTs(s.start)}</td><td>${f"""
    """mtDur(s.elapsed_s)}</td><td class="l">${esc(s.model.alias)} &rarr; ${esc(s.model.name)}</td><td>${s."""
    """ctx_now.toLocaleString()}</td><td>${s.model.auto_compact_threshold ?? '-'}</td><td class="l">${bar(s"""
    """.ctx_now, s.model.auto_compact_threshold)}</td><td class="l">${esc(s.cwd)}</td></tr>`).join('') + '<"""
    """/table>' : '<p class="dim">aucune session active</p>';\n"""
    """  document.getElementById('sessions').innerHTML = '<table><tr><th class="l">session</th><th class="l"""
    """">début</th><th>durée</th><th>état</th><th class="l">modèle (alias → name)</th><th>ctx now</th><th>c"""
    """tx max</th><th>seuil</th><th class="l">barre</th><th>appels</th><th>total tok</th><th>coût est.</th>"""
    """<th class="l">cwd</th></tr>'\n"""
    """    + d.sessions.map(s=>row(s, s.live)).join('') + '</table>';
"""
    """  const pm = {};
"""
    """  for (const s of d.sessions){ const a = pm[s.model.name] = pm[s.model.name] || {calls:0, tok:0, cos"""
    """t:0}; a.calls+=s.calls; a.tok+=s.usage.total_tokens; a.cost+=s.cost_est||0; }\n"""
    """  document.getElementById('models').innerHTML = '<table><tr><th class="l">modèle</th><th>appels</th>"""
    """<th>tokens</th><th>coût est.</th></tr>'\n"""
    """    + Object.entries(pm).sort((a,b)=>b[1].tok-a[1].tok).map(([n,a])=>`<tr><td class="l">${esc(n)}</t"""
    """d><td>${a.calls}</td><td>${a.tok.toLocaleString()}</td><td>$${a.cost.toFixed(4)}</td></tr>`).join(''"""
    """) + '</table>';\n"""
    """  const tt = d.sessions.reduce((a,s)=>a+s.usage.total_tokens,0), tc = d.sessions.reduce((a,s)=>a+(s."""
    """cost_est||0),0), nc = d.sessions.reduce((a,s)=>a+s.calls,0);\n"""
    """  document.getElementById('totals').textContent = `TOTAUX : ${d.sessions.length} sessions · ${nc} ap"""
    """pels LLM · ${tt.toLocaleString()} tokens · coût estimé $${tc.toFixed(4)} — sources ~/.vibe/logs/sess"""
    """ion + config.toml + experiment_eval_cache.json (aucune clé API lue)`;\n"""
    """}
"""
    """refresh(); setInterval(refresh, 2000);
"""
    """</script></body></html>"""
)


def serve(port: int, vibe_home: Path, project: str | None) -> None:
    """Sert le dashboard web en local : / = page live (poll /api toutes les 2 s), /api = JSON."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                body = LIVE_PAGE.encode("utf-8")
                ctype = "text/html; charset=utf-8"
            elif self.path == "/api":
                sessions, thr = collect(vibe_home, project)
                body = json.dumps(
                    {
                        "generated_at": datetime.now(UTC).isoformat(),
                        "project": project,
                        "global_threshold": thr,
                        "sessions": sessions,
                    },
                    default=str,
                ).encode("utf-8")
                ctype = "application/json; charset=utf-8"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: object) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"dashboard web: http://127.0.0.1:{port}/  (Ctrl-C pour arrêter)", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()


def main() -> int:
    """Point d'entrée CLI : snapshot terminal, --watch, --serve, --html/--json."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--vibe-home", default=str(Path.home() / ".vibe"))
    ap.add_argument("--project", default=None)
    ap.add_argument("--watch", type=float, default=None, help="rafraîchit toutes les N secondes")
    ap.add_argument("--serve", type=int, default=None, help="sert le dashboard web sur 127.0.0.1:PORT")
    ap.add_argument("--html", default=None, help="écrit un dashboard HTML auto-refresh à ce chemin")
    ap.add_argument("--json", default=None, help="écrit un snapshot JSON à ce chemin")
    args = ap.parse_args()

    vibe_home = Path(args.vibe_home)

    if args.serve:
        serve(args.serve, vibe_home, args.project)
        return 0

    def tick() -> list[dict[str, Any]]:
        """Un rafraîchissement : collecte, affiche le texte, écrit html/json si demandé."""
        sessions, thr = collect(vibe_home, args.project)
        text = render_text(sessions, thr, args.project)
        if args.watch:
            print("\033[2J\033[H" + text, flush=True)
        else:
            print(text)
        if args.html:
            Path(args.html).parent.mkdir(parents=True, exist_ok=True)
            Path(args.html).write_text(render_html(sessions, thr, args.project), encoding="utf-8")
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(
                json.dumps(
                    {
                        "generated_at": datetime.now(UTC).isoformat(),
                        "project_filter": args.project,
                        "sessions": [
                            {k: v for k, v in s.items() if k != "model"} | {"model": s["model"]} for s in sessions
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                ),
                encoding="utf-8",
            )
        return sessions

    if args.watch:
        try:
            while True:
                tick()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            pass
    else:
        tick()
    return 0


if __name__ == "__main__":
    sys.exit(main())
