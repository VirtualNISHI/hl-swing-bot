"""REGIME-ADAPTIVE TWO-STRATEGY lens.

1. Quantify the true slow-bleed miss (downtrends with ZERO baseline trades).
2. Build a causal regime classifier (cascade / slow-grind-down / chop-up).
3. Test slow-capture rule candidates, routed only in slow-grind-down regime.
4. Backtest the SWITCHED portfolio vs cascade-only. split-half + cross-asset.

All from precomputed caches -> fast. Run per-tag.
"""
import sys, types, os, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_engine import (load_cache, run_variant, sig_baseline, stats, ann_05,
                         maxdd_05, years_span, split_half, FEE, resolve_short)

# ---------------------------------------------------------------------------
# Causal regime features, computed from cache arrays (close) + cached feats.
# ---------------------------------------------------------------------------
def build_regime(cache):
    raw = cache["raw"]; feats = cache["feats"]
    close = raw["close"]; n = cache["n"]
    reg = [None]*n
    ret30 = [0.0]*n         # 30d (720h) close return %
    atrpct_rank = [0.5]*n   # percentile of atr_pct vs trailing 720h
    recent_maxmove = [0.0]*n  # max move_per_atr last 48h
    # precompute move_per_atr series
    mpa = [feats[i]["move_per_atr"] if feats[i] else 0.0 for i in range(n)]
    atrp = [feats[i]["atr_pct"] if feats[i] else None for i in range(n)]
    for i in range(n):
        f = feats[i]
        if not f:
            continue
        if i >= 720 and close[i-720] > 0:
            ret30[i] = (close[i]/close[i-720]-1)*100
        # recent max move/ATR over last 48h
        lo = max(0, i-48)
        recent_maxmove[i] = max(mpa[lo:i+1]) if i > lo else mpa[i]
        # atr_pct percentile vs trailing 720h
        wlo = max(0, i-720)
        hist = [atrp[j] for j in range(wlo, i) if atrp[j] is not None]
        if hist and atrp[i] is not None:
            atrpct_rank[i] = sum(1 for x in hist if x <= atrp[i])/len(hist)
        # classify
        slope = f["trend_4h_slope"]; t4 = f["trend_4h"]
        if ret30[i] < 0 and recent_maxmove[i] >= 1.5:
            reg[i] = "CASCADE"
        elif ret30[i] < -3.0 and slope <= -1 and recent_maxmove[i] < 1.5:
            reg[i] = "SLOWDOWN"
        else:
            reg[i] = "CHOPUP"
    return {"reg": reg, "ret30": ret30, "atrpct_rank": atrpct_rank,
            "recent_maxmove": recent_maxmove}


# ---------------------------------------------------------------------------
# Slow-capture rule candidates (SHORT-only, designed to fire in grind-downs).
# ---------------------------------------------------------------------------
def make_slow_rules(regime):
    reg = regime["reg"]

    def in_slow(i):
        return reg[i] == "SLOWDOWN"

    # V1: relaxed onset (move>=0.5, no vol req), slope+streak gates kept
    def v1(i, f, ctx):
        if not in_slow(i):
            return False
        return (f["move_per_atr"] >= 0.5 and f["trend_4h"] <= -1
                and f["trend_4h_slope"] <= -1 and f["red_4h_streak"] >= 2)

    # V2: pure trend-follow, red_streak>=3 + slope down, no move/vol spike needed
    def v2(i, f, ctx):
        if not in_slow(i):
            return False
        return (f["trend_4h"] <= -1 and f["trend_4h_slope"] <= -1
                and f["red_4h_streak"] >= 3)

    # V3: deep-streak trend follow, streak>=4 (rarer, higher-conviction)
    def v3(i, f, ctx):
        if not in_slow(i):
            return False
        return (f["trend_4h"] <= -1 and f["trend_4h_slope"] <= -1
                and f["red_4h_streak"] >= 4)

    # V4: relaxed move only (move>=0.5), no streak floor, slope+trend gates
    def v4(i, f, ctx):
        if not in_slow(i):
            return False
        return (f["move_per_atr"] >= 0.5 and f["trend_4h"] <= -1
                and f["trend_4h_slope"] <= -1)

    # V5: pullback-short: fire when ret_4h slightly positive (bounce) inside a
    #     downtrend -> short the rip. ret_1h<0 still required by engine; use
    #     ret_4h in [-0.5*atr, +1.5*atr] window i.e. a stall/bounce.
    def v5(i, f, ctx):
        if not in_slow(i):
            return False
        atrp = f["atr_pct"]
        # recent 4h bounce: ret_4h between 0 and +1.2 ATR (a relief rally)
        r4 = f["ret_4h"]
        return (f["trend_4h"] <= -1 and f["trend_4h_slope"] <= -1
                and r4 > 0 and r4 <= 1.2*atrp)

    return {"V1_relaxed05_streak2": v1, "V2_trendfollow_streak3": v2,
            "V3_trendfollow_streak4": v3, "V4_relaxed05_nostreak": v4,
            "V5_pullback_short": v5}


def fmt(tag, name, sigs, ms):
    st = stats(sigs)
    if st["n"] == 0:
        return f"  {name}: n=0"
    ann, eq = ann_05(sigs, ms)
    yrs = years_span(ms)
    f1, f2 = split_half(sigs, ms)
    return (f"  {name}: n={st['n']} ({st['n']/yrs:.1f}/yr) "
            f"net/trade={st['net_mean']:.3f}% net_tot={st['net_total']:.1f}% "
            f"win={st['win']*100:.0f}% ann={ann:.2f}% | "
            f"H1 n={f1['n']} net={f1['net_mean']:.3f}% | "
            f"H2 n={f2['n']} net={f2['net_mean']:.3f}%")


def run_tag(tag):
    c = load_cache(tag)
    ms = c["raw"]["ms"]
    yrs = years_span(ms)
    regime = build_regime(c)
    reg = regime["reg"]
    # regime time share
    valid = [r for r in reg if r]
    share = {k: sum(1 for r in valid if r == k)/len(valid) for k in
             ["CASCADE", "SLOWDOWN", "CHOPUP"]}
    print(f"\n#### {tag} (span={yrs:.2f}y) regime share: "
          f"CASCADE={share['CASCADE']*100:.0f}% SLOWDOWN={share['SLOWDOWN']*100:.0f}% "
          f"CHOPUP={share['CHOPUP']*100:.0f}%")

    base = run_variant(c, sig_baseline, tag=tag)
    print(fmt(tag, "BASELINE(cascade-only)", base, ms))

    rules = make_slow_rules(regime)
    slow_results = {}
    for name, fn in rules.items():
        sigs = run_variant(c, fn, tag=tag)
        slow_results[name] = sigs
        print(fmt(tag, name, sigs, ms))
    return c, regime, base, slow_results


if __name__ == "__main__":
    tags = sys.argv[1:] or ["btc3y"]
    for t in tags:
        run_tag(t)
