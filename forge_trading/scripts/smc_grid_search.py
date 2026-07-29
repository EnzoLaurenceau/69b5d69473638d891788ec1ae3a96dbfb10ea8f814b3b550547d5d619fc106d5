"""SMC v2 - Multi-confluence institutionnelle"""
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings('ignore')

np.random.seed(42)

def gen(start, vol, bars):
    bv = vol / np.sqrt(24)
    ret = np.random.standard_t(5, bars) * bv
    c = start * np.exp(np.cumsum(ret))
    intra = bv * 0.3
    h = c * (1 + np.abs(np.random.normal(0, intra, bars)))
    l = c * (1 - np.abs(np.random.normal(0, intra, bars)))
    o = np.roll(c, 1); o[0] = start
    return pd.DataFrame({'open': o, 'high': np.maximum(h, np.maximum(o, c)), 'low': np.minimum(l, np.minimum(o, c)), 'close': c})

pairs = {'EURUSD': (1.10, 0.005), 'GBPUSD': (1.30, 0.006), 'USDJPY': (110, 0.004), 'AUDUSD': (0.75, 0.005)}

print("=" * 70)
print("SMC v2 - MULTI-CONFLUENCE INSTITUTIONNELLE (FVG + OB + BOS)")
print("=" * 70)
print()

# Grid search
results = []

for min_conf in [4, 5, 6, 7]:
    for rr_target in [2.0, 2.5, 3.0]:
        all_trades = []
        bars = 2 * 252 * 24  # 2 years

        for pair, (start, vol) in pairs.items():
            data = gen(start, vol, bars)
            c = data["close"].values
            h = data["high"].values
            l = data["low"].values
            o = data["open"].values
            n = len(c)

            sma20 = pd.Series(c).rolling(20).mean().values
            sma50 = pd.Series(c).rolling(50).mean().values
            sma200 = pd.Series(c).rolling(200).mean().values
            delta = np.diff(c, prepend=c[0])
            g = pd.Series(np.where(delta > 0, delta, 0)).rolling(14).mean().values
            lo = pd.Series(np.where(delta < 0, -delta, 0)).rolling(14).mean().values
            lo = np.where(lo == 0, 1e-10, lo)
            rsi = 100 - 100 / (1 + g / lo)
            atr = pd.Series(np.abs(delta)).rolling(14).mean().values

            # FVG
            fvg_b = np.zeros(n)
            fvg_s = np.zeros(n)
            for i in range(1, n - 1):
                if h[i - 1] < l[i + 1]:
                    fvg_b[i] = 1
                if l[i - 1] > h[i + 1]:
                    fvg_s[i] = 1
            fvg_b_r = pd.Series(fvg_b).rolling(10).sum().values > 0
            fvg_s_r = pd.Series(fvg_s).rolling(10).sum().values > 0

            # OB
            ob_b = np.zeros(n)
            ob_s = np.zeros(n)
            for i in range(20, n - 3):
                if (c[i + 3] - c[i]) / c[i] > atr[i] / c[i] * 2 and c[i] < o[i]:
                    ob_b[i] = 1
                if (c[i] - c[i + 3]) / c[i] > atr[i] / c[i] * 2 and c[i] > o[i]:
                    ob_s[i] = 1
            ob_b_r = pd.Series(ob_b).rolling(30).sum().values > 0
            ob_s_r = pd.Series(ob_s).rolling(30).sum().values > 0

            cap = 50.0
            in_t = False

            for i in range(200, n):
                if in_t:
                    ep = None
                    if d == 1:
                        if l[i] <= sl:
                            ep = sl
                        elif h[i] >= tp:
                            ep = tp
                    else:
                        if h[i] >= sl:
                            ep = sl
                        elif l[i] <= tp:
                            ep = tp
                    if ep:
                        pnl_pct = (ep - ent) / ent * d
                        ra = cap * 0.02
                        pnl = ra * (pnl_pct * ent / abs(ent - sl))
                        pnl = np.clip(pnl, -cap * 0.05, cap * 0.05)
                        cap = max(0.01, cap + pnl)
                        all_trades.append({"pnl": pnl, "w": pnl > 0})
                        in_t = False
                    continue

                ls = 0
                ss = 0
                if sma50[i] > sma200[i]:
                    ls += 1
                if c[i] > sma50[i]:
                    ls += 1
                if fvg_b_r[i]:
                    ls += 1
                if ob_b_r[i]:
                    ls += 1
                if 30 < rsi[i] < 65:
                    ls += 1
                if c[i] > o[i]:
                    ls += 1
                if sma20[i] > sma50[i]:
                    ls += 1

                if sma50[i] < sma200[i]:
                    ss += 1
                if c[i] < sma50[i]:
                    ss += 1
                if fvg_s_r[i]:
                    ss += 1
                if ob_s_r[i]:
                    ss += 1
                if 35 < rsi[i] < 70:
                    ss += 1
                if c[i] < o[i]:
                    ss += 1
                if sma20[i] < sma50[i]:
                    ss += 1

                if ls >= min_conf and ls > ss:
                    ent = c[i] * 1.00015
                    sl = l[i] - atr[i] * 0.5
                    if sl >= ent:
                        sl = ent - atr[i]
                    tp = ent + (ent - sl) * rr_target
                    d = 1
                    in_t = True
                elif ss >= min_conf and ss > ls:
                    ent = c[i] * 0.99985
                    sl = h[i] + atr[i] * 0.5
                    if sl <= ent:
                        sl = ent + atr[i]
                    tp = ent - (sl - ent) * rr_target
                    d = -1
                    in_t = True

        df = pd.DataFrame(all_trades)
        if len(df) > 100:
            wr = df["w"].mean()
            wins = df[df["w"]]["pnl"]
            loss = df[~df["w"]]["pnl"]
            pf = abs(wins.sum() / loss.sum()) if loss.sum() != 0 else 0
            rr_act = abs(wins.mean() / loss.mean()) if len(loss) > 0 else 0
            total = df["pnl"].sum()
            status = "OK" if wr >= 0.70 and pf >= 1.0 else "NEAR" if wr >= 0.60 else "NO"
            results.append({"conf": min_conf, "rr": rr_target, "n": len(df), "wr": wr, "rr_act": rr_act, "pf": pf, "pnl": total, "status": status})

print(f"{'Conf':>4} {'RR':>4} | {'Trades':>7} {'WR':>6} {'RR':>5} {'PF':>5} {'PnL':>8} {'Status':>6}")
print("-" * 60)
for r in results:
    print(f"{r['conf']:4} {r['rr']:4.1f} | {r['n']:7,} {r['wr']:5.1%} {r['rr_act']:5.2f} {r['pf']:5.2f} {r['pnl']:+8.2f} {r['status']:>6}")

# Best
good = [r for r in results if r["wr"] >= 0.65]
if good:
    best = max(good, key=lambda x: x["wr"] * x["pf"])
    print()
    print("=" * 60)
    print("MEILLEUR RESULTAT:")
    print(f"  Confluence: {best['conf']}/7")
    print(f"  R:R target: 1:{best['rr']}")
    print(f"  Trades: {best['n']:,}")
    print(f"  Win Rate: {best['wr']:.1%}")
    print(f"  R:R actual: 1:{best['rr_act']:.2f}")
    print(f"  PF: {best['pf']:.2f}")
    print(f"  PnL: ${best['pnl']:.2f}")
