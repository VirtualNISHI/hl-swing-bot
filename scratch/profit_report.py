import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')  # avoid 3.13 segfault
import csv, statistics
from hl_swing_bot.backtest import HourlyBar, run_backtest

def load(path):
    out=[]
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            out.append(HourlyBar(int(r['open_time_ms']), float(r['open']), float(r['high']),
                                 float(r['low']), float(r['close']), float(r['volume']), int(r['trades'])))
    out.sort(key=lambda b: b.hour_ms)
    return out

RT=0.19; RISK=0.005; EQ0=100_000
def sim(bars, label):
    res=run_backtest(bars, short_only=True)  # live defaults: slope ON, streak>=2
    sigs=sorted(res.get('signals',[]), key=lambda x:x['ms'])
    if not sigs:
        print(f'{label}: 0 trades'); return
    eq=EQ0; peak=eq; maxdd=0; wins=0; rs=[]
    for s in sigs:
        sd=abs(s['entry']-s['stop'])/s['entry']*100
        R=(s['realized_pct']-RT)/sd if sd>0 else 0
        rs.append(R)
        if s['realized_pct']-RT>0: wins+=1
        eq*=(1+RISK*R); peak=max(peak,eq); maxdd=max(maxdd,(peak-eq)/peak*100)
    days=(bars[-1].hour_ms-bars[0].hour_ms)/86400000
    ann=((eq/EQ0)**(365/days)-1)*100
    print(f'{label}: {len(sigs)} trades / {days:.0f}d  win {wins}/{len(sigs)} ({wins/len(sigs)*100:.0f}%)  avgR {statistics.mean(rs):+.2f}')
    print(f'   JPY100,000 -> {eq:,.0f}  ({(eq/EQ0-1)*100:+.2f}% over {days:.0f}d = {ann:+.1f}%/yr)  maxDD {maxdd:.1f}%')

for coin,p in (('BTC','scratch/hist_btc.csv'),('ETH','scratch/hist_eth.csv')):
    sim(load(p), coin)
