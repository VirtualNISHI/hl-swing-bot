"""Precisely characterize the live complaint: multi-week slow-grind downtrends with
NO sharp 1h impulse (so move/ATR>=1.0 entry gate never fires). Count baseline entries
inside them. This proves the miss is an ENTRY problem (exits can't fix a missing entry)."""
import sys, types, gc
sys.modules['duckdb'] = types.ModuleType('duckdb')
gc.disable()
import csv, json, statistics
from hl_swing_bot.backtest import HourlyBar
SCRATCH = r"C:\User\projects\hl-swing-bot\scratch"

def load_bars(path):
    bars=[]
    with open(path,newline="") as f:
        r=csv.reader(f); next(r)
        for row in r:
            bars.append(HourlyBar(int(float(row[0])),float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[5]),int(float(row[6]))))
    return bars

def analyze(csv_name, base_tag):
    bars=load_bars(f"{SCRATCH}\\{csv_name}")
    base=json.load(open(f"{SCRATCH}\\base_{base_tag}.json"))
    sig_idx=sorted(s["idx"] for s in base["signals"] if s["direction"]=="SHORT")
    closes=[b.close for b in bars]; n=len(bars)
    # find peak->trough downtrend episodes >=10% over <=21d (504h)
    episodes=[]; i=0
    while i<n-1:
        peak=closes[i]; pidx=i; trough=closes[i]; tidx=i; j=i+1; seen=0.0
        while j<n and (j-pidx)<=504:
            if closes[j]>peak: peak=closes[j]; pidx=j; trough=closes[j]; tidx=j
            if closes[j]<trough: trough=closes[j]; tidx=j
            dd=(peak-trough)/peak
            if dd>seen: seen=dd
            j+=1
        if seen>=0.10:
            # sharpest single 1h drop and sharpest 24h drop within the decline
            max1h=0.0; max24=0.0
            for t in range(pidx+1, min(tidx+1,n)):
                r1=(closes[t-1]-closes[t])/closes[t-1]
                if r1>max1h: max1h=r1
                lo=t-24 if t-24>=pidx else pidx
                r24=(closes[lo]-closes[t])/closes[lo]
                if r24>max24: max24=r24
            dur_days=(tidx-pidx)/24
            entries=sum(1 for x in sig_idx if pidx<=x<=tidx)
            episodes.append(dict(pidx=pidx,tidx=tidx,dd=round(seen*100,1),
                dur_d=round(dur_days,1),max1h=round(max1h*100,2),max24=round(max24*100,1),entries=entries,
                start_ms=bars[pidx].hour_ms))
            i=tidx+1
        else: i+=1
    return episodes

if __name__=="__main__":
    out={}
    for tag,csvn in [("btc3y","binance_btc_3y.csv"),("eth3y","binance_eth_3y.csv")]:
        eps=analyze(csvn,tag)
        # 'slow grind, no sharp 1h' = max single 24h drop < 5% (the bot needs move/ATR>=1 which ~ a fast bar)
        slow=[e for e in eps if e["max24"]<5.0]
        fast=[e for e in eps if e["max24"]>=5.0]
        out[tag]=dict(
            total_eps=len(eps),
            slow_eps=len(slow), slow_with_entry=sum(1 for e in slow if e["entries"]>0),
            slow_entries_total=sum(e["entries"] for e in slow),
            fast_eps=len(fast), fast_with_entry=sum(1 for e in fast if e["entries"]>0),
            fast_entries_total=sum(e["entries"] for e in fast),
            slow_detail=[(e["dd"],e["dur_d"],e["max24"],e["entries"]) for e in slow],
        )
    print(json.dumps(out,indent=1))
