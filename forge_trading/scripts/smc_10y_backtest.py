"""SMC 10-year backtest - direct implementation"""
import yfinance as yf
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings('ignore')

pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'NZDUSD']

print('='*70)
print('SMC BACKTEST 10 ANS - 6 PAIRES - DAILY')
print('Sweep + Displacement + FVG Pullback Entry')
print('='*70)

all_trades = []

for pair in pairs:
    raw = yf.download(f'{pair}=X', period='10y', interval='1d', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    data = raw.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close'})

    c = data['close'].values
    h = data['high'].values
    l = data['low'].values
    o = data['open'].values
    n = len(c)

    sma50 = pd.Series(c).rolling(50).mean().values
    sma200 = pd.Series(c).rolling(200).mean().values
    delta = np.diff(c, prepend=c[0])
    g = pd.Series(np.where(delta > 0, delta, 0)).rolling(14).mean().values
    lo = pd.Series(np.where(delta < 0, -delta, 0)).rolling(14).mean().values
    lo = np.where(lo == 0, 1e-10, lo)
    rsi = 100 - 100 / (1 + g / lo)
    atr = pd.Series(np.abs(delta)).rolling(14).mean().values

    # Swings
    swing_h = []
    swing_l = []
    for i in range(10, n - 1):
        if h[i] == max(h[max(0, i-10):i+11]):
            swing_h.append((i, h[i]))
        if l[i] == min(l[max(0, i-10):i+11]):
            swing_l.append((i, l[i]))

    # Sweeps
    sweeps = []
    for idx, price in swing_h:
        for i in range(idx + 1, min(idx + 50, n)):
            if h[i] > price * 1.001 and c[i] < price:
                sweeps.append((i, 'bull', price))
                break
    for idx, price in swing_l:
        for i in range(idx + 1, min(idx + 50, n)):
            if l[i] < price * 0.999 and c[i] > price:
                sweeps.append((i, 'bear', price))
                break

    # Displacement
    ranges = h - l
    avg_range = pd.Series(ranges).rolling(20).mean().values
    body = np.abs(c - o)
    body_pct = np.where(ranges > 0, body / ranges, 0)
    is_disp_bull = (body_pct > 0.60) & (c > o) & (ranges > avg_range * 1.0)
    is_disp_bear = (body_pct > 0.60) & (c < o) & (ranges > avg_range * 1.0)

    # FVG
    fvg_bull = np.zeros(n)
    fvg_bear = np.zeros(n)
    for i in range(1, n - 1):
        if h[i-1] < l[i+1]:
            fvg_bull[i] = 1
        if l[i-1] > h[i+1]:
            fvg_bear[i] = 1

    # Index sweeps
    sweep_dict = {}
    for idx, stype, level in sweeps:
        if idx not in sweep_dict:
            sweep_dict[idx] = []
        sweep_dict[idx].append((stype, level))

    print(f'{pair}: {n} bars | {len(sweeps)} sweeps | {int(is_disp_bull.sum())+int(is_disp_bear.sum())} disp | {int(fvg_bull.sum())+int(fvg_bear.sum())} fvg')

    # Backtest
    for rr in [2.0, 2.5, 3.0]:
        cap = 50.0
        in_trade = False

        for i in range(200, n):
            if in_trade:
                ep = None
                if d == 1:
                    if l[i] <= sl_p:
                        ep = sl_p
                    elif h[i] >= tp:
                        ep = tp
                else:
                    if h[i] >= sl_p:
                        ep = sl_p
                    elif l[i] <= tp:
                        ep = tp
                if ep:
                    pnl_pct = (ep - ent) / ent * d
                    pnl = cap * 0.02 * (pnl_pct * ent / abs(ent - sl_p))
                    pnl = np.clip(pnl, -cap * 0.05, cap * 0.05)
                    cap = max(0.01, cap + pnl)
                    all_trades.append({'pair': pair, 'pnl': pnl, 'w': pnl > 0, 'rr': rr})
                    in_trade = False
                continue

            # Check sweep
            has_bull_sweep = False
            has_bear_sweep = False
            for j in range(max(0, i - 30), i + 1):
                if j in sweep_dict:
                    for stype, _ in sweep_dict[j]:
                        if stype == 'bull':
                            has_bull_sweep = True
                        elif stype == 'bear':
                            has_bear_sweep = True

            if not (has_bull_sweep or has_bear_sweep):
                continue

            # Check displacement
            has_disp_b = any(is_disp_bull[max(0, i-15):i+1])
            has_disp_s = any(is_disp_bear[max(0, i-15):i+1])

            # Check FVG
            has_fvg_b = any(fvg_bull[max(0, i-15):i+1])
            has_fvg_s = any(fvg_bear[max(0, i-15):i+1])

            # Long
            if has_bull_sweep and has_disp_b and has_fvg_b:
                conf = 3
                if sma50[i] > sma200[i]:
                    conf += 1
                if c[i] > sma50[i]:
                    conf += 1
                if 30 < rsi[i] < 65:
                    conf += 1
                if c[i] > o[i]:
                    conf += 0.5

                if conf >= 4:
                    ent = c[i] * 1.00012
                    sl_p = l[i] - atr[i] * 0.3
                    if sl_p >= ent:
                        sl_p = ent - atr[i]
                    tp = ent + (ent - sl_p) * rr
                    d = 1
                    in_trade = True
                    continue

            # Short
            if has_bear_sweep and has_disp_s and has_fvg_s:
                conf = 3
                if sma50[i] < sma200[i]:
                    conf += 1
                if c[i] < sma50[i]:
                    conf += 1
                if 35 < rsi[i] < 70:
                    conf += 1
                if c[i] < o[i]:
                    conf += 0.5

                if conf >= 4:
                    ent = c[i] * 0.99988
                    sl_p = h[i] + atr[i] * 0.3
                    if sl_p <= ent:
                        sl_p = ent + atr[i]
                    tp = ent - (sl_p - ent) * rr
                    d = -1
                    in_trade = True

# Results
df = pd.DataFrame(all_trades)

print()
print('='*70)
print('RESULTATS GLOBAUX')
print('='*70)

for rr in [2.0, 2.5, 3.0]:
    sub = df[df['rr'] == rr] if len(df) > 0 else pd.DataFrame()
    if len(sub) == 0:
        print(f'  RR=1:{rr:.1f} | 0 trades')
        continue

    wins = sub[sub['w']]
    losses = sub[~sub['w']]
    wr = len(wins) / len(sub)
    pnl = sub['pnl'].sum()
    pf = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else 0
    rr_act = abs(wins['pnl'].mean() / losses['pnl'].mean()) if len(losses) > 0 and losses['pnl'].mean() != 0 else 0

    tag = '<< TARGET' if wr >= 0.70 else ('GOOD' if wr >= 0.55 else ('OK' if wr >= 0.51 else 'LOW'))
    print(f'  RR=1:{rr:.1f} | {len(sub):5} trades | WR={wr:.1%} | RR_act=1:{rr_act:.2f} | PF={pf:.2f} | PnL=${pnl:.2f} | {tag}')

# Detail per pair for best RR
print()
print('PAR PAIRE (RR=1:2.5):')
sub = df[df['rr'] == 2.5] if len(df) > 0 else pd.DataFrame()
if len(sub) > 0:
    for pair in pairs:
        ps = sub[sub['pair'] == pair]
        if len(ps) == 0:
            print(f'  {pair}: 0 trades')
            continue
        pw = ps[ps['w']]
        wr = len(pw) / len(ps)
        pnl = ps['pnl'].sum()
        print(f'  {pair}: {len(ps)} trades | WR={wr:.1%} | PnL=${pnl:.2f}')
