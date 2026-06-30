import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, r'C:\User\projects\hl-swing-bot\scratch')
import statistics
from _lens_common import load_bars, HOUR_MS, NET_COST, wilder_atr_series
from baseline_fast import run_baseline_fast

SD = r'C:\User\projects\hl-swing-bot\scratch'

def years(bars):
    return (bars[-1].hour_ms-bars[0].hour_ms)/(HOUR_MS*24*365.25)

def identify_downtrends(bars, min_drop=0.08, min_len_h=72):
    closes=[b.close for b in bars]; atrs=wilder_atr_series(bars)
    eps=[]; n=len(closes); i=0
    while i<n-1:
        peak=closes[i]; peak_idx=i; trough=closes[i]; trough_idx=i; j=i+1
        while j<n:
            if closes[j]>peak*1.001:
                if (peak-trough)/peak<0.02:
                    peak=closes[j]; peak_idx=j; trough=closes[j]; trough_idx=j
                else:
                    break
            if closes[j]<trough:
                trough=closes[j]; trough_idx=j
            j+=1
        drop=(peak-trough)/peak; dur=trough_idx-peak_idx
        if drop>=min_drop and dur>=min_len_h:
            mx=0.0
            for k in range(peak_idx+1,trough_idx+1):
                if atrs[k] and atrs[k]>0:
                    mx=max(mx,abs(closes[k]-closes[k-1])/atrs[k])
            eps.append((peak_idx,trough_idx,drop,dur,mx))
        i=max(trough_idx,i+1)
    return eps

def summ(sigs, yr):
    nets=[s['net'] for s in sigs]
    Rs=[s['net']/s['risk_pct'] for s in sigs]
    eq=1.0
    for R in Rs: eq*=(1+0.005*R)
    cagr=(eq**(1/yr)-1)*100 if yr>0 else 0
    return dict(n=len(sigs), npt=statistics.mean(nets), tpy=len(sigs)/yr,
                cagr=cagr, tp=sum(1 for s in sigs if s['status']=='TP')/len(sigs),
                wr=sum(1 for x in nets if x>0)/len(nets), sumnet=sum(nets))

for name, fn in [('BTC','binance_btc_3y.csv'),('ETH','binance_eth_3y.csv')]:
    bars,_=load_bars(SD+'\\'+fn); yr=years(bars)
    sigs=run_baseline_fast(bars)
    s=summ(sigs,yr)
    print(f"=== {name} BASELINE (shipped: slope_gate, red>=2) {yr:.2f}y ===")
    print(f"  n={s['n']} net/trade={s['npt']:+.3f}% trades/yr={s['tpy']:.1f} "
          f"win%={s['wr']*100:.0f} TP%={s['tp']*100:.0f} sumNet={s['sumnet']:+.1f}% CAGR@0.5%={s['cagr']:+.1f}%")
    # split-half
    mid=len(bars)//2
    h1=run_baseline_fast(bars[:mid]); h2=run_baseline_fast(bars[mid:])
    s1=summ(h1,years(bars[:mid])); s2=summ(h2,years(bars[mid:]))
    print(f"  H1 net/trade={s1['npt']:+.3f}% (n={s1['n']})  H2 net/trade={s2['npt']:+.3f}% (n={s2['n']})")
    # downtrend coverage
    eps=identify_downtrends(bars)
    slow=[e for e in eps if e[4]<1.0]; fast=[e for e in eps if e[4]>=1.0]
    sidx=sorted(s2['n'] for s2 in [])  # placeholder
    sig_idx=sorted(x['idx'] for x in sigs)
    def cov(ep):
        p,t=ep[0],ep[1]; return any(p<=si<=t for si in sig_idx)
    slowc=sum(1 for e in slow if cov(e)); fastc=sum(1 for e in fast if cov(e))
    print(f"  downtrends>=8%/72h: total={len(eps)} slow(no sharp 1h bar)={len(slow)} fast={len(fast)}")
    print(f"  slow-bleed covered by >=1 baseline trade: {slowc}/{len(slow)} "
          f"({(slowc/len(slow)*100) if slow else 0:.0f}%)  fast covered: {fastc}/{len(fast)}")
    # avg drop of slow vs fast
    if slow: print(f"  slow avg drop={statistics.mean(e[2] for e in slow)*100:.1f}% avg dur={statistics.mean(e[3] for e in slow):.0f}h max1hMove/ATR avg={statistics.mean(e[4] for e in slow):.2f}")
