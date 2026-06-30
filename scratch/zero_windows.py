"""Find downtrend windows on 3y BTC/ETH where baseline fired ZERO trades but price
fell >= 8%. These are the user's complaint case. Then test which relaxed config
captures them WITHOUT destroying edge."""
import sys, types, datetime as dt
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch')
import fast_engine as fe

NEG_INF = -1e9


def windows(bars, drop_pct=8.0, W=336):
    closes = [b[4] for b in bars]
    n = len(closes); out = []; i = 0
    while i < n - W:
        peak = closes[i]
        seg = closes[i:i+W]
        trough = min(seg); tj = i + seg.index(trough)
        drop = (peak - trough)/peak*100
        if drop >= drop_pct:
            out.append((i, tj, drop)); i = tj + 1
        else:
            i += 1
    return out


for key in ['btc', 'eth']:
    data = fe.load(f'scratch/feats_{key}_3y.pkl')
    bars = data['bars']; feats = data['feats']
    wins = windows(bars)
    base, _ = fe.run(data)
    base_idx = set(s['idx'] for s in base)
    zero_wins = []
    for (a, b, drop) in wins:
        nb = sum(1 for s in base if a <= s['idx'] <= b)
        if nb == 0:
            # max move/ATR inside
            mx = max((feats[k]['move_per_atr'] for k in range(a, b+1) if feats[k]), default=0)
            zero_wins.append((a, b, drop, mx))
    print(f'\n[{key.upper()}-3y] downtrends>=8%: {len(wins)}  with ZERO baseline trades: {len(zero_wins)}')
    for (a, b, drop, mx) in zero_wins:
        t0 = dt.datetime.utcfromtimestamp(bars[a][0]/1000).strftime('%Y-%m-%d')
        print(f'    {t0} drop={drop:.1f}% maxMoveATR_in_win={mx:.2f}')
    # For zero windows: do relaxed configs catch them, and at what net?
    for name, kw in [('mv0.5_vol0_sc2.5', dict(move_min=0.5, vol_min=0.0, score_min=2.5)),
                     ('mv0_vol-inf_sc2.5', dict(move_min=0.0, vol_min=NEG_INF, score_min=2.5)),
                     ('mv0.3_vol-inf_sc3.0', dict(move_min=0.3, vol_min=NEG_INF, score_min=3.0))]:
        sigs, _ = fe.run(data, **kw)
        caught = 0; net_in = 0.0; tr_in = 0
        for (a, b, drop, mx) in zero_wins:
            w = [s for s in sigs if a <= s['idx'] <= b]
            if w:
                caught += 1
            tr_in += len(w)
            net_in += sum(s['realized_pct']-0.19 for s in w)
        print(f'    {name:22s} zeroWinsCaught={caught}/{len(zero_wins)} tradesAdded={tr_in} netInThoseWins={net_in:+.1f}')
