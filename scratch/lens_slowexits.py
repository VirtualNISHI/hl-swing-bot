"""Test slow-capture rules with DIFFERENT exit geometry.

Slow grinds won't hit a 2.5-ATR TP fast; they chop and stop out at 1.5 ATR.
Test: wider TTL, breakeven, trailing-ATR exit, smaller/larger targets, and a
'time-exit only' (hold N hours then exit at market) to test whether the
directional edge exists at all independent of TP/SL geometry.
"""
import sys, types, os, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_engine import load_cache, years_span
from lens_regime import build_regime

STOP_ATR = 1.5
FEE = 0.19
COOLDOWN = 4


def resolve_short_ex(high, low, close, i, entry, atr, *, ttl, targ_atr,
                     be_atr=0.0, trail_atr=0.0):
    stop = entry + STOP_ATR*atr
    target = entry - targ_atr*atr if targ_atr > 0 else None
    end = min(i+ttl, len(close)-1)
    be_armed = False
    best = entry
    for j in range(i+1, end+1):
        if trail_atr > 0:
            best = min(best, low[j-1])
            stop = min(stop, best + trail_atr*atr)
        if be_atr > 0 and be_armed:
            stop = min(stop, entry)
        if high[j] >= stop:
            st = "HIT_SL" if stop > entry else "HIT_BE"
            return st, (entry/stop-1)*100, j
        if target is not None and low[j] <= target:
            return "HIT_TP", (entry/target-1)*100, j
        if be_atr > 0 and not be_armed and low[j] <= entry - be_atr*atr:
            be_armed = True
    return "EXPIRED", (entry/close[end]-1)*100, end


def run(cache, signal_fn, *, ttl, targ_atr, be_atr=0.0, trail_atr=0.0,
        cooldown=COOLDOWN):
    feats = cache["feats"]; raw = cache["raw"]
    high, low, close, ms = raw["high"], raw["low"], raw["close"], raw["ms"]
    sigs = []
    last = -10_000
    for i in range(len(feats)):
        f = feats[i]
        if not f:
            continue
        atr = f["atr_1h"]
        if atr <= 0 or f["ret_1h"] > 0:
            continue
        if (i-last) < cooldown:
            continue
        if not signal_fn(i, f, None):
            continue
        entry = f["close"]
        stt, gross, ei = resolve_short_ex(high, low, close, i, entry, atr,
                                          ttl=ttl, targ_atr=targ_atr,
                                          be_atr=be_atr, trail_atr=trail_atr)
        net = gross - FEE
        risk = (STOP_ATR*atr)/entry*100
        sigs.append({"idx":i,"ms":ms[i],"net":net,"risk_pct":risk,"status":stt})
        last = i
    return sigs


def st(sigs, ms):
    if not sigs:
        return "n=0"
    nets = [s["net"] for s in sigs]
    yrs = years_span(ms)
    mid = (ms[0]+ms[-1])/2
    h1 = [s["net"] for s in sigs if s["ms"] < mid]
    h2 = [s["net"] for s in sigs if s["ms"] >= mid]
    eq = 1.0
    for s in sorted(sigs, key=lambda x:x["idx"]):
        if s["risk_pct"]>0:
            eq *= (1+0.005*(s["net"]/s["risk_pct"]))
    ann = (eq**(1/yrs)-1)*100
    h1m = statistics.mean(h1) if h1 else 0
    h2m = statistics.mean(h2) if h2 else 0
    return (f"n={len(sigs)} ({len(sigs)/yrs:.1f}/yr) net/t={statistics.mean(nets):.3f}% "
            f"tot={sum(nets):.1f}% win={sum(1 for x in nets if x>0)/len(nets)*100:.0f}% "
            f"ann={ann:.2f}% H1={h1m:.3f}%({len(h1)}) H2={h2m:.3f}%({len(h2)})")


if __name__ == "__main__":
    tags = sys.argv[1:] or ["btc3y"]
    for tag in tags:
        c = load_cache(tag); ms = c["raw"]["ms"]
        regime = build_regime(c); reg = regime["reg"]
        def slowgate(i, f, ctx):
            return (reg[i] == "SLOWDOWN" and f["trend_4h"] <= -1
                    and f["trend_4h_slope"] <= -1 and f["red_4h_streak"] >= 2)
        print(f"\n#### {tag}: slow rule (streak>=2 in SLOWDOWN) x exit grid")
        grids = [
            ("TP2.5/SL1.5/ttl72 (base)", dict(ttl=72, targ_atr=2.5)),
            ("TP1.5/SL1.5/ttl72",        dict(ttl=72, targ_atr=1.5)),
            ("TP1.0/SL1.5/ttl48",        dict(ttl=48, targ_atr=1.0)),
            ("TP4.0/SL1.5/ttl168",       dict(ttl=168, targ_atr=4.0)),
            ("TP3.0/SL1.5/ttl168/BE1.0", dict(ttl=168, targ_atr=3.0, be_atr=1.0)),
            ("trail1.5/SL1.5/ttl168",    dict(ttl=168, targ_atr=0.0, trail_atr=1.5)),
            ("timeexit ttl24 (no TP)",   dict(ttl=24, targ_atr=0.0)),
            ("timeexit ttl72 (no TP)",   dict(ttl=72, targ_atr=0.0)),
            ("timeexit ttl168 (no TP)",  dict(ttl=168, targ_atr=0.0)),
        ]
        for name, kw in grids:
            sigs = run(c, slowgate, **kw)
            print(f"  {name:28s}: {st(sigs, ms)}")
