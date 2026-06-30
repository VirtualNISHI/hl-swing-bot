"""Robustness of split-half result: instead of slicing (which skips MIN_BARS at the
H2 boundary), run the FULL backtest once and partition the resulting signals by
timestamp into first-half vs second-half. This uses full feature context
everywhere and is the cleanest split."""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch')
import fast_engine as fe

NEG_INF = -1e9
FEE = 0.19


def split_by_time(data, kw):
    sigs, bars = fe.run(data, **kw)
    t0 = bars[0][0]; t1 = bars[-1][0]; mid_ms = (t0 + t1) / 2
    h1 = [s for s in sigs if bars[s['idx']][0] < mid_ms]
    h2 = [s for s in sigs if bars[s['idx']][0] >= mid_ms]
    def net(ss):
        v = [s['realized_pct'] - FEE for s in ss]
        return (sum(v)/len(v), len(v)) if v else (0.0, 0)
    return net(h1), net(h2)


DATA = {k: fe.load(f'scratch/feats_{v}.pkl') for k, v in
        {'BTC3y': 'btc_3y', 'ETH3y': 'eth_3y'}.items()}

CELLS = {
    'BASELINE': dict(),
    'mv0.5_vol0.5_sc3': dict(move_min=0.5, vol_min=0.5, score_min=3.0),
    'mv0_vol-inf_sc3': dict(move_min=0.0, vol_min=NEG_INF, score_min=3.0),
    'mv0_vol-inf_sc2.5': dict(move_min=0.0, vol_min=NEG_INF, score_min=2.5),
}
for name, kw in CELLS.items():
    print(f'\n{name}')
    for k in ['BTC3y', 'ETH3y']:
        (n1, c1), (n2, c2) = split_by_time(DATA[k], kw)
        print(f'  {k}: H1 net/t={n1:+.3f} (n={c1}) | H2 net/t={n2:+.3f} (n={c2})')
