"""
alpha_factory.py — moteur quant (workflow de la vidéo, version Forge).

analytics → split in/out-sample → optimisation génétique (optuna, IN-SAMPLE ONLY)
→ walk-forward (verdict overfitting) → rapport HTML style MT5 → filtre survivants.

Léger : pas de vectorbt. quantstats optionnel (sinon HTML auto-suffisant inline SVG).
TOUTE optimisation se fait sur l'in-sample uniquement (jamais sur le full data set).
"""
from __future__ import annotations
import datetime
from pathlib import Path
import numpy as np
import pandas as pd

from .config import MODERATE
from .backtest import Params, run as bt_run
import logging

logger = logging.getLogger(__name__)


# ── analyse de marché (distributions, autocorr, heatmap) ─────────────────────

def analytics(df: pd.DataFrame) -> dict:
    r = df["close"].pct_change().dropna()
    by_hour = r.groupby(r.index.hour).mean()
    heat = (r.abs().groupby([r.index.dayofweek, r.index.hour]).mean()
            .unstack(fill_value=0.0))
    return {
        "ret_mean": float(r.mean()), "ret_std": float(r.std()),
        "skew": float(r.skew()), "kurt": float(r.kurt()),
        "autocorr": {f"lag{k}": float(r.autocorr(k) or 0.0) for k in range(1, 6)},
        "best_hour": int(by_hour.abs().idxmax()) if len(by_hour) else None,
        "weekday_hour_heat": heat.round(5),
    }


# ── split + optimisation in-sample ───────────────────────────────────────────

def split(df: pd.DataFrame, frac: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = int(len(df) * frac)
    return df.iloc[:n], df.iloc[n:]


def _objective(trial, df_in):
    p = Params(
        k=trial.suggest_int("k", 1, 4),
        tp_r=trial.suggest_float("tp_r", 0.6, 2.5),
        sl_buffer=trial.suggest_float("sl_buffer", 0.0, 0.6),
        max_hold=trial.suggest_int("max_hold", 4, 36),
        both_sides=trial.suggest_categorical("both_sides", [True, False]),
        trend_ema=trial.suggest_categorical("trend_ema", [0, 20, 50, 100, 200]),
    )
    s = bt_run(df_in, p).stats()
    if s["trades"] < 30:                     # critère vidéo : >300 sur full ; 30 sur in-sample
        return -1e9
    pf = s["pf"] if np.isfinite(s["pf"]) else 5.0
    return s["sharpe"] * 0.5 + (pf - 1.0)     # objectif robuste


def optimize(df_in: pd.DataFrame, n_trials: int = 40) -> Params:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize")
    study.optimize(lambda t: _objective(t, df_in), n_trials=n_trials, show_progress_bar=False)
    bp = study.best_params
    return Params(k=bp["k"], tp_r=bp["tp_r"], sl_buffer=bp["sl_buffer"],
                  max_hold=bp["max_hold"], both_sides=bp["both_sides"],
                  trend_ema=bp["trend_ema"])


# ── walk-forward (verdict overfitting) ───────────────────────────────────────

def walk_forward(df: pd.DataFrame, folds: int = 4, n_trials: int = 25) -> dict:
    size = len(df) // (folds + 1)
    oos = []
    for f in range(folds):
        train = df.iloc[: size * (f + 1)]
        test = df.iloc[size * (f + 1): size * (f + 2)]
        if len(test) < 30:
            continue
        p = optimize(train, n_trials)
        oos.append(bt_run(test, p).stats())
    if not oos:
        return {"verdict": "N/A", "folds": 0}
    avg_pf = float(np.mean([s["pf"] if np.isfinite(s["pf"]) else 3.0 for s in oos]))
    avg_r = float(np.mean([s["total_r"] for s in oos]))
    verdict = ("ROBUST" if avg_pf >= 1.3 and avg_r > 0 else
               "MODERATE" if avg_pf >= 1.05 and avg_r > 0 else
               "WEAK" if avg_pf >= 0.9 else "OVERFITTED")
    return {"verdict": verdict, "folds": len(oos), "oos_avg_pf": round(avg_pf, 2),
            "oos_avg_total_r": round(avg_r, 2)}


# ── survivants ───────────────────────────────────────────────────────────────

def is_survivor(stats: dict, min_trades: int = 30, min_pf: float = 1.0) -> bool:
    return stats["trades"] >= min_trades and (stats["pf"] >= min_pf or not np.isfinite(stats["pf"]))


# ── rapport HTML (style MT5, auto-suffisant) ─────────────────────────────────

def _equity_svg(eq: pd.Series, w=680, h=180) -> str:
    if eq.empty:
        return "<p>pas de trades</p>"
    y = eq.to_numpy(float); x = np.arange(len(y))
    yn = (y - y.min()) / ((y.max() - y.min()) or 1.0)
    xn = x / ((len(x) - 1) or 1)
    pts = " ".join(f"{xn[i]*w:.1f},{h-yn[i]*h:.1f}" for i in range(len(y)))
    zero = h - ((0 - y.min()) / ((y.max() - y.min()) or 1.0)) * h
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="background:#0d1117">'
            f'<line x1="0" y1="{zero:.1f}" x2="{w}" y2="{zero:.1f}" stroke="#444"/>'
            f'<polyline fill="none" stroke="#2ea043" stroke-width="2" points="{pts}"/></svg>')


def report_html(pair: str, params: Params, ins: dict, oos: dict, wf: dict,
                eq_full: pd.Series, analytics_d: dict, out_dir: Path = None) -> Path:
    out_dir = out_dir or MODERATE.state_dir
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"factory_{pair}_{ts}.html"

    def tbl(d):
        return "".join(f"<tr><td>{k}</td><td>{round(v,4) if isinstance(v,float) else v}</td></tr>"
                       for k, v in d.items())
    heat = analytics_d["weekday_hour_heat"]
    html = f"""<!doctype html><meta charset=utf-8><title>Alpha Factory {pair}</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;max-width:760px;margin:auto;padding:1rem}}
table{{border-collapse:collapse;width:100%;margin:.4rem 0}}td{{border:1px solid #30363d;padding:3px 8px}}
h2{{color:#58a6ff}}.bad{{color:#f85149}}.good{{color:#2ea043}}</style>
<h1>Alpha Factory — {pair}</h1><p><em>{ts} — recherche/optimisation, PAS un conseil financier</em></p>
<h2>Params optimisés (in-sample only)</h2><table>{tbl(params.__dict__)}</table>
<h2>Equity (full)</h2>{_equity_svg(eq_full)}
<h2>In-sample</h2><table>{tbl(ins)}</table>
<h2>Out-of-sample</h2><table>{tbl(oos)}</table>
<h2>Walk-forward — <span class="{ 'good' if wf.get('verdict')=='ROBUST' else 'bad'}">{wf.get('verdict')}</span></h2>
<table>{tbl(wf)}</table>
<h2>Marché</h2><table>{tbl({k:v for k,v in analytics_d.items() if k!='weekday_hour_heat'})}</table>
<h3>Heatmap weekday×hour (|ret| moyen)</h3>{heat.to_html()}
"""
    path.write_text(html, encoding="utf-8")
    # bonus : tearsheet quantstats si dispo
    try:
        import quantstats as qs  # optionnel
        daily = pd.Series(eq_full.diff().fillna(eq_full)).resample("1D").sum()
        qs.reports.html(daily, output=str(out_dir / f"tearsheet_{pair}_{ts}.html"),
                        title=f"{pair} factory")
    except Exception as exc:
        logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
    return path


# ── pipeline complet ─────────────────────────────────────────────────────────

def run_factory(pair: str, df: pd.DataFrame, n_trials: int = 40) -> dict:
    df_in, df_out = split(df)
    params = optimize(df_in, n_trials)
    ins = bt_run(df_in, params).stats()
    out_res = bt_run(df_out, params)
    oos = out_res.stats()
    full = bt_run(df, params)
    wf = walk_forward(df, folds=4, n_trials=max(15, n_trials // 2))
    a = analytics(df)
    report = report_html(pair, params, ins, oos, wf, full.equity, a)
    return {"params": params.__dict__, "in_sample": ins, "out_sample": oos,
            "walk_forward": wf, "survivor": is_survivor(oos), "report": str(report)}


def _demo():
    rng = np.random.default_rng(1)
    n = 800
    close = 100 + rng.normal(0.01, 0.5, n).cumsum()
    df = pd.DataFrame({"open": np.r_[close[0], close[:-1]],
                       "high": close + np.abs(rng.normal(0, 0.3, n)),
                       "low": close - np.abs(rng.normal(0, 0.3, n)),
                       "close": close},
                      index=pd.date_range("2023-01-01", periods=n, freq="h"))
    out = run_factory("TEST", df, n_trials=8)
    assert "report" in out and Path(out["report"]).exists()
    assert out["walk_forward"]["verdict"] in {"ROBUST", "MODERATE", "WEAK", "OVERFITTED", "N/A"}
    print("alpha_factory self-check OK:", {k: out[k] for k in ("survivor", "walk_forward")})
    print("report:", out["report"])


if __name__ == "__main__":
    _demo()
