"""Full validation gauntlet for candidate cells:
(a) split-half on 3y BTC & ETH (both halves net-positive)
(b) cross-asset (BTC & ETH both positive on full 3y)
(c) HL 208d same sign
Report pass/fail per gate. Baseline included as reference."""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch')
import fast_engine as fe

NEG_INF = -1e9
DATA = {k: fe.load(f'scratch/feats_{v}.pkl') for k, v in
        {'BTC3y': 'btc_3y', 'ETH3y': 'eth_3y', 'HLBTC': 'hist_btc', 'HLETH': 'hist_eth'}.items()}


def split(data):
    bars = data['bars']; mid = len(bars)//2
    d1 = dict(bars=bars[:mid], feats=data['feats'][:mid], scores=data['scores'][:mid])
    d2 = dict(bars=bars[mid:], feats=data['feats'][mid:], scores=data['scores'][mid:])
    return d1, d2


def npt(data, kw):
    s, b = fe.run(data, **kw)
    return fe.metrics(s, b)


CELLS = {
    'BASELINE (mv1,vol1,sc3)': dict(),
    'mv0.3_vol0.5_sc3.0': dict(move_min=0.3, vol_min=0.5, score_min=3.0),
    'mv0.0_vol0.5_sc3.0': dict(move_min=0.0, vol_min=0.5, score_min=3.0),
    'mv0.3_vol-inf_sc3.0': dict(move_min=0.3, vol_min=NEG_INF, score_min=3.0),
    'mv0.0_vol-inf_sc3.0': dict(move_min=0.0, vol_min=NEG_INF, score_min=3.0),
    'mv0.7_vol-inf_sc3.0': dict(move_min=0.7, vol_min=NEG_INF, score_min=3.0),
    'mv0.5_vol0.5_sc3.0': dict(move_min=0.5, vol_min=0.5, score_min=3.0),
    'mv1.0_vol-inf_sc3.0(drop vol only)': dict(move_min=1.0, vol_min=NEG_INF, score_min=3.0),
}

hdr = f"{'cell':38s} {'BTCnpt':>7s} {'ETHnpt':>7s} {'BTC_H1':>7s} {'BTC_H2':>7s} {'ETH_H1':>7s} {'ETH_H2':>7s} {'HLBTC':>6s} {'HLETH':>6s}  VERDICT"
print(hdr)
for name, kw in CELLS.items():
    mb = npt(DATA['BTC3y'], kw); me = npt(DATA['ETH3y'], kw)
    b1, b2 = split(DATA['BTC3y']); e1, e2 = split(DATA['ETH3y'])
    mb1 = npt(b1, kw); mb2 = npt(b2, kw); me1 = npt(e1, kw); me2 = npt(e2, kw)
    hb = npt(DATA['HLBTC'], kw); he = npt(DATA['HLETH'], kw)
    def g(m): return m['net_per_trade'] if m['n'] > 0 else 0.0
    # gates
    cross = g(mb) > 0 and g(me) > 0
    sh = g(mb1) > 0 and g(mb2) > 0 and g(me1) > 0 and g(me2) > 0
    hl = g(hb) > 0 and g(he) > 0
    verdict = 'PASS' if (cross and sh and hl) else 'FAIL[' + ','.join(
        x for x, ok in [('cross', cross), ('split', sh), ('hl', hl)] if not ok) + ']'
    print(f"{name:38s} {g(mb):+7.3f} {g(me):+7.3f} {g(mb1):+7.3f} {g(mb2):+7.3f} {g(me1):+7.3f} {g(me2):+7.3f} {g(hb):+6.2f} {g(he):+6.2f}  {verdict}")
    # also show n for flagging
    print(f"    n: BTC={mb['n']} ETH={me['n']} | BTC_H1={mb1['n']} H2={mb2['n']} ETH_H1={me1['n']} H2={me2['n']} | HLBTC={hb['n']} HLETH={he['n']}")
