"""SWITCHED PORTFOLIO vs cascade-only purity.

Portfolio = baseline cascade signals (everywhere) UNION best slow-capture rule
routed ONLY in SLOWDOWN regime. De-dup overlapping entries (same idx within
cooldown). Compare annualized return + maxDD + split-half vs cascade-only.

Also: robustness of conclusion to a WIDER slow-regime definition.
"""
import sys, types, os, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_engine import (load_cache, run_variant, sig_baseline, years_span)
from lens_regime import build_regime
from lens_slowexits import resolve_short_ex, STOP_ATR, FEE

COOLDOWN = 4


def slow_signals(cache, reg, *, ttl, targ_atr, trail_atr=0.0, streak=2,
                 cooldown=COOLDOWN):
    feats = cache["feats"]; raw = cache["raw"]
    high, low, close, ms = raw["high"], raw["low"], raw["close"], raw["ms"]
    sigs = []; last = -10_000
    for i in range(len(feats)):
        f = feats[i]
        if not f:
            continue
        atr = f["atr_1h"]
        if atr <= 0 or f["ret_1h"] > 0:
            continue
        if reg[i] != "SLOWDOWN":
            continue
        if not (f["trend_4h"] <= -1 and f["trend_4h_slope"] <= -1
                and f["red_4h_streak"] >= streak):
            continue
        if (i-last) < cooldown:
            continue
        entry = f["close"]
        stt, gross, ei = resolve_short_ex(high, low, close, i, entry, atr,
                                          ttl=ttl, targ_atr=targ_atr, trail_atr=trail_atr)
        net = gross - FEE
        risk = (STOP_ATR*atr)/entry*100
        sigs.append({"idx":i,"ms":ms[i],"net":net,"risk_pct":risk,"src":"slow"})
        last = i
    return sigs


def base_signals(cache):
    raw = cache["raw"]
    out = []
    for s in run_variant(cache, sig_baseline):
        out.append({"idx":s["idx"],"ms":s["ms"],"net":s["net"],
                    "risk_pct":s["risk_pct"],"src":"casc"})
    return out


def merge(base, slow, cooldown=COOLDOWN):
    """Union by idx; if a slow signal lands within cooldown of an already-placed
    signal, drop it (single-position assumption)."""
    allsig = sorted(base + slow, key=lambda x: x["idx"])
    kept = []; last = -10_000
    for s in allsig:
        if s["idx"] - last < cooldown:
            continue
        kept.append(s); last = s["idx"]
    return kept


def metrics(sigs, ms, label):
    if not sigs:
        return f"{label}: n=0"
    nets = [s["net"] for s in sigs]
    yrs = years_span(ms)
    eq = 1.0; peak = 1.0; mdd = 0.0
    for s in sorted(sigs, key=lambda x:x["idx"]):
        if s["risk_pct"]>0:
            eq *= (1+0.005*(s["net"]/s["risk_pct"]))
            peak = max(peak, eq); mdd = max(mdd, (peak-eq)/peak*100)
    ann = (eq**(1/yrs)-1)*100
    mid = (ms[0]+ms[-1])/2
    h1 = [s["net"] for s in sigs if s["ms"]<mid]
    h2 = [s["net"] for s in sigs if s["ms"]>=mid]
    h1m = statistics.mean(h1) if h1 else 0; h2m = statistics.mean(h2) if h2 else 0
    return (f"{label}: n={len(sigs)} ({len(sigs)/yrs:.1f}/yr) "
            f"net/t={statistics.mean(nets):.3f}% tot={sum(nets):.1f}% "
            f"ann={ann:.2f}% maxDD={mdd:.1f}% "
            f"H1={h1m:.3f}%({len(h1)}) H2={h2m:.3f}%({len(h2)})")


def wider_regime(cache):
    """More permissive SLOWDOWN: ret30<-2%, slope down, recent_maxmove<2.0."""
    regime = build_regime(cache)
    reg = regime["reg"]; ret30 = regime["ret30"]; rmm = regime["recent_maxmove"]
    feats = cache["feats"]
    new = list(reg)
    for i in range(cache["n"]):
        f = feats[i]
        if not f:
            new[i] = None; continue
        if reg[i] == "CASCADE":
            continue
        if ret30[i] < -2.0 and f["trend_4h_slope"] <= -1 and rmm[i] < 2.0:
            new[i] = "SLOWDOWN"
    return new


if __name__ == "__main__":
    for tag in ["btc3y", "eth3y"]:
        c = load_cache(tag); ms = c["raw"]["ms"]
        regime = build_regime(c); reg = regime["reg"]
        base = base_signals(c)
        print(f"\n#### {tag} PORTFOLIO comparison")
        print("  " + metrics(base, ms, "CASCADE-ONLY (purity)"))
        # best slow placeholder = TP4.0/ttl168 (least-bad on 3y)
        slow = slow_signals(c, reg, ttl=168, targ_atr=4.0, streak=2)
        print("  " + metrics(slow, ms, "SLOW-only (TP4/ttl168, SLOWDOWN)"))
        port = merge(base, slow)
        added = len(port) - len(base)
        print("  " + metrics(port, ms, f"SWITCHED PORTFOLIO (+{added} slow trades)"))
        # wider regime
        regw = wider_regime(c)
        sharew = sum(1 for r in regw if r=="SLOWDOWN")/sum(1 for r in regw if r)
        sloww = slow_signals(c, regw, ttl=168, targ_atr=4.0, streak=2)
        portw = merge(base, sloww)
        print(f"  [wider regime SLOWDOWN share={sharew*100:.0f}%]")
        print("  " + metrics(sloww, ms, "SLOW-only WIDER regime"))
        print("  " + metrics(portw, ms, f"SWITCHED WIDER (+{len(portw)-len(base)})"))
