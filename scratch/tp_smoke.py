import sys, types, time
sys.modules['duckdb'] = types.ModuleType('duckdb')
import os
sys.path.insert(0, os.path.join('scratch'))
from trend_participation import load_bars, precompute_features
import warnings; warnings.filterwarnings('ignore')

t0 = time.time()
bars, taker = load_bars('scratch/binance_btc_3y.csv')
print('loaded', len(bars), 'bars in', round(time.time()-t0, 2), 's')
print('span', bars[0].hour_ms, '..', bars[-1].hour_ms)
# Time precompute on a small slice first
t0 = time.time()
feats = precompute_features(bars[:2000])
print('precompute 2000 bars:', round(time.time()-t0, 2), 's')
fi = [f for f in feats if f is not None]
print('non-null feats:', len(fi), 'sample:', {k: round(fi[-1][k],3) for k in ('close','atr_pct','trend_4h','trend_4h_slope','red_4h_streak','move_per_atr','vol_z_168')})
