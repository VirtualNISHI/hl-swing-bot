"""Baseline (shipped config) + slow-bleed MISS diagnostic.

Runs run_backtest(short_only=True) on each asset (3y + HL). Quantifies how much
of the confirmed-downtrend price decline the baseline participates in.
"""
import sys, types, json, os, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch'); sys.path.insert(0, 'src')
import warnings; warnings.filterwarnings('ignore')
from trend_participation import load_bars, FEE
from hl_swing_bot.backtest import run_backtest
from hl_swing_bot.features import MIN_BARS

DATASETS = {
    'btc_3y': 'scratch/binance_btc_3y.csv',
    'eth_3y': 'scratch/binance_eth_3y.csv',
    'btc_hl': 'scratch/hist_btc.csv',
    'eth_hl': 'scratch/hist_eth.csv',
}

def yrs(bars):
    return (bars[-1].hour_ms - bars[MIN_BARS].hour_ms) / (365.25*24*3600*1000)

results = {}
for name, path in DATASETS.items():
    bars, _ = load_bars(path)
    feats = json.load(open(f'scratch/tp_feat_{name}.json'))['feats']
    res = run_backtest(bars, short_only=True, slippage_bps=5.0)
    sigs = res.get('signals', [])
    nets = [s['realized_pct'] - FEE for s in sigs if s['realized_pct'] is not None]
    y = yrs(bars)
    # cache baseline signals for split-half later
    json.dump({'sigs': sigs, 'years': y}, open(f'scratch/tp_baseline_{name}.json','w'))

    # ---- confirmed-downtrend coverage diagnostic ----
    # "downtrend bar" = trend_4h<=-1 and slope<=-1 (the regime we want to trade)
    dt_idx = [i for i in range(len(feats)) if feats[i] is not None
              and feats[i]['trend_4h'] <= -1 and feats[i]['trend_4h_slope'] <= -1]
    n_dt = len(dt_idx)
    # Hours where the baseline had an OPEN short (idx..exit_idx)
    covered = set()
    for s in sigs:
        if s['exit_idx'] is not None:
            for j in range(s['idx'], s['exit_idx']+1):
                covered.add(j)
    dt_covered = sum(1 for i in dt_idx if i in covered)
    cov_pct = dt_covered / n_dt * 100 if n_dt else 0

    # Total downside MOVE available in confirmed downtrend regime vs captured.
    # Available: sum of negative 1h returns while in downtrend regime (gross down move).
    avail_down = sum(-feats[i]['ret_1h'] for i in dt_idx if feats[i]['ret_1h'] < 0)
    results[name] = {
        'n_trades': len(nets), 'net_per_trade': round(statistics.mean(nets),4) if nets else 0,
        'net_total': round(sum(nets),2), 'trades_per_yr': round(len(nets)/y,1),
        'winrate': round(sum(1 for x in nets if x>0)/len(nets),3) if nets else 0,
        'dt_regime_hours': n_dt, 'dt_hours_covered': dt_covered,
        'dt_coverage_pct': round(cov_pct,1),
        'avail_down_move_in_regime_pct': round(avail_down,1),
        'years': round(y,2),
    }
    print(name, results[name], flush=True)

json.dump(results, open('scratch/tp_baseline_summary.json','w'), indent=2)
print('BASELINE DONE', flush=True)
