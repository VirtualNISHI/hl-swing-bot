import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
import pickle, json, time
from hl_swing_bot.backtest import HourlyBar, run_backtest

JOBS = [
    ('btc3y', 'scratch/feats_btc_3y.pkl'),
    ('eth3y', 'scratch/feats_eth_3y.pkl'),
    ('btchl', 'scratch/feats_hist_btc.pkl'),
    ('ethhl', 'scratch/feats_hist_eth.pkl'),
]

def log(m):
    with open('scratch/baselines_log.txt','a') as f: f.write(m+'\n')

open('scratch/baselines_log.txt','w').close()
for key, pkl in JOBS:
    with open(pkl,'rb') as f: d=pickle.load(f)
    bars=[HourlyBar(*t) for t in d['bars']]
    t0=time.time()
    log(f'{key} start nbars={len(bars)}')
    res=run_backtest(bars, short_only=True)
    sigs=res.get('signals',[])
    with open(f'scratch/baseline_{key}.json','w') as f:
        json.dump(sigs, f)
    log(f'{key} DONE sigs={len(sigs)} in {time.time()-t0:.0f}s')
log('ALL DONE')
