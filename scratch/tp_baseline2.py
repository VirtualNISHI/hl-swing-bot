import sys, types, json, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch'); sys.path.insert(0, 'src')
import warnings; warnings.filterwarnings('ignore')
from trend_participation import load_bars, FEE
from hl_swing_bot.backtest import run_backtest
from hl_swing_bot.features import MIN_BARS

name = sys.argv[1]
path = sys.argv[2]
bars, _ = load_bars(path)
feats = json.load(open(f'scratch/tp_feat_{name}.json'))['feats']
y = (bars[-1].hour_ms - bars[MIN_BARS].hour_ms) / (365.25*24*3600*1000)

res = run_backtest(bars, short_only=True, slippage_bps=5.0)
sigs = res.get('signals', [])
nets = [s['realized_pct'] - FEE for s in sigs if s['realized_pct'] is not None]

# split-half of baseline
mid_idx = MIN_BARS + (len(bars)-MIN_BARS)//2
h1 = [s['realized_pct']-FEE for s in sigs if s['idx'] < mid_idx and s['realized_pct'] is not None]
h2 = [s['realized_pct']-FEE for s in sigs if s['idx'] >= mid_idx and s['realized_pct'] is not None]

# confirmed-downtrend coverage
dt_idx = [i for i in range(len(feats)) if feats[i] is not None
          and feats[i]['trend_4h'] <= -1 and feats[i]['trend_4h_slope'] <= -1]
covered = set()
for s in sigs:
    if s['exit_idx'] is not None:
        covered.update(range(s['idx'], s['exit_idx']+1))
dt_cov = sum(1 for i in dt_idx if i in covered)
# also: how many trades ENTERED while move/ATR<1 and vol_z<1 (slow-bleed bars)?
slow_entries = sum(1 for s in sigs if feats[s['idx']] and
                   feats[s['idx']]['move_per_atr']<1.0 and feats[s['idx']]['vol_z_168']<1.0)

out = {
    'name': name, 'years': round(y,2), 'n': len(nets),
    'net_per_trade': round(statistics.mean(nets),4) if nets else 0,
    'net_total': round(sum(nets),2), 'trades_per_yr': round(len(nets)/y,1) if y else 0,
    'winrate': round(sum(1 for x in nets if x>0)/len(nets),3) if nets else 0,
    'h1_net_per_trade': round(statistics.mean(h1),4) if h1 else None,
    'h2_net_per_trade': round(statistics.mean(h2),4) if h2 else None,
    'h1_n': len(h1), 'h2_n': len(h2),
    'dt_regime_hours': len(dt_idx), 'dt_hours_with_open_short': dt_cov,
    'dt_coverage_pct': round(dt_cov/len(dt_idx)*100,1) if dt_idx else 0,
    'slow_bleed_entries': slow_entries,
}
json.dump(out, open(f'scratch/tp_base_{name}.json','w'), indent=2)
print(json.dumps(out), flush=True)
