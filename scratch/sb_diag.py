"""Slow-bleed diagnostic (my own, uses fast_engine + precomputed pkls)."""
import sys, types, datetime as dt
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch')
import fast_engine as fe

NEG_INF = -1e9


def find_downtrends(bars, drop_pct=8.0, min_hours=72, max_hours=24*21):
    closes = [b[4] for b in bars]
    n = len(closes)
    windows = []
    i = 0
    while i < n - min_hours:
        peak = closes[i]
        j_end = min(i + max_hours, n)
        trough_val = peak; trough_j = i
        for j in range(i + 1, j_end):
            if closes[j] < trough_val:
                trough_val = closes[j]; trough_j = j
        drop = (peak - trough_val) / peak * 100
        dur = trough_j - i
        if drop >= drop_pct and dur >= min_hours:
            windows.append((i, trough_j, drop, dur))
            i = trough_j + 1
        else:
            i += 1
    return windows


def max_move_atr(feats, a, b):
    mx = 0.0
    for k in range(a, b + 1):
        f = feats[k]
        if f and f['move_per_atr'] > mx:
            mx = f['move_per_atr']
    return mx


def sigs_in(sigs, wins):
    out = []
    for s in sigs:
        for (a, b, _, _) in wins:
            if a <= s['idx'] <= b:
                out.append(s); break
    return out


CANDS = {
    'baseline(mv1,vol1,sc3)': dict(),
    'mv0.5_vol0_sc2.5': dict(move_min=0.5, vol_min=0.0, score_min=2.5),
    'mv0_vol-inf_sc2.5': dict(move_min=0.0, vol_min=NEG_INF, score_min=2.5),
    'mv0_vol-inf_sc2.0': dict(move_min=0.0, vol_min=NEG_INF, score_min=2.0),
}

for key in ['btc', 'eth']:
    data = fe.load(f'scratch/feats_{key}_3y.pkl')
    bars = data['bars']; feats = data['feats']
    wins = find_downtrends(bars)
    slow = [w for w in wins if max_move_atr(feats, w[0], w[1]) < 1.0]
    print(f'\n[{key.upper()}-3y] downtrends>=8%/3d: {len(wins)}  pure-slow(no >=1.0 bar): {len(slow)}')
    for name, kw in CANDS.items():
        sigs, _ = fe.run(data, **kw)
        inwin = sigs_in(sigs, wins)
        inslow = sigs_in(sigs, slow)
        net = sum(s['realized_pct'] - 0.19 for s in inwin)
        # how many slow windows got >=1 trade
        slow_hit = 0
        for w in slow:
            if sigs_in(sigs, [w]):
                slow_hit += 1
        print(f'  {name:24s} totTrades={len(sigs):4d} inDowntrend={len(inwin):3d} '
              f'inSlow={len(inslow):3d} slowWinsCovered={slow_hit}/{len(slow)} netInDowntrend={net:+.1f}')
    # top 5 windows
    print('  --- 5 biggest downtrends ---')
    base, _ = fe.run(data)
    relax, _ = fe.run(data, move_min=0.0, vol_min=NEG_INF, score_min=2.5)
    for (a, b, drop, dur) in sorted(wins, key=lambda w: -w[2])[:5]:
        mx = max_move_atr(feats, a, b)
        nb = len(sigs_in(base, [(a, b, drop, dur)]))
        nr = len(sigs_in(relax, [(a, b, drop, dur)]))
        t0 = dt.datetime.utcfromtimestamp(bars[a][0]/1000).strftime('%Y-%m-%d')
        print(f'    {t0} drop={drop:.1f}% dur={dur}h maxMoveATR={mx:.2f} base={nb} relax={nr}')
