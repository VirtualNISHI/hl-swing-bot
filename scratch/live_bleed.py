"""Examine the LIVE HL-BTC 208d data: find recent ~-10%/2wk bleed, show why
baseline fired zero, and what relaxed configs would do. Also tabulate which gate
blocks each bar in the bleed window."""
import sys, types, datetime as dt
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch')
import fast_engine as fe

NEG_INF = -1e9
data = fe.load('scratch/feats_hist_btc.pkl')
bars = data['bars']; feats = data['feats']; scores = data['scores']
n = len(bars)
closes = [b[4] for b in bars]


def ts(i):
    return dt.datetime.utcfromtimestamp(bars[i][0]/1000).strftime('%Y-%m-%d %H:%M')


# find worst trailing 2-week (336h) drawdown windows
best = []
W = 336
for i in range(0, n - W):
    peak = max(closes[i:i+24])  # peak in first day of window
    trough = min(closes[i:i+W])
    drop = (peak - trough)/peak*100
    best.append((drop, i))
best.sort(reverse=True)
print('Worst 2wk drops in HL-BTC 208d:')
seen = []
for drop, i in best:
    if any(abs(i-j) < W for j in seen):
        continue
    seen.append(i)
    print(f'  {ts(i)} .. drop={drop:.1f}%')
    if len(seen) >= 4:
        break

# Take the single worst window, walk it bar by bar, classify gate blocks under baseline
drop0, i0 = next((d,i) for d,i in best)
a, b = i0, min(i0+W, n-1)
print(f'\n=== Worst window {ts(a)} .. {ts(b)} (drop {drop0:.1f}%) ===')
# baseline gate analysis
from collections import Counter
blocks = Counter()
fired_idx = []
for i in range(a, b+1):
    f = feats[i]
    if f is None:
        blocks['no_feat'] += 1; continue
    direction = 'LONG' if f['ret_1h'] > 0 else 'SHORT'
    if direction == 'LONG':
        blocks['long_bar'] += 1; continue
    sc = scores[i]
    reasons = []
    if sc < 3.0: reasons.append('score')
    if f['move_per_atr'] < 1.0: reasons.append('move')
    if f['vol_z_168'] < 1.0: reasons.append('vol')
    if not (f['trend_4h'] <= -1): reasons.append('trend4h')
    if not (f['trend_4h_slope'] <= -1): reasons.append('slope')
    if not (f['red_4h_streak'] >= 2): reasons.append('redstreak')
    if reasons:
        blocks['+'.join(reasons)] += 1
    else:
        fired_idx.append(i)
print('Baseline gate-block tally (SHORT bars only, reasons combined):')
for k,v in blocks.most_common():
    print(f'   {v:4d}  {k}')
print(f'  bars that pass ALL baseline gates: {len(fired_idx)}')

# Now actually run baseline + relaxed restricted to this window
def run_in(kw):
    sigs,_ = fe.run(data, **kw)
    return [s for s in sigs if a <= s['idx'] <= b]

for name, kw in [('baseline', dict()),
                 ('mv0.5_vol0_sc2.5', dict(move_min=0.5, vol_min=0.0, score_min=2.5)),
                 ('mv0_vol-inf_sc2.5', dict(move_min=0.0, vol_min=NEG_INF, score_min=2.5)),
                 ('mv0_vol-inf_sc2.0', dict(move_min=0.0, vol_min=NEG_INF, score_min=2.0)),
                 ('noStreak_mv0.5_sc2.5', dict(move_min=0.5, vol_min=0.0, score_min=2.5, red_streak_min=0)),
                 ('noSlope_noStreak_mv0.5_sc2.5', dict(move_min=0.5, vol_min=0.0, score_min=2.5, red_streak_min=0, slope_gate=False))]:
    w = run_in(kw)
    net = sum(s['realized_pct']-0.19 for s in w)
    print(f'  {name:30s} trades_in_window={len(w):2d} net={net:+.2f}')
