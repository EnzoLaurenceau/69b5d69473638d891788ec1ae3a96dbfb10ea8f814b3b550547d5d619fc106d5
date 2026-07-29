"""forge_health.py — santé du dépôt + vue par tâche, rendues DYNAMIQUEMENT.

RÈGLE : aucun site statique. Rien n'est pré-généré sur disque — `collect()` relit les
sources vivantes à CHAQUE appel et `render_html()` fabrique la page à la volée. Toute
mise à jour d'un scan ou d'une métrique est visible au rafraîchissement suivant, sans
étape de build ni fichier HTML à maintenir.

Sources (toutes optionnelles — dégradation gracieuse si absentes) :
  05_STATE/tech_debt.json      → inventaire déterministe (fichiers, SLOC, score, zones)
  05_STATE/swarm_audit.json    → findings jugés (sévérité, catégories, quarantaines)
  05_STATE/debt_priority.json  → hotspots priorisés par blast radius
  05_STATE/forge_metrics.jsonl → coût/latence/qualité par workflow+agent (vue par tâche)

CLI :
    python 00_CORE/forge_agents/forge_health.py          # résumé texte
    python 00_CORE/forge_agents/forge_health.py --json   # JSON brut
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import math
import time
from pathlib import Path
try:
    from .forge_store import state_path
except ImportError:  # lance comme script : pas de paquet parent
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from forge_agents.forge_store import state_path

logger = logging.getLogger("ForgeHealth")

FORGE_ROOT = Path(__file__).resolve().parents[2]
STATE = FORGE_ROOT / "05_STATE"

REFRESH_SECONDS = 30


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("source indisponible %s: %s", path.name, exc)
        return {}


def _grade(score: float) -> str:
    for threshold, letter in ((90, "A"), (75, "B"), (60, "C"), (40, "D")):
        if score >= threshold:
            return letter
    return "E"


def collect() -> dict:
    """Relit TOUTES les sources à chaud. Aucun cache — c'est le point de la règle dynamique."""
    debt = _load_json(state_path("tech_debt.json"))
    audit = _load_json(state_path("swarm_audit.json"))
    prio = _load_json(state_path("debt_priority.json"))

    totals = debt.get("totals", {})
    sev = audit.get("by_severity", {})
    grounding = audit.get("grounding", {})

    # ── Vue par tâche (W3-01) : agrégats du ledger de métriques ────────────────
    tasks: list = []
    ai_totals = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "errors": 0}
    try:
        from .forge_metrics import summary as metrics_summary
        # summary() renvoie {"groups": [ {workflow, agent, calls, tokens_*, latency_p50_ms…} ], …}
        tasks = list(metrics_summary().get("groups", []))
    except Exception as exc:
        logger.debug("forge_metrics indisponible: %s", exc)
        tasks = []
    for t in tasks:
        ai_totals["calls"] += t.get("calls", 0)
        ai_totals["tokens_in"] += t.get("tokens_in", 0)
        ai_totals["tokens_out"] += t.get("tokens_out", 0)
        ai_totals["cost_usd"] += t.get("cost_usd", 0.0)
        ai_totals["errors"] += t.get("errors", 0)
    tasks.sort(key=lambda t: -(t.get("tokens_in", 0) + t.get("tokens_out", 0)))

    # ── Notes (hypothèses explicites, pas des vérités) ─────────────────────────
    sloc = max(totals.get("sloc", 0), 1)
    debt_density = totals.get("score", 0) / (sloc / 1000.0)          # score / kSLOC
    crit = sev.get("CRITICAL", 0)
    high = sev.get("HIGH", 0)
    # Décroissance exponentielle : une note linéaire écrêtée saturait à 0 dès ~8 CRITICAL,
    # ce qui n'informe plus (et surjuge des findings non vérifiés un par un). Asymptotique :
    # toujours > 0, et chaque défaut supplémentaire pèse moins que le précédent.
    scores = {
        "dette": 100.0 * math.exp(-debt_density / 40.0),
        "fiabilite": 100.0 * math.exp(-(crit * 0.08 + high * 0.012)),
        "silence": 100.0 * math.exp(-totals.get("silent_excepts", 0) / 250.0),
    }
    overall = sum(scores.values()) / len(scores) if scores else 0.0

    return {
        "generated_at": time.time(),
        "sources_present": {
            "tech_debt": bool(debt), "swarm_audit": bool(audit),
            "debt_priority": bool(prio), "metrics": bool(tasks),
        },
        "repo": {
            "files": totals.get("files", 0),
            "sloc": totals.get("sloc", 0),
            "debt_score": round(totals.get("score", 0.0), 1),
            "debt_per_ksloc": round(debt_density, 1),
            "silent_excepts": totals.get("silent_excepts", 0),
            "bare_excepts": totals.get("bare_excepts", 0),
            "todos": totals.get("todos", 0),
            "duplicate_groups": totals.get("duplicate_groups", 0),
            "unreferenced_symbols": totals.get("unreferenced_symbols", 0),
            "scan_elapsed_s": debt.get("elapsed_s"),
        },
        "findings": {
            "total": audit.get("total_findings", 0),
            "by_severity": sev,
            "grounded": grounding.get("grounded", 0),
            "hallucinated_quarantined": grounding.get("hallucinated_quarantined", 0),
            "context_artifacts_quarantined": grounding.get("context_artifacts_quarantined", 0),
            "engine": audit.get("engine", "?"),
            "mimo_billed_tokens": (audit.get("cost") or {}).get("mimo_billed_tokens", 0),
            "claude_session_tokens": (audit.get("cost") or {}).get("claude_session_tokens", 0),
        },
        "zones": debt.get("zones", {}),
        "hotspots": prio.get("hotspots", [])[:10],
        "top_findings": prio.get("findings", [])[:12],
        "ai": {"totals": ai_totals, "tasks": tasks[:15]},
        "scores": {k: round(v, 1) for k, v in scores.items()},
        "overall": round(overall, 1),
        "grade": _grade(overall),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RENDU — fabriqué à la volée, jamais écrit sur disque
# ═══════════════════════════════════════════════════════════════════════════════

_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--txt:#e6edf3;--dim:#8b949e;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 10px;color:var(--dim);
text-transform:uppercase;letter-spacing:.08em}
.sub{color:var(--dim);font-size:12px;margin-bottom:20px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(165px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.k{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.v{font-size:24px;font-weight:600;margin-top:4px}
.grade{font-size:40px;font-weight:700}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.acc{color:var(--acc)}
table{width:100%;border-collapse:collapse;background:var(--panel);
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 11px;text-align:left;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase}
tr:last-child td{border-bottom:none}
code{background:#21262d;padding:1px 5px;border-radius:4px;font-size:12px}
.bar{height:6px;background:#21262d;border-radius:3px;overflow:hidden;margin-top:6px}
.bar>i{display:block;height:100%;background:var(--acc)}
.scroll{overflow-x:auto}
.miss{color:var(--warn);font-size:12px}
"""


def _cls(v: float, good: float, bad: float) -> str:
    return "ok" if v >= good else ("bad" if v <= bad else "warn")


def render_html(data: dict | None = None) -> str:
    """Fabrique la page à partir des données VIVANTES. Aucun fichier statique."""
    d = data or collect()
    e = html.escape
    r, f, ai = d["repo"], d["findings"], d["ai"]
    sev = f.get("by_severity", {})

    def card(k: str, v, cls: str = "") -> str:
        return f'<div class="card"><div class="k">{e(k)}</div><div class="v {cls}">{v}</div></div>'

    missing = [k for k, ok in d["sources_present"].items() if not ok]
    miss_html = (f'<p class="miss">Sources absentes : {", ".join(missing)} — '
                 f'les blocs correspondants sont vides.</p>') if missing else ""

    zones = "".join(
        f"<tr><td><code>{e(k)}</code></td><td>{v.get('files',0)}</td>"
        f"<td>{v.get('sloc',0):,}</td><td>{v.get('score',0):,.0f}</td></tr>"
        for k, v in list(d.get("zones", {}).items())[:12])

    hot = "".join(
        f"<tr><td>{i}</td><td><code>{e(h.get('file',''))}</code></td>"
        f"<td>{h.get('priority',0):,.0f}</td><td>{h.get('findings',0)}</td>"
        f"<td>{h.get('dependents',0)}</td></tr>"
        for i, h in enumerate(d.get("hotspots", []), 1))

    tops = "".join(
        f"<tr><td>{t.get('priority',0):.1f}</td>"
        f"<td class=\"{'bad' if t.get('severity')=='CRITICAL' else 'warn'}\">{e(t.get('severity',''))}</td>"
        f"<td>{e(t.get('category',''))}</td>"
        f"<td><code>{e(t.get('file',''))}:{t.get('line',0)}</code></td>"
        f"<td>{e(str(t.get('title',''))[:90])}</td></tr>"
        for t in d.get("top_findings", []))

    tasks = "".join(
        f"<tr><td><code>{e(str(t.get('workflow','')) or '—')}</code></td>"
        f"<td>{e(str(t.get('agent','')) or '—')}</td><td>{t.get('calls',0)}</td>"
        f"<td>{t.get('tokens_in',0):,}</td><td>{t.get('tokens_out',0):,}</td>"
        f"<td>{t.get('latency_p50_ms', 0) or 0:,}</td>"
        f"<td>{t.get('errors',0)}</td></tr>"
        for t in ai.get("tasks", []))

    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d["generated_at"]))
    g = d["grade"]
    gcls = "ok" if g in ("A", "B") else ("warn" if g == "C" else "bad")

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Santé du dépôt — Forge</title><style>{_CSS}</style></head><body><div class="wrap">
<h1>Santé du dépôt</h1>
<p class="sub">Rendu dynamique — données relues à chaque requête · {e(ts)} ·
rafraîchissement auto {REFRESH_SECONDS}s</p>
{miss_html}

<div class="grid">
  <div class="card"><div class="k">note globale</div>
    <div class="grade {gcls}">{g}</div><div class="k">{d['overall']}/100</div></div>
  {card("fichiers", f"{r['files']:,}")}
  {card("SLOC", f"{r['sloc']:,}")}
  {card("score de dette", f"{r['debt_score']:,.0f}")}
  {card("dette / kSLOC", r['debt_per_ksloc'], _cls(100 - r['debt_per_ksloc'], 70, 40))}
  {card("échecs silencieux", r['silent_excepts'], _cls(100 - r['silent_excepts'], 80, 50))}
</div>

<h2>Findings ({e(str(f['engine']))})</h2>
<div class="grid">
  {card("total retenus", f['total'])}
  {card("critical", sev.get('CRITICAL', 0), "bad" if sev.get('CRITICAL') else "ok")}
  {card("high", sev.get('HIGH', 0), "warn" if sev.get('HIGH') else "ok")}
  {card("medium", sev.get('MEDIUM', 0))}
  {card("groundés", f['grounded'], "acc")}
  {card("hallucinations écartées", f['hallucinated_quarantined'], "warn")}
  {card("artefacts écartés", f['context_artifacts_quarantined'], "warn")}
</div>

<h2>Coût IA de l'audit</h2>
<div class="grid">
  {card("tokens MiMo facturés", f"{f['mimo_billed_tokens']:,}")}
  {card("tokens session Claude", f"{f['claude_session_tokens']:,}", "ok")}
  {card("appels LLM tracés", f"{ai['totals']['calls']:,}")}
  {card("coût USD tracé", f"{ai['totals']['cost_usd']:.4f}")}
</div>

<h2>Fichiers les plus rentables à corriger</h2>
<div class="scroll"><table><tr><th>#</th><th>fichier</th><th>priorité</th>
<th>findings</th><th>dépendants</th></tr>{hot or '<tr><td colspan="5">—</td></tr>'}</table></div>

<h2>Top findings</h2>
<div class="scroll"><table><tr><th>prio</th><th>sév.</th><th>catégorie</th>
<th>emplacement</th><th>défaut</th></tr>{tops or '<tr><td colspan="5">—</td></tr>'}</table></div>

<h2>Vue par tâche (workflow × agent)</h2>
<div class="scroll"><table><tr><th>workflow</th><th>agent</th><th>appels</th>
<th>tokens in</th><th>tokens out</th><th>latence p50 ms</th><th>erreurs</th></tr>
{tasks or '<tr><td colspan="7">aucune métrique dans forge_metrics.jsonl</td></tr>'}</table></div>

<h2>Zones</h2>
<div class="scroll"><table><tr><th>zone</th><th>fichiers</th><th>SLOC</th><th>score</th></tr>
{zones or '<tr><td colspan="4">—</td></tr>'}</table></div>

<p class="sub">Findings issus de MiMo : groundés et filtrés des artefacts de découpage,
mais non vérifiés un par un. Priorité haute = à regarder en premier, pas « défaut prouvé ».</p>
</div>
<script>setTimeout(function(){{location.reload()}}, {REFRESH_SECONDS * 1000});</script>
</body></html>"""


def _main() -> int:
    ap = argparse.ArgumentParser(description="Santé du dépôt (dynamique)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    d = collect()
    if args.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0
    r, f = d["repo"], d["findings"]
    print(f"NOTE {d['grade']} ({d['overall']}/100)  scores={d['scores']}")
    print(f"dépôt : {r['files']} fichiers, {r['sloc']:,} SLOC, dette {r['debt_score']:,.0f} "
          f"({r['debt_per_ksloc']}/kSLOC), {r['silent_excepts']} échecs silencieux")
    print(f"findings : {f['total']} retenus {f['by_severity']} | groundés {f['grounded']} | "
          f"écartés {f['hallucinated_quarantined']} hallu + {f['context_artifacts_quarantined']} artefacts")
    print(f"coût : MiMo {f['mimo_billed_tokens']:,} tokens | session Claude {f['claude_session_tokens']}")
    print(f"tâches tracées : {len(d['ai']['tasks'])} | sources absentes : "
          f"{[k for k,v in d['sources_present'].items() if not v] or 'aucune'}")
    print(f"HTML rendu à la volée : {len(render_html(d)):,} caractères (jamais écrit sur disque)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
