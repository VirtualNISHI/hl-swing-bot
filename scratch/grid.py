"""Main grid: baseline + impulse-gate relaxation. Reports computed numbers only."""
import sys, types, json, itertools, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch')
import fast_engine as fe

NEG_INF = -1e9

DATA = {
    'BTC3y': fe.load('scratch/feats_btc_3y.pkl'),
    'ETH3y': fe.load('scratch/feats_eth_3y.pkl'),
    'HLBTC': fe.load('scratch/feats_hist_btc.pkl'),
    'HLETH': fe.load('scratch/feats_hist_eth.pkl'),
}


def split_data(data):
    bars = data['bars']; mid = len(bars) // 2
    d1 = {'bars': bars[:mid], 'feats': data['feats'][:mid], 'scores': data['scores'][:mid]}
    d2 = {'bars': bars[mid:], 'feats': data['feats'][mid:], 'scores': data['scores'][mid:]}
    # NOTE: slicing feats/scores keeps idx alignment ONLY for d1. For d2 we must
    # rebuild idx alignment; but fe.run iterates range(MIN_BARS,n) using local idx
    # into the sliced lists, and _resolve uses local bars. Since feats were computed
    # with full-history context, slicing them is fine as long as idx maps 1:1 to
    # the sliced bars. For d2, feats[mid:] aligns with bars[mid:] at local idx.
    return d1, d2


def run_cell(data, **kw):
    sigs, bars = fe.run(data, **kw)
    return fe.metrics(sigs, bars), sigs


def fmt(m):
    if m['n'] == 0:
        return 'n=0'
    return (f"n={m['n']} net/t={m['net_per_trade']:+.3f} tot={m['total_net']:+.1f} "
            f"wr={m['win_rate']*100:.0f}% t/yr={m['trades_per_year']:.1f} ann={m['ann']:+.2f}%")


def main():
    out = {}
    # ---- BASELINE ----
    print('=== BASELINE (slope_gate=T, red_streak>=2, move>=1.0, vol>=1.0, score>=3.0) ===')
    base = {}
    for k in ['BTC3y', 'ETH3y', 'HLBTC', 'HLETH']:
        m, sigs = run_cell(DATA[k])
        base[k] = m
        print(f'  {k}: {fmt(m)}')
    # split-half baseline BTC/ETH
    for k in ['BTC3y', 'ETH3y']:
        d1, d2 = split_data(DATA[k])
        m1, _ = run_cell(d1); m2, _ = run_cell(d2)
        print(f'  {k} split: H1 {fmt(m1)} | H2 {fmt(m2)}')
    out['baseline'] = base

    # ---- GRID ----
    moves = [0.0, 0.3, 0.5, 0.7, 1.0]
    vols = [NEG_INF, 0.0, 0.5, 1.0]
    scores = [2.0, 2.5, 3.0]
    print('\n=== GRID (slope_gate=T, red_streak>=2 kept; relax move/vol/score) ===')
    grid = []
    for mv, vl, sc in itertools.product(moves, vols, scores):
        mb, _ = run_cell(DATA['BTC3y'], move_min=mv, vol_min=vl, score_min=sc)
        me, _ = run_cell(DATA['ETH3y'], move_min=mv, vol_min=vl, score_min=sc)
        cell = dict(move=mv, vol=(None if vl == NEG_INF else vl), score=sc,
                    btc=mb, eth=me)
        grid.append(cell)
        vstr = '-inf' if vl == NEG_INF else f'{vl}'
        print(f'  mv={mv} vol={vstr} sc={sc} | BTC {fmt(mb)} || ETH {fmt(me)}')
    out['grid'] = grid

    with open('scratch/grid_out.json', 'w') as fh:
        json.dump(out, fh, default=float)
    print('\nWROTE scratch/grid_out.json')


if __name__ == '__main__':
    main()
