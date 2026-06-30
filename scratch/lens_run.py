"""LENS full run: cache baseline entries once per asset, then test exit replacements.

Outputs (computed numbers only):
 1. Baseline 3y net/trade, trades/yr, AND slow-bleed-miss quantification.
 2. Exit variants A-D on the SAME entries: TTL extension, chandelier trail,
    4h trend-flip exit, scale-out.
 3. For the best: split-half (1st1.5y vs last1.5y), cross-asset (BTC&ETH),
    annualized return @0.5% risk.
HL 208d check done in a second script using cached funcs.
"""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')

import csv, statistics, json
from hl_swing_bot.backtest import HourlyBar, run_backtest
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

# ---- exit engines (SHORT only). Return (gross_pct, exit_idx, tag). ----
def ex_fixed(bars, ei, entry, stop, atr, atr_arr, flips, *, ttl, tmult):
    target = entry - tmult*atr
    end = min(ei+ttl, len(bars)-1)
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
    end = min(ei+ttl, len(bars)-1)
    lowest = bars[ei].low; cur = stop
    for j in range(ei+1, end+1):
        b = bars[j]
        aj = atr_arr[j] if atr_arr[j] > 0 else atr
        eff = min(cur, lowest + k*aj)
        if b.high >= eff: return (entry/eff-1)*100, j, "TR"
        lowest = min(lowest, b.low); cur = eff
    c = bars[end].close; return (entry/c-1)*100, end, "EXP"

def ex_flip(bars, ei, entry, stop, atr, atr_arr, flips, *, ttl, mode):
    end = min(ei+ttl, len(bars)-1)
    fl = flips[mode]
    for j in range(ei+1, end+1):
        b = bars[j]
        if b.high >= stop: return (entry/stop-1)*100, j, "SL"
        if fl[j]: return (entry/b.close-1)*100, j, "FL"
    c = bars[end].close; return (entry/c-1)*100, end, "EXP"

def ex_scaleout(bars, ei, entry, stop, atr, atr_arr, flips, *, ttl, fmult, rk):
    end = min(ei+ttl, len(bars)-1)
    ftp = entry - fmult*atr
    half = False; rh = 0.0; lowest = bars[ei].low; cur = stop
    for j in range(ei+1, end+1):
        b = bars[j]
        if not half:
            if b.high >= cur: return (entry/cur-1)*100, j, "SL"
            if b.low <= ftp:
                rh = 0.5*(entry/ftp-1)*100; half = True; cur = entry
                lowest = min(lowest, b.low); continue
        else:
            aj = atr_arr[j] if atr_arr[j] > 0 else atr
            eff = min(cur, lowest + rk*aj)
            if b.high >= eff: return rh + 0.5*(entry/eff-1)*100, j, "TR"
            lowest = min(lowest, b.low); cur = eff
    c = bars[end].close
    if not half: return (entry/c-1)*100, end, "EXP"
    return rh + 0.5*(entry/c-1)*100, end, "EXP"

def build_flips(bars):
    bars4 = aggregate_to_4h(bars)
    closes4 = [b.close for b in bars4]
    ms_to_idx = {b.hour_ms: i for i, b in enumerate(bars)}
    flip_sma = [False]*len(bars); flip_slope = [False]*len(bars)
    for k in range(len(bars4)):
        if k < 51: continue
        sma50 = statistics.mean(closes4[k-50:k])
        up_sma = bars4[k].close > sma50
        up_slope = False
        if k >= 61:
            sma50_prev = statistics.mean(closes4[k-60:k-10])
            up_slope = sma50 >= sma50_prev
        bstart = bars4[k].hour_ms
        idx = None
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
    """sigs: list of baseline signal dicts {idx,entry,stop,direction}. SHORT only.
    Returns list of trades with net_pct (post-fee), stop_pct, hold, exit_idx, gross."""
    trades = []
    for s in sigs:
        if s["direction"] != "SHORT": continue
        ei = s["idx"]; entry = s["entry"]; stop = s["stop"]
        # baseline SHORT: stop = entry + 1.5*atr  => atr = (stop-entry)/1.5 (exact)
        atr = (stop - entry) / 1.5
        gross, xidx, tag = engine(bars, ei, entry, stop, atr, atr_arr, flips, **kw)
        net = gross - FEE
        stop_pct = (stop/entry - 1)*100  # SHORT: stop above entry => positive % loss distance
        trades.append(dict(net_pct=net, gross=gross, stop_pct=abs(stop_pct),
                           hold=(xidx-ei), exit_idx=xidx, tag=tag, ms=bars[ei].hour_ms))
    return trades

def equity_mult(trades, risk_frac=0.005):
    eq = 1.0
    for t in trades:
        sp = t["stop_pct"]
        if sp <= 0: continue
        R = t["net_pct"]/sp
        eq *= (1 + risk_frac*R)
        if eq <= 1e-9: eq = 1e-9
    return eq

def ann_return(trades, bars, risk_frac=0.005):
    eq = equity_mult(trades, risk_frac)
    yr = years_span(bars)
    if eq <= 0: return -1.0
    return (eq ** (1/yr) - 1)*100

def summ(trades):
    if not trades: return dict(n=0)
    nets = [t["net_pct"] for t in trades]; holds=[t["hold"] for t in trades]
    return dict(n=len(trades), net_mean=round(statistics.mean(nets),4),
                net_total=round(sum(nets),2), net_median=round(statistics.median(nets),4),
                winrate=round(sum(1 for x in nets if x>0)/len(nets),3),
                med_hold=statistics.median(holds), best=round(max(nets),2),
                worst=round(min(nets),2),
                exp_share=round(sum(1 for t in trades if t["tag"]=="EXP")/len(trades),3))

def half_split(trades, bars):
    mid_ms = (bars[0].hour_ms + bars[-1].hour_ms)//2
    h1 = [t for t in trades if t["ms"] < mid_ms]
    h2 = [t for t in trades if t["ms"] >= mid_ms]
    return summ(h1), summ(h2)

# slow-bleed miss quantification (baseline)
def slowbleed_analysis(bars, sigs):
    """Identify slow-grind downtrends: rolling windows where price falls a lot over
    many bars without sharp 1h impulses; check how many baseline entries fall in them.
    Define a downtrend episode: from any local-peak, the max drawdown over the next N bars.
    We tag distinct >=8% drawdown episodes over <=21d (504h) windows and classify each as
    'cascade' (had a >=4% single-day / sharp move) vs 'slow' and count baseline entries inside."""
    closes = [b.close for b in bars]
    n = len(bars)
    episodes = []  # (start_idx, trough_idx, dd, is_slow)
    i = 0
    while i < n-1:
        # find a local peak: close >= prior 24h max-ish; simple: scan for new lower lows
        # detect drop of >=8% from a running peak within 504h
        peak = closes[i]; peak_idx = i
        j = i+1; trough = closes[i]; trough_idx = i
        seen_dd = 0.0
        while j < n and (j - peak_idx) <= 504:
            if closes[j] > peak:  # new peak resets
                peak = closes[j]; peak_idx = j; trough = closes[j]; trough_idx = j
            if closes[j] < trough:
                trough = closes[j]; trough_idx = j
            dd = (peak - trough)/peak
            if dd > seen_dd: seen_dd = dd
            j += 1
        if seen_dd >= 0.08:
            # measure sharpest 24h drop within peak_idx..trough_idx
            sharp = 0.0
            for t in range(peak_idx, min(trough_idx+1, n)):
                lo = t-24 if t-24>=peak_idx else peak_idx
                drop = (closes[lo]-closes[t])/closes[lo]
                if drop > sharp: sharp = drop
            is_slow = sharp < 0.06  # no >=6% in any 24h window => slow grind
            episodes.append((peak_idx, trough_idx, round(seen_dd*100,1),
                             round(sharp*100,1), is_slow))
            i = trough_idx+1
        else:
            i += 1
    # count baseline entries inside each episode window
    sig_idx = sorted(s["idx"] for s in sigs if s["direction"]=="SHORT")
    def in_eps(lo,hi): return sum(1 for x in sig_idx if lo <= x <= hi)
    slow_eps = [e for e in episodes if e[4]]
    casc_eps = [e for e in episodes if not e[4]]
    slow_covered = sum(1 for e in slow_eps if in_eps(e[0], e[1]) > 0)
    casc_covered = sum(1 for e in casc_eps if in_eps(e[0], e[1]) > 0)
    return dict(
        n_episodes=len(episodes), n_slow=len(slow_eps), n_cascade=len(casc_eps),
        slow_covered=slow_covered, casc_covered=casc_covered,
        slow_missed=len(slow_eps)-slow_covered,
        slow_eps=[(e[0],e[1],e[2],e[3],in_eps(e[0],e[1])) for e in slow_eps],
    )

if __name__ == "__main__":
    out = {}
    for asset, fn in [("BTC", "binance_btc_3y.csv"), ("ETH", "binance_eth_3y.csv")]:
        bars = load_bars(f"{SCRATCH}\\{fn}")
        atr_arr = wilder_atr(bars)
        flips = build_flips(bars)
        res = run_backtest(bars, short_only=True)
        sigs = res["signals"]
        yr = years_span(bars)
        a = {"asset": asset, "years": round(yr,3), "n_base": res["n_signals"]}
        # baseline reproduction via fixed-TP engine (should match expectancy)
        base_tr = make_trades(bars, sigs, atr_arr, flips, ex_fixed, ttl=72, tmult=2.5)
        a["baseline"] = summ(base_tr)
        a["baseline"]["trades_per_yr"] = round(len(base_tr)/yr,2)
        a["baseline"]["ann_ret_pct"] = round(ann_return(base_tr, bars),2)
        a["slowbleed"] = slowbleed_analysis(bars, sigs)
        # variants
        variants = {}
        for ttl in (72,168,336,720):
            tr = make_trades(bars, sigs, atr_arr, flips, ex_ttl, ttl=ttl)
            variants[f"ttl{ttl}_nostop_TP_off"] = summ(tr) | {"ann": round(ann_return(tr,bars),2)}
        for ttl in (168,336):
            for k in (2.0,3.0,4.0):
                tr = make_trades(bars, sigs, atr_arr, flips, ex_chandelier, ttl=ttl, k=k)
                variants[f"chand_ttl{ttl}_k{k}"] = summ(tr) | {"ann": round(ann_return(tr,bars),2)}
        for ttl in (336,720):
            for mode in ("sma","slope"):
                tr = make_trades(bars, sigs, atr_arr, flips, ex_flip, ttl=ttl, mode=mode)
                variants[f"flip_{mode}_ttl{ttl}"] = summ(tr) | {"ann": round(ann_return(tr,bars),2)}
        for ttl in (336,):
            for fmult in (1.5,2.5):
                for rk in (3.0,4.0):
                    tr = make_trades(bars, sigs, atr_arr, flips, ex_scaleout, ttl=ttl, fmult=fmult, rk=rk)
                    variants[f"scaleout_ttl{ttl}_f{fmult}_rk{rk}"] = summ(tr) | {"ann": round(ann_return(tr,bars),2)}
        a["variants"] = variants
        out[asset] = a
    with open(f"{SCRATCH}\\lens_out.json","w") as f:
        json.dump(out, f, indent=1, default=float)
    print("DONE")
    print(json.dumps(out, indent=1, default=float))
