import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
import csv
from hl_swing_bot.backtest import HourlyBar, _compute_features_at

def log(m):
    with open('scratch/probe_log.txt','a') as f:
        f.write(m+'\n')

open('scratch/probe_log.txt','w').close()
bars=[]
with open('scratch/binance_btc_3y.csv') as f:
    for row in csv.DictReader(f):
        bars.append(HourlyBar(int(row['open_time_ms']),float(row['open']),float(row['high']),float(row['low']),float(row['close']),float(row['volume']),int(row['trades'])))
log(f'bars {len(bars)}')
cnt=0
for i in range(len(bars)):
    f=_compute_features_at(bars,i)
    cnt += 1 if f else 0
    if i%2000==0:
        log(f'at {i} ok={cnt}')
log(f'DONE total_ok={cnt}')
