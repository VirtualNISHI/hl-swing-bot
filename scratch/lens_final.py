"""Final evidence table: every slow-capture variant's strict pass/fail.

Pass requires ALL: 3y net/trade>0 (BTC AND ETH), split-half both halves net>0
(BTC AND ETH), HL 208d same sign (BTC AND ETH). Flag n<20 cells.
"""
import sys, types, os, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_engine import load_cache, run_variant, sig_baseline, years_span
from lens_regime import build_regime
from lens_slowexits import run as run_ex

CACHE = {t: load_cache(t) for t in ["btc3y","eth3y","btchl","ethhl"]}
REG = {t: build_regime(CACHE[t]) for t in CACHE}


def half_nets(sigs, ms):
    if not sigs: return (None,None,0,0)
    mid = (ms[0]+ms[-1])/2
    h1 = [s["net"] for s in sigs if s["ms"]<mid]
    h2 = [s["net"] for s in sigs if s["ms"]>=mid]
    return (statistics.mean(h1) if h1 else None,
            statistics.mean(h2) if h2 else None, len(h1), len(h2))


def netmean(sigs):
    return statistics.mean([s["net"] for s in sigs]) if sigs else None


def slowfn_for(tag, streak=2, move=None):
    reg = REG[tag]["reg"]
    def fn(i, f, ctx):
        if reg[i] != "SLOWDOWN": return False
        if not (f["trend_4h"]<=-1 and f["trend_4h_slope"]<=-1): return False
        if move is not None and f["move_per_atr"] < move: return False
        return f["red_4h_streak"] >= streak
    return fn


VARIANTS = [
    ("relaxed_move0.5_streak2 / TP2.5 ttl72", dict(streak=2, move=0.5), dict(ttl=72, targ_atr=2.5)),
    ("trendfollow streak3 / TP2.5 ttl72",     dict(streak=3, move=None), dict(ttl=72, targ_atr=2.5)),
    ("trendfollow streak2 / TP4.0 ttl168",    dict(streak=2, move=None), dict(ttl=168, targ_atr=4.0)),
    ("trendfollow streak2 / trail1.5 ttl168", dict(streak=2, move=None), dict(ttl=168, targ_atr=0.0, trail_atr=1.5)),
    ("trendfollow streak2 / timeexit ttl72",  dict(streak=2, move=None), dict(ttl=72, targ_atr=0.0)),
]

print("VARIANT | BTC3y net/t | ETH3y net/t | BTC H1/H2 | ETH H1/H2 | BTC-HL | ETH-HL | VERDICT")
for name, sfk, exk in VARIANTS:
    row = {}
    for tag in ["btc3y","eth3y","btchl","ethhl"]:
        fn = slowfn_for(tag, **sfk)
        sigs = run_ex(CACHE[tag], fn, **exk)
        ms = CACHE[tag]["raw"]["ms"]
        row[tag] = (netmean(sigs), half_nets(sigs, ms), len(sigs))
    b3 = row["btc3y"]; e3 = row["eth3y"]; bh = row["btchl"]; eh = row["ethhl"]
    def pos(x): return x is not None and x > 0
    b3h = b3[1]; e3h = e3[1]
    split_ok = pos(b3h[0]) and pos(b3h[1]) and pos(e3h[0]) and pos(e3h[1])
    cross_3y = pos(b3[0]) and pos(e3[0])
    hl_ok = pos(bh[0]) and pos(eh[0])
    verdict = "PASS" if (cross_3y and split_ok and hl_ok) else "REJECTED"
    flag = ""
    for tag in ["btc3y","eth3y","btchl","ethhl"]:
        h1n = row[tag][1][2]; h2n = row[tag][1][3]
        if min(h1n,h2n) < 20: flag += f" n<20({tag}:{min(h1n,h2n)})"
    print(f"\n{name}")
    print(f"  BTC3y net/t={b3[0]:.3f}% (n={b3[2]})  ETH3y net/t={e3[0]:.3f}% (n={e3[2]})")
    print(f"  BTC split H1={b3h[0]:.3f}%/H2={b3h[1]:.3f}%  ETH split H1={e3h[0]:.3f}%/H2={e3h[1]:.3f}%")
    print(f"  HL-BTC net/t={bh[0]:.3f}% (n={bh[2]})  HL-ETH net/t={eh[0]:.3f}% (n={eh[2]})")
    print(f"  -> cross3y_pos={cross_3y} split_ok={split_ok} hl_same_sign={hl_ok} => {verdict}{flag}")

# baseline reference
print("\n=== BASELINE cascade-only reference (net/trade) ===")
for tag in ["btc3y","eth3y","btchl","ethhl"]:
    sigs = run_variant(CACHE[tag], sig_baseline)
    ms = CACHE[tag]["raw"]["ms"]; yrs = years_span(ms)
    h1,h2,n1,n2 = half_nets(sigs, ms)
    print(f"  {tag}: net/t={netmean(sigs):.3f}% n={len(sigs)} ({len(sigs)/yrs:.1f}/yr) "
          f"H1={h1:.3f}%({n1}) H2={h2:.3f}%({n2})")
