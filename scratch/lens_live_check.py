"""Inspect the live HL bleed: did SLOWDOWN regime fire, what would slow rules do,
and run the slow-capture rule + exit grid on HL 208d (live instrument check).
"""
import sys, types, os, statistics, datetime
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_engine import load_cache, run_variant, sig_baseline, stats, years_span
from lens_regime import build_regime
from lens_slowexits import run as run_ex, st as st_ex


def describe_recent(tag, weeks=4):
    c = load_cache(tag)
    raw = c["raw"]; close = raw["close"]; ms = raw["ms"]; n = c["n"]
    regime = build_regime(c); reg = regime["reg"]; ret30 = regime["ret30"]
    rmm = regime["recent_maxmove"]
    # find the largest peak->trough drawdown in last `weeks*168` bars
    w = weeks*168
    lo = max(0, n-w)
    seg = close[lo:]
    peak = seg[0]; peak_i = lo; mdd = 0; trough_i = lo
    for k in range(lo, n):
        if close[k] > peak:
            peak = close[k]; peak_i = k
        dd = (peak - close[k]) / peak * 100
        if dd > mdd:
            mdd = dd; trough_i = k; tp_peak_i = peak_i
    d0 = datetime.datetime.utcfromtimestamp(ms[tp_peak_i]/1000).strftime("%Y-%m-%d")
    d1 = datetime.datetime.utcfromtimestamp(ms[trough_i]/1000).strftime("%Y-%m-%d")
    print(f"\n#### {tag}: last {weeks}w worst drop {mdd:.1f}% {d0}->{d1} "
          f"({trough_i-tp_peak_i}h)")
    # regime composition during that episode
    ep = reg[tp_peak_i:trough_i+1]
    from collections import Counter
    cnt = Counter(x for x in ep if x)
    tot = sum(cnt.values()) or 1
    print("   regime during episode:", {k: f"{v/tot*100:.0f}%" for k,v in cnt.items()})
    # max 1h down move in episode
    maxdown = 0
    for k in range(tp_peak_i+1, trough_i+1):
        r = (close[k]/close[k-1]-1)*100
        maxdown = min(maxdown, r)
    print(f"   worst single 1h move in episode: {maxdown:.2f}%  "
          f"(slow-bleed if > -3%: {maxdown > -3.0})")
    # baseline trades inside episode
    base = run_variant(c, sig_baseline)
    inside = [s for s in base if tp_peak_i <= s["idx"] <= trough_i]
    print(f"   BASELINE trades inside episode: {len(inside)} "
          f"(net each: {[round(s['net'],2) for s in inside]})")
    return c, regime


if __name__ == "__main__":
    for tag in ["btchl", "ethhl"]:
        c, regime = describe_recent(tag, weeks=4)
        ms = c["raw"]["ms"]; reg = regime["reg"]
        def slowgate(i, f, ctx):
            return (reg[i] == "SLOWDOWN" and f["trend_4h"] <= -1
                    and f["trend_4h_slope"] <= -1 and f["red_4h_streak"] >= 2)
        # share
        valid = [r for r in reg if r]
        from collections import Counter
        cnt = Counter(valid); tot = sum(cnt.values())
        print(f"   {tag} regime share: " +
              " ".join(f"{k}={cnt[k]/tot*100:.0f}%" for k in ["CASCADE","SLOWDOWN","CHOPUP"]))
        print(f"   slow rule on HL 208d exit grid:")
        for name, kw in [
            ("TP2.5/SL1.5/ttl72", dict(ttl=72, targ_atr=2.5)),
            ("TP4.0/SL1.5/ttl168", dict(ttl=168, targ_atr=4.0)),
            ("trail1.5/ttl168", dict(ttl=168, targ_atr=0.0, trail_atr=1.5)),
            ("timeexit ttl72", dict(ttl=72, targ_atr=0.0)),
        ]:
            sigs = run_ex(c, slowgate, **kw)
            print(f"     {name:20s}: {st_ex(sigs, ms)}")
