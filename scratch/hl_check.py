import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, r'C:\User\projects\hl-swing-bot\scratch')
import statistics
from _lens_common import load_bars, HOUR_MS, NET_COST
from hl_swing_bot.backtest import run_backtest
from baseline_fast import run_baseline_fast
from pullback_sweep import run as run_pb, summ as pb_summ
from pullback_lens import years

SD = r'C:\User\projects\hl-swing-bot\scratch'

def base_summ(sigs, yr):
    nets=[s['net'] for s in sigs]; Rs=[s['net']/s['risk_pct'] for s in sigs]
    eq=1.0
    for R in Rs: eq*=(1+0.005*R)
    cagr=(eq**(1/yr)-1)*100 if yr>0 else 0
    return dict(n=len(sigs), npt=statistics.mean(nets) if nets else 0, tpy=len(sigs)/yr,
                cagr=cagr, wr=(sum(1 for x in nets if x>0)/len(nets)) if nets else 0)

for name, fn in [('BTC','hist_btc.csv'),('ETH','hist_eth.csv')]:
    bars,_=load_bars(SD+'\\'+fn); yr=years(bars)
    print(f"=== HL 208d {name} ({yr:.2f}y, {len(bars)} bars) ===")
    # validate fast baseline against run_backtest on HL
    ref=run_backtest(bars, short_only=True)
    refn=ref['n_signals']
    fast=run_baseline_fast(bars)
    bs=base_summ(fast,yr)
    print(f"  BASELINE (fast) n={bs['n']} net/trade={bs['npt']:+.3f}% trades/yr={bs['tpy']:.1f} CAGR@0.5%={bs['cagr']:+.1f}%  [run_backtest n={refn} check]")
    if refn:
        refnet=statistics.mean(s['realized_pct']-NET_COST for s in ref['signals'])
        print(f"    run_backtest net/trade={refnet:+.3f}% (matches fast={abs(refnet-bs['npt'])<0.01})")
    # best pullback variant: config1 (retr 0.5-1.0) and config0
    for label,cfg in [('PB c0',dict(retr_lo=0.382,retr_hi=0.786,rsi_cap=60,stop_mult=1.5,tgt_mult=2.5,ttl=72)),
                      ('PB c1',dict(retr_lo=0.5,retr_hi=1.0,rsi_cap=60,stop_mult=1.5,tgt_mult=2.5,ttl=72)),
                      ('PB c3 ride',dict(retr_lo=0.382,retr_hi=0.786,rsi_cap=60,stop_mult=2.0,tgt_mult=4.0,ttl=120))]:
        s=pb_summ(run_pb(bars,**cfg),yr)
        if s:
            print(f"  {label}: n={s['n']} net/trade={s['npt']:+.3f}% trades/yr={s['tpy']:.1f} CAGR@0.5%={s['cagr']:+.1f}% TP%={s['tp']*100:.0f}")
        else:
            print(f"  {label}: 0 trades")
