import sys, types, time, json, os
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch')
sys.path.insert(0, os.path.join('src'))
import warnings; warnings.filterwarnings('ignore')
from trend_participation import load_bars, precompute_features

DATASETS = {
    'btc_3y': 'scratch/binance_btc_3y.csv',
    'eth_3y': 'scratch/binance_eth_3y.csv',
    'btc_hl': 'scratch/hist_btc.csv',
    'eth_hl': 'scratch/hist_eth.csv',
}
KEEP = ('close', 'atr_1h', 'atr_pct', 'ret_1h', 'ret_4h', 'move_per_atr',
        'move_per_atr_z', 'robust_z_168', 'vol_z_168', 'trend_4h',
        'trend_4h_slope', 'red_4h_streak')

for name, path in DATASETS.items():
    t0 = time.time()
    bars, _ = load_bars(path)
    feats = precompute_features(bars)
    out = []
    for i, f in enumerate(feats):
        if f is None:
            out.append(None)
        else:
            out.append({k: f[k] for k in KEEP})
    with open(f'scratch/tp_feat_{name}.json', 'w') as fh:
        json.dump({'ms_first': bars[0].hour_ms, 'ms_last': bars[-1].hour_ms,
                   'n': len(bars), 'feats': out}, fh)
    print(name, 'done', len(bars), 'bars in', round(time.time()-t0,1), 's', flush=True)
print('ALL DONE', flush=True)
