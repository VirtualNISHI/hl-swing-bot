"""Final robustness: a few more exit structures for the pullback entry, to
confirm the archetype has no edge before rejecting. Adds a trailing-ATR-stop
'trend ride' exit (no fixed target) which is the textbook trend-follow exit."""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, r'C:\User\projects\hl-swing-bot\scratch')
import statistics
from _lens_common import load_bars, ema_series, rsi_series, wilder_atr_series, NET_COST, HOUR_MS
from pullback_lens import aggregate_4h_aligned, years
from pullback_sweep import find_swings

SD = r'C:\User\projects\hl-swing-bot\scratch'

def resolve_trail(bars, atrs, i, stop_mult=1.5, trail_mult=2.5, ttl=120):
    """SHORT with chandelier-style trailing stop: stop = min(running) +
    trail_mult*ATR_at_entry. Entry stop = entry+stop_mult*ATR. As price falls,
    trail the stop down to (lowest_low_so_far + trail_mult*ATR)."""
    a=atrs[i]
    if not a or a<=0: return None
    entry=bars[i].close
    init_stop=entry+stop_mult*a
    stop=init_stop
    lowest=entry
    end=min(i+ttl,len(bars)-1)
    for j in range(i+1,end+1):
        b=bars[j]
        if b.low<lowest: lowest=b.low
        # trail
        new_stop=lowest+trail_mult*a
        stop=min(stop,new_stop)
        if b.high>=stop:
            px=stop
            return (entry/px-1)*100, ('SL' if px>=entry else 'TRAIL'), j
    last=bars[end].close
    return (entry/last-1)*100, 'EXP', end

def run_trail(bars, ema_p=20, retr_lo=0.382, retr_hi=0.786, rsi_cap=60, rsi_p=14,
              stop_mult=1.5, trail_mult=2.5, ttl=120, cooldown_h=12, max_look=48):
    closes=[b.close for b in bars]; lows=[b.low for b in bars]; highs=[b.high for b in bars]
    ema=ema_series(closes,ema_p); atrs=wilder_atr_series(bars); rsi=rsi_series(closes,rsi_p)
    sma50_at,slope_neg_at=aggregate_4h_aligned(bars)
    trades=[]; last=-10**9; n=len(bars)
    for i in range(60,n):
        if i-last<cooldown_h: continue
        a=atrs[i]
        if not a or a<=0 or ema[i] is None or sma50_at[i] is None: continue
        if not (closes[i]<sma50_at[i] and slope_neg_at[i]): continue
        leg_hi,_,sw_lo,lo_idx,b_hi,bh_idx=find_swings(closes,lows,highs,i,max_look)
        leg=leg_hi-sw_lo
        if leg<=0: continue
        retr=(b_hi-sw_lo)/leg
        if not (retr_lo<=retr<=retr_hi): continue
        if bh_idx>=i: continue
        if rsi[bh_idx] is None or rsi[bh_idx]>rsi_cap: continue
        if not (closes[i]<lows[i-1] and closes[i]<ema[i]): continue
        out=resolve_trail(bars,atrs,i,stop_mult,trail_mult,ttl)
        if out is None: continue
        gross,status,_=out
        risk=stop_mult*a/closes[i]*100
        trades.append({'idx':i,'net':gross-NET_COST,'R':(gross-NET_COST)/risk,'status':status})
        last=i
    return trades

def summ(tr,yr):
    if not tr: return None
    nets=[t['net'] for t in tr]; Rs=[t['R'] for t in tr]
    eq=1.0
    for R in Rs: eq*=(1+0.005*R)
    return dict(n=len(tr),npt=statistics.mean(nets),tpy=len(tr)/yr,
                cagr=(eq**(1/yr)-1)*100, sumnet=sum(nets),
                wr=sum(1 for x in nets if x>0)/len(nets))

def fmt(s):
    return "0" if not s else f"n={s['n']:4d} net/t={s['npt']:+.3f}% t/yr={s['tpy']:5.1f} sumNet={s['sumnet']:+7.1f}% CAGR={s['cagr']:+.1f}% win%={s['wr']*100:.0f}"

btc,_=load_bars(SD+r'\binance_btc_3y.csv'); eth,_=load_bars(SD+r'\binance_eth_3y.csv')
for trail in [2.5, 3.5]:
    print(f"\n### TRAILING-STOP trend-ride trail={trail}xATR ###")
    for nm,bars in [('BTC',btc),('ETH',eth)]:
        yr=years(bars); m=len(bars)//2
        print(f"  {nm} FULL {fmt(summ(run_trail(bars,trail_mult=trail),yr))}")
        print(f"      H1   {fmt(summ(run_trail(bars[:m],trail_mult=trail),years(bars[:m])))}")
        print(f"      H2   {fmt(summ(run_trail(bars[m:],trail_mult=trail),years(bars[m:])))}")
