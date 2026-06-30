"""Fast variant engine reading the precomputed feature cache.

Reproduces backtest signal+outcome semantics with cheap array ops so we can
sweep many variants without paying the O(n^2) recompute again.

Outcome model mirrors backtest._resolve_outcome:
  SHORT entry=close[i]; stop=entry+1.5*atr; target=entry-2.5*atr;
  walk j=i+1..i+72: if high[j]>=stop -> SL ; if low[j]<=target -> TP ;
  else EXPIRED at close[i+72]. realized gross = (entry/exit-1)*100.
  NET = gross - 0.19.
Cooldown: same-dir 4 bars, opp-dir 1 bar (we only do SHORT so same-dir=4h=4 bars).
"""
import pickle, os, statistics

SCRATCH = os.path.dirname(os.path.abspath(__file__))
FEE = 0.19
STOP_ATR = 1.5
TARG_ATR = 2.5
TTL = 72
COOLDOWN_BARS = 4  # same-direction 240min


def load_cache(tag):
    with open(os.path.join(SCRATCH, f"fcache_{tag}.pkl"), "rb") as fh:
        return pickle.load(fh)


def resolve_short(high, low, close, i, entry, atr, ttl=TTL):
    stop = entry + STOP_ATR * atr
    target = entry - TARG_ATR * atr
    end = min(i + ttl, len(close) - 1)
    for j in range(i + 1, end + 1):
        if high[j] >= stop:
            return "HIT_SL", (entry / stop - 1) * 100, j
        if low[j] <= target:
            return "HIT_TP", (entry / target - 1) * 100, j
    return "EXPIRED", (entry / close[end] - 1) * 100, end


def run_variant(cache, signal_fn, ttl=TTL, cooldown=COOLDOWN_BARS, tag=""):
    """signal_fn(i, f, ctx) -> True if a SHORT should fire at bar i.

    Returns list of signal dicts: idx, ms, entry, stop, status, gross, net, atr.
    """
    feats = cache["feats"]
    raw = cache["raw"]
    high, low, close, ms = raw["high"], raw["low"], raw["close"], raw["ms"]
    n = cache["n"]
    sigs = []
    last_idx = -10_000
    ctx = {}
    for i in range(len(feats)):
        f = feats[i]
        if not f:
            continue
        atr = f["atr_1h"]
        if atr <= 0:
            continue
        # ret_1h>0 would be LONG; short_only -> skip up-bars (mirror harness:
        # direction = LONG if ret_1h>0 else SHORT)
        if f["ret_1h"] > 0:
            continue
        if (i - last_idx) < cooldown:
            continue
        if not signal_fn(i, f, ctx):
            continue
        entry = f["close"]
        status, gross, exit_idx = resolve_short(high, low, close, i, entry, atr, ttl)
        net = gross - FEE
        risk_pct = (STOP_ATR * atr) / entry * 100.0
        sigs.append({
            "idx": i, "ms": ms[i], "entry": entry, "stop": entry + STOP_ATR * atr,
            "status": status, "gross": gross, "net": net, "atr": atr,
            "risk_pct": risk_pct, "exit_idx": exit_idx,
        })
        last_idx = i
    return sigs


# ---- baseline signal (shipped) ----
def sig_baseline(i, f, ctx):
    score = (0.30*abs(f["move_per_atr_z"]) + 0.25*abs(f["robust_z_168"])
             + 0.20*f["vol_z_168"] + 0.15*abs(f["ret_4h"])/max(f["atr_pct"],1e-9)
             + 0.10*1.0)
    return (score >= 3.0 and f["move_per_atr"] >= 1.0 and f["vol_z_168"] >= 1.0
            and f["trend_4h"] <= -1 and f["trend_4h_slope"] <= -1
            and f["red_4h_streak"] >= 2)


# ---- metrics ----
def years_span(ms_list):
    if len(ms_list) < 2:
        return 1.0
    return (ms_list[-1] - ms_list[0]) / (365.25*24*3600*1000)


def stats(sigs):
    if not sigs:
        return {"n": 0, "net_mean": 0.0, "net_total": 0.0, "win": 0.0,
                "tp": 0, "sl": 0, "exp": 0}
    nets = [s["net"] for s in sigs]
    return {
        "n": len(sigs),
        "net_mean": statistics.mean(nets),
        "net_median": statistics.median(nets),
        "net_total": sum(nets),
        "win": sum(1 for x in nets if x > 0)/len(nets),
        "tp": sum(1 for s in sigs if s["status"]=="HIT_TP"),
        "sl": sum(1 for s in sigs if s["status"]=="HIT_SL"),
        "exp": sum(1 for s in sigs if s["status"]=="EXPIRED"),
        "best": max(nets), "worst": min(nets),
    }


def ann_05(sigs, ms_list, risk_frac=0.005):
    eq = 1.0
    for s in sorted(sigs, key=lambda x: x["idx"]):
        rp = s["risk_pct"]
        if rp <= 0:
            continue
        R = s["net"] / rp
        eq *= (1.0 + risk_frac * R)
        if eq <= 0:
            eq = 1e-9; break
    yrs = years_span(ms_list)
    ann = (eq ** (1.0/yrs) - 1.0) * 100.0 if yrs > 0 else 0.0
    return ann, eq


def maxdd_05(sigs, risk_frac=0.005):
    eq = 1.0; peak = 1.0; mdd = 0.0
    for s in sorted(sigs, key=lambda x: x["idx"]):
        rp = s["risk_pct"]
        if rp <= 0:
            continue
        eq *= (1.0 + risk_frac * (s["net"]/rp))
        peak = max(peak, eq)
        mdd = max(mdd, (peak-eq)/peak*100.0)
    return eq, mdd


def split_half(sigs, ms_list):
    if not ms_list:
        return {}, {}
    mid_ms = (ms_list[0] + ms_list[-1]) / 2
    first = [s for s in sigs if s["ms"] < mid_ms]
    second = [s for s in sigs if s["ms"] >= mid_ms]
    return stats(first), stats(second)
