"""Phase 2: exit-replacement testing on CACHED baseline entries. No run_backtest,
no O(n^2). Stable. Reports baseline + variants + split-half + annualized + slowbleed."""
import sys, types, gc
sys.modules['duckdb'] = types.ModuleType('duckdb')
gc.disable()
import csv, json, statistics
from hl_swing_bot.backtest import HourlyBar
from hl_swing_bot.features import aggregate_to_4h, wilder_atr

SCRATCH = r"C:\User\projects\hl-swing-bot\scratch"
FEE = 0.19

def load_bars(path):
    bars = []
    with open(path, newline="") as f:
        r = csv.reader(f); next(r)
        for row in r:
            bars.append(HourlyBar(int(float(row[0])), float(row[1]), float(row[2]),
                                  float(row[3]), float(row[4]), float(row[5]), int(float(row[6]))))
    return bars

def years_span(bars):
    return (bars[-1].hour_ms - bars[0].hour_ms) / (1000*60*60*24*365.25)

# ---- exit engines (SHORT). Return (gross_pct, exit_idx, tag). ----
def ex_fixed(bars, ei, entry, stop, atr, atr_arr, flips, *, ttl, tmult):
    target = entry - tmult*atr; end = min(ei+ttl, len(bars)-1)
    for j in range(ei+1, end+1):
        b = bars[j]
        if b.high >= stop: return (entry/stop-1)*100, j, "SL"
        if b.low <= target: return (entry/target-1)*100, j, "TP"
    c = bars[end].close; return (entry/c-1)*100, end, "EXP"

def ex_ttl(bars, ei, entry, stop, atr, atr_arr, flips, *, ttl):
    end = min(ei+ttl, len(bars)-1)
    for j in range(ei+1, end+1):
        if bars[j].high >= stop: return (entry/stop-1)*100, j, "SL"
    c = bars[end].close; return (entry/c-1)*100, end, "EXP"

def ex_chandelier(bars, ei, entry, stop, atr, atr_arr, flips, *, ttl, k):
    end = min(ei+ttl, len(bars)-1); lowest = bars[ei].low; cur = stop
    for j in range(ei+1, end+1):
        b = bars[j]; aj = atr_arr[j] if atr_arr[j] > 0 else atr
        eff = cur if cur < lowest + k*aj else lowest + k*aj
        if b.high >= eff: return (entry/eff-1)*100, j, "TR"
        if b.low < lowest: lowest = b.low
        cur = eff
    c = bars[end].close; return (entry/c-1)*100, end, "EXP"

def ex_flip(bars, ei, entry, stop, atr, atr_arr, flips, *, ttl, mode):
    end = min(ei+ttl, len(bars)-1); fl = flips[mode]
    for j in range(ei+1, end+1):
        b = bars[j]
        if b.high >= stop: return (entry/stop-1)*100, j, "SL"
        if fl[j]: return (entry/b.close-1)*100, j, "FL"
    c = bars[end].close; return (entry/c-1)*100, end, "EXP"

def ex_scaleout(bars, ei, entry, stop, atr, atr_arr, flips, *, ttl, fmult, rk):
    end = min(ei+ttl, len(bars)-1); ftp = entry - fmult*atr
    half = False; rh = 0.0; lowest = bars[ei].low; cur = stop
    for j in range(ei+1, end+1):
        b = bars[j]
        if not half:
            if b.high >= cur: return (entry/cur-1)*100, j, "SL"
            if b.low <= ftp:
                rh = 0.5*(entry/ftp-1)*100; half = True; cur = entry
                if b.low < lowest: lowest = b.low
                continue
        else:
            aj = atr_arr[j] if atr_arr[j] > 0 else atr
            eff = cur if cur < lowest + rk*aj else lowest + rk*aj
            if b.high >= eff: return rh + 0.5*(entry/eff-1)*100, j, "TR"
            if b.low < lowest: lowest = b.low
            cur = eff
    c = bars[end].close
    if not half: return (entry/c-1)*100, end, "EXP"
    return rh + 0.5*(entry/c-1)*100, end, "EXP"

def build_flips(bars):
    bars4 = aggregate_to_4h(bars); closes4 = [b.close for b in bars4]
    ms_to_idx = {b.hour_ms: i for i, b in enumerate(bars)}
    flip_sma = [False]*len(bars); flip_slope = [False]*len(bars)
    for k in range(len(bars4)):
        if k < 51: continue
        sma50 = statistics.mean(closes4[k-50:k]); up_sma = bars4[k].close > sma50
        up_slope = False
        if k >= 61:
            sma50_prev = statistics.mean(closes4[k-60:k-10]); up_slope = sma50 >= sma50_prev
        bstart = bars4[k].hour_ms; idx = None
        for off in range(3,-1,-1):
            cand = bstart + off*3600000
            if cand in ms_to_idx: idx = ms_to_idx[cand]; break
        if idx is None: continue
        nxt = None
        if k+1 < len(bars4):
            nb = bars4[k+1].hour_ms
            for off in range(0,4):
                cand = nb+off*3600000
                if cand in ms_to_idx: nxt = ms_to_idx[cand]; break
        hi = nxt if nxt is not None else len(bars)
        for jj in range(idx, hi):
            flip_sma[jj] = up_sma; flip_slope[jj] = up_slope
    return {"sma": flip_sma, "slope": flip_slope}

def make_trades(bars, sigs, atr_arr, flips, engine, **kw):
    trades = []
    for s in sigs:
        if s["direction"] != "SHORT": continue
        ei = s["idx"]; entry = s["entry"]; stop = s["stop"]
        atr = (stop - entry) / 1.5
        gross, xidx, tag = engine(bars, ei, entry, stop, atr, atr_arr, flips, **kw)
        net = gross - FEE; stop_pct = abs((stop/entry - 1)*100)
        trades.append(dict(net_pct=net, gross=gross, stop_pct=stop_pct,
                           hold=(xidx-ei), tag=tag, ms=bars[ei].hour_ms))
    return trades

def equity_mult(trades, risk_frac=0.005):
    eq = 1.0
    for t in trades:
        sp = t["stop_pct"]
        if sp <= 0: continue
        eq *= (1 + risk_frac*(t["net_pct"]/sp))
        if eq <= 1e-9: eq = 1e-9
    return eq

def ann_return(trades, bars, risk_frac=0.005):
    eq = equity_mult(trades, risk_frac); yr = years_span(bars)
    return (eq**(1/yr) - 1)*100 if eq > 0 else -100.0

def summ(trades):
    if not trades: return dict(n=0)
    nets=[t["net_pct"] for t in trades]; holds=[t["hold"] for t in trades]
    return dict(n=len(trades), net_mean=round(statistics.mean(nets),4),
                net_total=round(sum(nets),2), net_median=round(statistics.median(nets),4),
                winrate=round(sum(1 for x in nets if x>0)/len(nets),3),
                med_hold=statistics.median(holds), best=round(max(nets),2), worst=round(min(nets),2),
                exp_share=round(sum(1 for t in trades if t["tag"]=="EXP")/len(trades),3))

def half_split(trades, bars):
    mid=(bars[0].hour_ms+bars[-1].hour_ms)//2
    h1=[t for t in trades if t["ms"]<mid]; h2=[t for t in trades if t["ms"]>=mid]
    return summ(h1), summ(h2)

def slowbleed_analysis(bars, sigs):
    closes=[b.close for b in bars]; n=len(bars); episodes=[]; i=0
    while i < n-1:
        peak=closes[i]; peak_idx=i; trough=closes[i]; trough_idx=i; j=i+1; seen=0.0
        while j < n and (j-peak_idx) <= 504:
            if closes[j] > peak: peak=closes[j]; peak_idx=j; trough=closes[j]; trough_idx=j
            if closes[j] < trough: trough=closes[j]; trough_idx=j
            dd=(peak-trough)/peak
            if dd > seen: seen=dd
            j+=1
        if seen >= 0.08:
            sharp=0.0
            for t in range(peak_idx, min(trough_idx+1,n)):
                lo=t-24 if t-24>=peak_idx else peak_idx
                drop=(closes[lo]-closes[t])/closes[lo]
                if drop > sharp: sharp=drop
            is_slow = sharp < 0.06
            episodes.append((peak_idx,trough_idx,round(seen*100,1),round(sharp*100,1),is_slow))
            i=trough_idx+1
        else: i+=1
    sig_idx=sorted(s["idx"] for s in sigs if s["direction"]=="SHORT")
    def cnt(lo,hi): return sum(1 for x in sig_idx if lo<=x<=hi)
    slow=[e for e in episodes if e[4]]; casc=[e for e in episodes if not e[4]]
    return dict(n_episodes=len(episodes), n_slow=len(slow), n_cascade=len(casc),
        slow_covered=sum(1 for e in slow if cnt(e[0],e[1])>0),
        casc_covered=sum(1 for e in casc if cnt(e[0],e[1])>0),
        slow_eps=[(e[0],e[1],e[2],e[3],cnt(e[0],e[1])) for e in slow],
        casc_eps=[(e[0],e[1],e[2],e[3],cnt(e[0],e[1])) for e in casc])

VARIANTS = []
for ttl in (72,168,336,720): VARIANTS.append((f"ttl{ttl}_nostop_noTP", ex_ttl, dict(ttl=ttl)))
for ttl in (168,336):
    for k in (2.0,3.0,4.0): VARIANTS.append((f"chand_ttl{ttl}_k{k}", ex_chandelier, dict(ttl=ttl,k=k)))
for ttl in (336,720):
    for mode in ("sma","slope"): VARIANTS.append((f"flip_{mode}_ttl{ttl}", ex_flip, dict(ttl=ttl,mode=mode)))
for fmult in (1.5,2.5):
    for rk in (3.0,4.0): VARIANTS.append((f"scaleout336_f{fmult}_rk{rk}", ex_scaleout, dict(ttl=336,fmult=fmult,rk=rk)))

def run_asset(csv_name, base_tag, do_slowbleed=True):
    bars = load_bars(f"{SCRATCH}\\{csv_name}")
    base = json.load(open(f"{SCRATCH}\\base_{base_tag}.json"))
    sigs = base["signals"]
    atr_arr = wilder_atr(bars); flips = build_flips(bars)
    a = dict(asset=base_tag, n_bars=len(bars), years=round(years_span(bars),3), n_base=base["n_signals"])
    bt = make_trades(bars, sigs, atr_arr, flips, ex_fixed, ttl=72, tmult=2.5)
    a["baseline"] = summ(bt); a["baseline"]["trades_per_yr"]=round(len(bt)/years_span(bars),2)
    a["baseline"]["ann"]=round(ann_return(bt,bars),2)
    h1,h2 = half_split(bt,bars); a["baseline"]["h1"]=h1; a["baseline"]["h2"]=h2
    if do_slowbleed: a["slowbleed"]=slowbleed_analysis(bars,sigs)
    V={}
    for name,eng,kw in VARIANTS:
        tr=make_trades(bars,sigs,atr_arr,flips,eng,**kw)
        s=summ(tr); s["ann"]=round(ann_return(tr,bars),2)
        h1,h2=half_split(tr,bars); s["h1net"]=h1.get("net_mean"); s["h2net"]=h2.get("net_mean")
        s["h1n"]=h1.get("n"); s["h2n"]=h2.get("n")
        V[name]=s
    a["variants"]=V
    return a, bars, sigs, atr_arr, flips

if __name__ == "__main__":
    out={}
    out["BTC3y"],_,_,_,_ = run_asset("binance_btc_3y.csv","btc3y")
    out["ETH3y"],_,_,_,_ = run_asset("binance_eth_3y.csv","eth3y")
    out["BTChl"],_,_,_,_ = run_asset("hist_btc.csv","btchl", do_slowbleed=False)
    out["EThl"],_,_,_,_ = run_asset("hist_eth.csv","ethhl", do_slowbleed=False)
    with open(f"{SCRATCH}\\lens_final.json","w") as f: json.dump(out,f,indent=1,default=float)
    print("DONE")
