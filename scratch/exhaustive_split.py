"""Exhaustively check EVERY grid cell against the full gauntlet (cross-asset +
split-half both halves positive + HL same sign). Report any PASS."""
import sys, types, itertools
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch')
import fast_engine as fe

NEG_INF = -1e9
DATA = {k: fe.load(f'scratch/feats_{v}.pkl') for k, v in
        {'BTC3y': 'btc_3y', 'ETH3y': 'eth_3y', 'HLBTC': 'hist_btc', 'HLETH': 'hist_eth'}.items()}


def split(data):
    bars = data['bars']; mid = len(bars)//2
    return (dict(bars=bars[:mid], feats=data['feats'][:mid], scores=data['scores'][:mid]),
            dict(bars=bars[mid:], feats=data['feats'][mid:], scores=data['scores'][mid:]))


def npt(data, kw):
    s, b = fe.run(data, **kw)
    m = fe.metrics(s, b)
    return m['net_per_trade'] if m['n'] > 0 else 0.0, m['n']


B1, B2 = split(DATA['BTC3y']); E1, E2 = split(DATA['ETH3y'])
moves = [0.0, 0.3, 0.5, 0.7, 1.0]
vols = [NEG_INF, 0.0, 0.5, 1.0]
scores = [2.0, 2.5, 3.0]
passes = []
total = 0
for mv, vl, sc in itertools.product(moves, vols, scores):
    kw = dict(move_min=mv, vol_min=vl, score_min=sc)
    total += 1
    nb, _ = npt(DATA['BTC3y'], kw); ne, _ = npt(DATA['ETH3y'], kw)
    if not (nb > 0 and ne > 0):
        continue
    b1, _ = npt(B1, kw); b2, _ = npt(B2, kw); e1, _ = npt(E1, kw); e2, _ = npt(E2, kw)
    if not (b1 > 0 and b2 > 0 and e1 > 0 and e2 > 0):
        continue
    hb, _ = npt(DATA['HLBTC'], kw); he, _ = npt(DATA['HLETH'], kw)
    if not (hb > 0 and he > 0):
        continue
    vstr = '-inf' if vl == NEG_INF else vl
    passes.append((mv, vstr, sc, nb, ne, b1, b2, e1, e2, hb, he))

print(f'Checked {total} grid cells. PASSING all gates (cross+split+HL): {len(passes)}')
for p in passes:
    print('  ', p)
# Also: how many even pass cross-asset positive (ignoring split)?
cross_ok = 0
for mv, vl, sc in itertools.product(moves, vols, scores):
    kw = dict(move_min=mv, vol_min=vl, score_min=sc)
    nb, _ = npt(DATA['BTC3y'], kw); ne, _ = npt(DATA['ETH3y'], kw)
    if nb > 0 and ne > 0:
        cross_ok += 1
print(f'Cells passing cross-asset positive (full 3y): {cross_ok}/{total}')
# And how many pass split-half on EITHER asset's H1 (the binding failure)?
b1pos = e1pos = 0
for mv, vl, sc in itertools.product(moves, vols, scores):
    kw = dict(move_min=mv, vol_min=vl, score_min=sc)
    b1, _ = npt(B1, kw); e1, _ = npt(E1, kw)
    if b1 > 0: b1pos += 1
    if e1 > 0: e1pos += 1
print(f'Cells with BTC first-half net-positive: {b1pos}/{total}')
print(f'Cells with ETH first-half net-positive: {e1pos}/{total}')
