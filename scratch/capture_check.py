import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, r'C:\User\projects\hl-swing-bot\scratch')
import statistics
from _lens_common import load_bars
from baseline_fast import run_baseline_fast
from baseline_full import identify_downtrends
from pullback_sweep import run as run_pb

SD = r'C:\User\projects\hl-swing-bot\scratch'

for name, fn in [('BTC','binance_btc_3y.csv'),('ETH','binance_eth_3y.csv')]:
    bars,_=load_bars(SD+'\\'+fn)
    base=sorted(x['idx'] for x in run_baseline_fast(bars))
    # most permissive pullback (c0)
    pb=sorted(t['idx'] for t in run_pb(bars, retr_lo=0.382, retr_hi=0.786, rsi_cap=60,
                                       stop_mult=1.5, tgt_mult=2.5, ttl=72))
    eps=identify_downtrends(bars)
    missed=[ep for ep in eps if not any(ep[0]<=si<=ep[1] for si in base)]
    print(f"=== {name}: {len(eps)} downtrends, baseline missed {len(missed)} ===")
    pb_covers=sum(1 for ep in missed if any(ep[0]<=pi<=ep[1] for pi in pb))
    print(f"  pullback lens fires in {pb_covers}/{len(missed)} of the BASELINE-MISSED downtrends")
    # of these baseline-missed downtrends, what would PB net?
    nets=[]
    for ep in missed:
        from pullback_sweep import run, summ
    # compute PB net only on trades inside missed episodes
    pb_trades=run_pb(bars, retr_lo=0.382, retr_hi=0.786, rsi_cap=60, stop_mult=1.5, tgt_mult=2.5, ttl=72)
    in_missed=[t for t in pb_trades if any(ep[0]<=t['idx']<=ep[1] for ep in missed)]
    if in_missed:
        nn=[t['net'] for t in in_missed]
        print(f"  PB trades inside baseline-missed downtrends: n={len(in_missed)} net/trade={statistics.mean(nn):+.3f}% sumNet={sum(nn):+.1f}%")
