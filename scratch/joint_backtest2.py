# Workaround for CPython 3.13 crash: stub duckdb BEFORE importing backtest
# (Storage only touches duckdb at instantiation, which we never do here).
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')

import csv, statistics
from hl_swing_bot.backtest import HourlyBar, run_backtest

def load(path):
    out = []
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            out.append(HourlyBar(int(r['open_time_ms']), float(r['open']),
                                 float(r['high']), float(r['low']), float(r['close']),
                                 float(r['volume']), int(r['trades'])))
    out.sort(key=lambda b: b.hour_ms)
    return out

RT = 0.19

def stat(res, half_at=2500):
    s = res.get('signals', [])
    if not s:
        return None
    g = statistics.mean(x['realized_pct'] for x in s)
    h1 = [x for x in s if x['idx'] <= half_at]
    h2 = [x for x in s if x['idx'] > half_at]
    g1 = statistics.mean(x['realized_pct'] for x in h1) if h1 else None
    g2 = statistics.mean(x['realized_pct'] for x in h2) if h2 else None
    return dict(n=len(s), net=g - RT,
                h1=(g1 - RT if g1 is not None else None), n1=len(h1),
                h2=(g2 - RT if g2 is not None else None), n2=len(h2))

VARIANTS = [
    ('slope-only            ', dict()),
    ('slope+streak2         ', dict(red_streak_min=2)),
    ('slope+BE1.25/TP2.0    ', dict(be_trigger_atr=1.25, target_atr_mult=2.0)),
    ('slope+streak2+BE/TP2.0', dict(red_streak_min=2, be_trigger_atr=1.25, target_atr_mult=2.0)),
]

lines = []
for coin, path in (('BTC', 'scratch/hist_btc.csv'), ('ETH', 'scratch/hist_eth.csv')):
    bars = load(path)
    lines.append(f'=== {coin} ({len(bars)} bars) ===')
    for name, kw in VARIANTS:
        r = stat(run_backtest(bars, short_only=True, **kw))
        if r is None:
            lines.append(f'{name}: 0 signals')
            continue
        ok = r['h1'] is not None and r['h2'] is not None and r['h1'] > 0 and r['h2'] > 0
        lines.append(f"{name}: n={r['n']:>3}  NET={r['net']:+.3f}  "
                     f"h1={r['h1']:+.3f}(n={r['n1']})  h2={r['h2']:+.3f}(n={r['n2']})  "
                     f"[{'PASS' if ok else 'FAIL-HALF'}]")

text = '\n'.join(lines)
open('scratch/joint_results.txt', 'w').write(text)
print(text)
