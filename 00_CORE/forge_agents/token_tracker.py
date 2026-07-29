"""
token_tracker.py — Système de comptabilité tokens : devis initial → tracking réel → post-mortem.

Pipeline :
  1) estimate_budget(task)   → devis initial affiché AVANT exécution
  2) add_log(usage)          → chaque forge_call() loggue input/output/cost/latency par modèle
  3) generate_final_report() → comparaison budget vs réel + recommandations d'optimisation

Le tracker est un singleton global accessible via get_tracker(), réinitialisé
par session via reset_session(session_id). Les logs sont écrits dans
08_LOGS/tokens/<session_id>-<timestamp>.json à la fin de chaque tâche.
"""

from __future__ import annotations
import json
import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

FORGE_ROOT = Path(__file__).parent.parent.parent
TOKEN_LOGS_DIR = FORGE_ROOT / "08_LOGS" / "tokens"
TOKEN_LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Models & pricing (USD per 1M tokens, valeurs mai 2026) ──────────────────

class Model(str, Enum):
    DS2API       = "ds2api-deepseek-v4"
    RTK          = "rtk-free-aggregator"
    GEMINI_FLASH = "gemini-2.5-flash"
    GROQ_LLAMA   = "groq-llama-4-scout"
    CEREBRAS     = "cerebras-llama-3.3"
    CLAUDE_HAIKU = "claude-haiku-4.5"
    CLAUDE_SONNET= "claude-sonnet-4.5"
    CLAUDE_OPUS  = "claude-opus-4.6"


# (input_per_1M_USD, output_per_1M_USD)
PRICING: dict[Model, tuple[float, float]] = {
    Model.DS2API:       (0.0,    0.0),
    Model.RTK:          (0.0,    0.0),
    Model.GEMINI_FLASH: (0.0,    0.0),
    Model.GROQ_LLAMA:   (0.0,    0.0),
    Model.CEREBRAS:     (0.0,    0.0),
    Model.CLAUDE_HAIKU: (0.80,   4.00),
    Model.CLAUDE_SONNET:(3.00,  15.00),
    Model.CLAUDE_OPUS: (15.00,  75.00),
}


def compute_cost(model: Model, input_tokens: int, output_tokens: int) -> float:
    """USD pour un appel donné."""
    in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


# ─── Mapping tier (forge_llm) → Model enum ───────────────────────────────────

def model_from_tier_and_provider(tier: str, provider: str = "") -> Model:
    """Convertit (tier, provider) du forge_llm vers le Model enum."""
    t = (tier or "").lower()
    p = (provider or "").lower()
    if t == "free":
        if "ds2api" in p:   return Model.DS2API
        if "rtk" in p:      return Model.RTK
        if "gemini" in p:   return Model.GEMINI_FLASH
        if "groq" in p:     return Model.GROQ_LLAMA
        if "cerebras" in p: return Model.CEREBRAS
        return Model.DS2API  # default free = ds2api
    if t == "haiku":  return Model.CLAUDE_HAIKU
    if t == "sonnet": return Model.CLAUDE_SONNET
    if t == "opus":   return Model.CLAUDE_OPUS
    return Model.CLAUDE_SONNET


# ─── TokenUsage : log atomique d'un appel ────────────────────────────────────

@dataclass
class TokenUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    node_name: str
    task_type: str = ""
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat())


# ─── Heuristiques d'estimation par type de tâche ─────────────────────────────
# (model, input_tokens, output_tokens) — basés sur observations historiques

ESTIMATES_BY_TASK: dict[str, list[tuple[Model, int, int]]] = {
    "market_scan": [
        (Model.GEMINI_FLASH,  5_000, 2_000),
        (Model.GROQ_LLAMA,    8_000, 3_000),
        (Model.CLAUDE_HAIKU,  3_000, 1_500),
        (Model.CLAUDE_SONNET,12_000, 4_000),
    ],
    "research": [
        (Model.GEMINI_FLASH,  4_000, 1_500),
        (Model.CLAUDE_SONNET,15_000, 5_000),
    ],
    "hunt": [
        (Model.GEMINI_FLASH,  3_000, 1_000),
        (Model.CLAUDE_SONNET,10_000, 3_500),
    ],
    "build": [
        (Model.GEMINI_FLASH,  2_000,   800),
        (Model.CLAUDE_HAIKU,  5_000, 2_500),
        (Model.CLAUDE_SONNET,25_000, 8_000),
    ],
    "close": [
        (Model.CLAUDE_HAIKU, 10_000, 4_000),
        (Model.CLAUDE_SONNET, 5_000, 2_000),
    ],
    "marketing": [
        (Model.GEMINI_FLASH,  3_000, 1_500),
        (Model.CLAUDE_HAIKU, 12_000, 5_000),
        (Model.CLAUDE_SONNET, 8_000, 3_000),
    ],
    "audit": [
        (Model.GEMINI_FLASH,  4_000, 1_500),
        (Model.CLAUDE_OPUS,  10_000, 3_000),
    ],
    "critique": [
        (Model.CLAUDE_OPUS, 15_000, 5_000),
    ],
    "orchestrate": [
        (Model.GEMINI_FLASH,  2_000,   500),
        (Model.CLAUDE_OPUS,   8_000, 2_500),
    ],
    "plan": [
        (Model.CLAUDE_OPUS, 12_000, 4_000),
    ],
}


def normalize_task(task: str) -> str:
    """Mappe un nom de tâche utilisateur vers une clé d'ESTIMATES_BY_TASK."""
    t = (task or "").lower()
    for key in ESTIMATES_BY_TASK:
        if key in t:
            return key
    return "market_scan"  # défaut raisonnable


# ─── TokenTracker : singleton qui agrège tout ────────────────────────────────

class TokenTracker:
    def __init__(self):
        self.logs: list[TokenUsage] = []
        self.estimate: dict[Model, dict] = {}
        self.task_name: str = ""
        self.session_id: str = ""
        # AAOS 84 — économies réalisées (cache fingerprint, réflexes cervelet…)
        self.tokens_saved: int = 0
        self.money_saved: float = 0.0
        self.latency_saved_ms: int = 0
        self.calls_avoided: int = 0

    # ── Reset ─────────────────────────────────────────────────────────────────
    def reset_session(self, session_id: str, task_name: str = "") -> None:
        self.logs = []
        self.estimate = {}
        self.session_id = session_id
        self.task_name = task_name
        self.tokens_saved = 0
        self.money_saved = 0.0
        self.latency_saved_ms = 0
        self.calls_avoided = 0

    # ── Logging ──────────────────────────────────────────────────────────────
    def add_log(self, usage: TokenUsage) -> None:
        self.logs.append(usage)

    # ── AAOS 84 — Token Efficiency ────────────────────────────────────────────
    def add_saving(self, tokens: int = 0, cost: float = 0.0, latency_ms: int = 0) -> None:
        """Enregistre un appel LLM évité (cache hit, réflexe, script local)."""
        self.tokens_saved += max(0, tokens)
        self.money_saved += max(0.0, cost)
        self.latency_saved_ms += max(0, latency_ms)
        self.calls_avoided += 1

    def savings_summary(self) -> dict:
        """Agrège les savings de la session active + tous les logs historiques."""
        # 1. Session active (in-memory)
        total_saved = self.tokens_saved
        total_money = self.money_saved
        total_latency = self.latency_saved_ms
        total_calls = self.calls_avoided

        # 2. Scanner les logs historiques persistés sur disque
        for f in TOKEN_LOGS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                # Format 1: nested efficiency_savings
                eff = data.get("efficiency_savings", {})
                total_saved += eff.get("tokens_saved", 0)
                total_money += eff.get("money_saved", 0.0)
                total_latency += eff.get("latency_saved_ms", 0)
                total_calls += eff.get("calls_avoided", 0)
                # Format 2: top-level savings_usd (legacy logs)
                if "savings_usd" in data:
                    total_money += data.get("savings_usd", 0.0)
            except Exception:
                continue

        return {
            "tokens_saved": total_saved,
            "money_saved": round(total_money, 4),
            "latency_saved_ms": total_latency,
            "calls_avoided": total_calls,
        }

    # ── Estimation ───────────────────────────────────────────────────────────
    def estimate_budget(self, task: str) -> dict[Model, dict]:
        """Génère un devis initial pour la tâche."""
        self.task_name = task
        key = normalize_task(task)
        plan = ESTIMATES_BY_TASK[key]

        est: dict[Model, dict] = {}
        for model, in_tok, out_tok in plan:
            est[model] = {
                "input":  in_tok,
                "output": out_tok,
                "cost":   compute_cost(model, in_tok, out_tok),
            }
        self.estimate = est
        return est

    # ── Agrégation réelle par modèle ─────────────────────────────────────────
    def actuals_by_model(self) -> dict[Model, dict]:
        agg: dict[str, dict] = {}
        for log in self.logs:
            d = agg.setdefault(log.model, {"input": 0, "output": 0, "cost": 0.0, "calls": 0, "latency_ms": 0})
            d["input"]      += log.input_tokens
            d["output"]     += log.output_tokens
            d["cost"]       += log.cost_usd
            d["calls"]      += 1
            d["latency_ms"] += log.latency_ms
        return {Model(k) if k in {m.value for m in Model} else k: v for k, v in agg.items()}

    def get_stats(self) -> dict:
        """Retourne un dictionnaire des métriques cumulées pour la session active."""
        actuals = self.actuals_by_model()
        total_in = sum(d["input"] for d in actuals.values())
        total_out = sum(d["output"] for d in actuals.values())
        total_cost = sum(d["cost"] for d in actuals.values())
        return {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "cost": round(total_cost, 4),
        }


    # ── Rendu tableaux ────────────────────────────────────────────────────────
    def render_estimate_table(self) -> str:
        if not self.estimate:
            return "(aucun devis — appelle estimate_budget() avant)"
        lines = []
        lines.append("╔══════════════════════════════════════════════════════════════════════╗")
        lines.append(f"║ TOKEN ESTIMATE — Task: {self.task_name[:42]:<42} ║")
        lines.append("╠══════════════════════════════════════════════════════════════════════╣")
        lines.append("║ Model            │  Est.Input │ Est.Output │  Unit Cost │   Total ║")
        lines.append("╠══════════════════╪═══════════╪═══════════╪═══════════╪═════════╣")
        total_in = total_out = total_cost = 0
        for model, d in self.estimate.items():
            in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
            rate_str = "Free" if in_rate == 0 else f"${in_rate}/1M in"
            cost_str = "Free" if d["cost"] == 0 else f"${d['cost']:.4f}"
            lines.append(f"║ {model.value[:16]:<16} │ {d['input']:>9,} │ {d['output']:>9,} │ {rate_str:<9} │ {cost_str:>7} ║")
            total_in   += d["input"]
            total_out  += d["output"]
            total_cost += d["cost"]
        lines.append("╠══════════════════╪═══════════╪═══════════╪═══════════╪═════════╣")
        lines.append(f"║ TOTAL ESTIMATED  │ {total_in:>9,} │ {total_out:>9,} │           │ ${total_cost:>6.4f} ║")
        lines.append("╚══════════════════════════════════════════════════════════════════════╝")
        return "\n".join(lines)

    def render_actual_table(self) -> str:
        actuals = self.actuals_by_model()
        if not actuals:
            return "(aucun appel loggé)"

        lines = []
        lines.append("╔══════════════════════════════════════════════════════════════════════╗")
        lines.append(f"║ TOKEN ACTUAL — Task: {self.task_name[:44]:<44} ║")
        lines.append("╠══════════════════════════════════════════════════════════════════════╣")
        lines.append("║ Model            │ Real Input │ Real Output│ Calls │   Total Cost ║")
        lines.append("╠══════════════════╪═══════════╪═══════════╪═══════╪═════════════╣")
        total_in = total_out = total_cost = total_calls = 0
        for model, d in actuals.items():
            mval = model.value if isinstance(model, Model) else str(model)
            cost_str = "Free" if d["cost"] == 0 else f"${d['cost']:.4f}"
            lines.append(f"║ {mval[:16]:<16} │ {d['input']:>9,} │ {d['output']:>9,} │ {d['calls']:>5} │ {cost_str:>11} ║")
            total_in    += d["input"]
            total_out   += d["output"]
            total_cost  += d["cost"]
            total_calls += d["calls"]

        # Variance ligne
        est_in   = sum(d["input"]  for d in self.estimate.values()) if self.estimate else 0
        est_out  = sum(d["output"] for d in self.estimate.values()) if self.estimate else 0
        est_cost = sum(d["cost"]   for d in self.estimate.values()) if self.estimate else 0

        def pct(actual, est):
            if est == 0:
                return "—"
            delta = (actual - est) / est * 100
            sign = "+" if delta > 0 else ""
            return f"{sign}{delta:.1f}%"

        lines.append("╠══════════════════╪═══════════╪═══════════╪═══════╪═════════════╣")
        lines.append(f"║ TOTAL ACTUAL     │ {total_in:>9,} │ {total_out:>9,} │ {total_calls:>5} │ ${total_cost:>10.4f} ║")
        lines.append(f"║ VARIANCE         │ {pct(total_in, est_in):>9} │ {pct(total_out, est_out):>9} │       │ {pct(total_cost, est_cost):>11} ║")
        lines.append("╚══════════════════════════════════════════════════════════════════════╝")
        return "\n".join(lines)

    # ── Analyse / recommandations ────────────────────────────────────────────
    def generate_recommendations(self) -> list[str]:
        """Heuristiques d'optimisation post-mortem."""
        recs: list[str] = []
        actuals = self.actuals_by_model()
        if not actuals or not self.estimate:
            return recs

        # Analyse des logs de consommation par nœud / type de tâche
        if self.logs:
            by_node = {}
            for log in self.logs:
                key = (log.node_name or "unknown", log.model or "unknown")
                d = by_node.setdefault(key, {"input": 0, "output": 0, "calls": 0, "cost": 0.0})
                d["input"] += log.input_tokens
                d["output"] += log.output_tokens
                d["calls"] += 1
                d["cost"] += log.cost_usd

            if by_node:
                most_consuming_key = max(by_node.keys(), key=lambda k: by_node[k]["input"] + by_node[k]["output"])
                most_consuming = by_node[most_consuming_key]
                node_name, model_name = most_consuming_key
                total_tok = most_consuming["input"] + most_consuming["output"]
                
                suggestion = "optimiser les prompts et réduire la taille du contexte"
                node_lower = node_name.lower()
                if "research" in node_lower or "scan" in node_lower or "search" in node_lower:
                    suggestion = "utiliser des requêtes AST/symbole locales (GitNexus query/context) au lieu de grepper tout le code"
                elif "build" in node_lower or "generate" in node_lower or "edit" in node_lower:
                    suggestion = "utiliser le moteur d'édition sémantique (Semantic Patch Optimizer) pour générer des diffs minimaux au lieu de réécrire les fichiers"
                elif "audit" in node_lower or "validate" in node_lower or "jury" in node_lower:
                    suggestion = "activer le cache sémantique (optiforge) et déléguer la validation rapide aux modèles légers (Gemini Flash / Haiku)"
                elif total_tok > 50000:
                    suggestion = "activer le Rust Token Killer (RTK) sur les sorties de commandes et compresser le contexte Graphify"

                recs.append(
                    f"🔥 CONSOMMATION MAX : Le nœud '{node_name}' ({model_name}) a consommé le plus avec {total_tok:,} tokens "
                    f"({most_consuming['input']:,} in / {most_consuming['output']:,} out) en {most_consuming['calls']} appels. "
                    f"Solution : {suggestion}."
                )

        for model, est_d in self.estimate.items():
            act_d = actuals.get(model)
            est_in, est_out = est_d["input"], est_d["output"]

            if act_d is None:
                recs.append(
                    f"• {model.value} prévu mais jamais appelé "
                    f"(budget {est_in + est_out:,} tokens libérés) → retirer du plan ou affecter à une autre tâche"
                )
                continue

            in_var  = (act_d["input"]  - est_in)  / est_in  * 100 if est_in  else 0
            out_var = (act_d["output"] - est_out) / est_out * 100 if est_out else 0

            if in_var < -15:
                recs.append(
                    f"• {model.value} : input réel {abs(in_var):.0f}% sous budget "
                    f"→ réduire l'estimation de {abs(in_var)/100*0.8:.0%} pour les prochaines tâches similaires"
                )
            elif in_var > 25:
                recs.append(
                    f"• {model.value} : input réel {in_var:+.0f}% au-dessus du budget "
                    f"→ prompt à compresser ou contexte Graphify à raccourcir"
                )
            if out_var > 25:
                recs.append(
                    f"• {model.value} : output {out_var:+.0f}% au-dessus du budget "
                    f"→ ajouter contrainte 'réponds en N mots max' au prompt"
                )

        # Substitution Haiku → Free si scoring/format
        haiku_usage = actuals.get(Model.CLAUDE_HAIKU)
        if haiku_usage and haiku_usage["calls"] > 0:
            # Si tokens moyens/appel < 500, c'est typiquement un score → Free suffit
            avg_in = haiku_usage["input"] / haiku_usage["calls"]
            if avg_in < 500:
                recs.append(
                    f"• {haiku_usage['calls']} appels Haiku < 500 tok input "
                    f"→ basculer ces scoring/format vers FREE tier (Gemini/Groq), économie ~${haiku_usage['cost']:.4f}"
                )

        # Latence
        slow_models = [(m, d) for m, d in actuals.items()
                       if d["calls"] > 0 and d["latency_ms"] / d["calls"] > 4000]
        for model, d in slow_models:
            mval = model.value if isinstance(model, Model) else str(model)
            recs.append(
                f"• {mval} : latence moyenne {d['latency_ms']/d['calls']:.0f}ms "
                f"→ envisager Cerebras (ultra-rapide) ou paralléliser les appels"
            )

        if not recs:
            recs.append("• Budget tenu, aucune optimisation évidente — workflow équilibré ✓")
        return recs

    # ── Efficiency score ─────────────────────────────────────────────────────
    def efficiency_score(self) -> float:
        """Score 0–100 : qualité de l'estimation + ratio gratuit/payant."""
        actuals = self.actuals_by_model()
        if not actuals or not self.estimate:
            return 0.0

        est_cost = sum(d["cost"] for d in self.estimate.values())
        act_cost = sum(d["cost"] for d in actuals.values())

        # Variance score (100 si pile-poil, dégrade au-delà de 20%)
        if est_cost == 0 and act_cost == 0:
            variance_score = 100.0
        elif est_cost == 0:
            variance_score = 50.0
        else:
            variance = abs(act_cost - est_cost) / est_cost
            variance_score = max(0.0, 100.0 - variance * 100)

        # Ratio gratuit (plus c'est haut, mieux c'est)
        free_in = sum(d["input"] + d["output"] for m, d in actuals.items()
                      if (m if isinstance(m, Model) else Model(m)) in
                      {Model.GEMINI_FLASH, Model.GROQ_LLAMA, Model.CEREBRAS})
        total_tok = sum(d["input"] + d["output"] for d in actuals.values())
        free_ratio = (free_in / total_tok) if total_tok else 0
        free_score = free_ratio * 100

        return round(variance_score * 0.6 + free_score * 0.4, 1)

    # ── Rapport final ────────────────────────────────────────────────────────
    def generate_final_report(self) -> dict:
        recs = self.generate_recommendations()
        score = self.efficiency_score()

        actuals = self.actuals_by_model()
        act_cost = sum(d["cost"] for d in actuals.values())
        est_cost = sum(d["cost"] for d in self.estimate.values()) if self.estimate else 0
        savings = est_cost - act_cost

        report = {
            "task": self.task_name,
            "session_id": self.session_id,
            "estimate_table": self.render_estimate_table(),
            "actual_table":   self.render_actual_table(),
            "recommendations": recs,
            "efficiency_score": score,
            "savings_usd": round(savings, 4),
            "efficiency_savings": self.savings_summary(),  # AAOS 84
            "raw_logs": [asdict(log) for log in self.logs],
        }
        # Persistance JSON
        ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        out_path = TOKEN_LOGS_DIR / f"{self.session_id or 'default'}-{ts}.json"
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False, default=str)
            report["log_path"] = str(out_path)
        except Exception as e:
            report["log_path"] = f"(write failed: {e})"
        return report


# ─── Singleton accessor ──────────────────────────────────────────────────────

_GLOBAL_TRACKER: Optional[TokenTracker] = None

def get_tracker() -> TokenTracker:
    global _GLOBAL_TRACKER
    if _GLOBAL_TRACKER is None:
        _GLOBAL_TRACKER = TokenTracker()
    return _GLOBAL_TRACKER


# ─── CLI test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    t = get_tracker()
    t.reset_session("test-001", "market_scan niche IA créateurs")

    # 1) DEVIS
    t.estimate_budget("market_scan niche IA créateurs")
    print(t.render_estimate_table())

    # 2) Simule des appels
    t.add_log(TokenUsage(Model.GEMINI_FLASH.value, 4_200, 1_800, 0.0, 850, "HUNTER", "score"))
    t.add_log(TokenUsage(Model.GROQ_LLAMA.value,   6_800, 2_100, 0.0, 320, "MARKET", "summarize"))
    t.add_log(TokenUsage(Model.CLAUDE_HAIKU.value, 2_300,   950, compute_cost(Model.CLAUDE_HAIKU, 2_300, 950), 1200, "BUILDER", "write_email"))
    t.add_log(TokenUsage(Model.CLAUDE_SONNET.value,11_847, 3_921, compute_cost(Model.CLAUDE_SONNET, 11_847, 3_921), 2341, "MARKET", "market_scan"))

    # 3) Rapport final
    print()
    print(t.render_actual_table())
    print()
    print("📊 RECOMMANDATIONS")
    for r in t.generate_recommendations():
        print(r)
    print(f"\n📈 EFFICIENCY SCORE: {t.efficiency_score()}/100")

    report = t.generate_final_report()
    print(f"\n💾 Log sauvé → {report['log_path']}")
