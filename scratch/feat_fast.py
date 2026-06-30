"""Allocation-light reimplementation of backtest._compute_features_at.

Validated to be byte-identical (same signals) to the module on btc3y/HL, then
used to build the eth3y cache (the module's growing-slice + generator approach
corrupts CPython 3.13 memory on the eth3y data).

Mirrors exactly:
  - wilder_atr (period 14): one ATR per bar, 0.0 warmup, RMA recursion.
  - move_per_atr = |ret_1h| / atr_pct ; atr_pct = atr/close*100
  - robust_z(value, hist) = (v-med)/(1.4826*MAD), 0 if <10 or mad<=0
  - robust_z_168: z of close vs prior 168 closes (sub[-169:-1])
  - vol_z_168:    z of volume vs prior 168 volumes
  - move_per_atr_z: z of move_per_atr vs hist_moves over that 168 window
  - 4h aggregation UTC-aligned; SMA50 over bars_4h[-51:-1]; trend_4h sign;
    slope: SMA50(bars_4h[-51:-1]) vs SMA50(bars_4h[-61:-11])
  - red_4h_streak: consecutive red 4h bars from the end (incl. partial bucket)
"""
import statistics, math

ATR_PERIOD = 14
HIST_LOOKBACK = 168
MIN_BARS = max(ATR_PERIOD + 5, 60)
BUCKET_MS = 4*60*60*1000


def robust_z(value, hist):
    h = [x for x in hist if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if len(h) < 10:
        return 0.0
    med = statistics.median(h)
    mad = statistics.median([abs(x-med) for x in h]) or 0.0
    if mad <= 0:
        return 0.0
    return (value - med) / (1.4826 * mad)


def wilder_atr_series(high, low, close):
    n = len(close)
    tr = [0.0]*n
    for i in range(n):
        if i == 0:
            tr[i] = high[i]-low[i]
        else:
            pc = close[i-1]
            tr[i] = max(high[i]-low[i], abs(high[i]-pc), abs(low[i]-pc))
    atr = [0.0]*n
    rma = None
    for i in range(n):
        if i < ATR_PERIOD:
            if i == ATR_PERIOD-1:
                rma = sum(tr[:ATR_PERIOD])/ATR_PERIOD
                atr[i] = rma
        else:
            rma = (rma*(ATR_PERIOD-1)+tr[i])/ATR_PERIOD
            atr[i] = rma
    return atr


def build_4h(ms, o, h, l, c, vol):
    """Return list of 4h bars as tuples (start_ms, open, high, low, close, isred)
    plus an array hour_to_4hidx mapping each hourly idx -> index into the 4h
    list of the bucket it belongs to (the bucket as completed THROUGH that hour).
    We rebuild incrementally: maintain running bucket; close it when start changes.
    Returns full 4h list AND, for each hourly i, the count of COMPLETE 4h bars
    up to and including the partial bucket ending at i (so slicing matches module
    which calls aggregate_to_4h(sub) where sub=bars[:i+1])."""
    n = len(ms)
    four_close = []   # close of each 4h bar
    four_open = []
    four_isred = []
    four_start = []
    # For each hourly i, we need the 4h list as it would be for sub=bars[:i+1].
    # The 4h list grows by 1 only when a NEW bucket starts. The LAST 4h bar is
    # always the partial bucket ending at i. We store, per i, (count4h, last_open,
    # last_close, last_isred) and access historical closes via four_close arrays
    # snapshotted. Since SMA50 uses bars_4h[-51:-1] (excludes the partial last),
    # and slope uses [-61:-11], we need COMPLETED 4h closes only for those.
    # Strategy: maintain completed_closes (list) appended when bucket closes, and
    # track current partial bucket (open, close, isred). For bar i, the 4h list =
    # completed_closes + [partial]. So:
    #   bars_4h[-1]    = partial (open_p, close_p)
    #   bars_4h[-51:-1] = completed_closes[-50:]
    #   bars_4h[-61:-11]= completed_closes[-60:-10]
    # red_4h_streak counts from partial backward over [partial]+completed.
    completed_close = []
    completed_isred = []
    cur_start = None
    cur_open = None
    cur_close = None
    # per-hour snapshots needed for features:
    per = []  # (comp_close_ref_len, partial_open, partial_close, partial_isred)
    for i in range(n):
        start = ms[i] - (ms[i] % BUCKET_MS)
        if cur_start is None:
            cur_start = start; cur_open = o[i]; cur_close = c[i]
        elif start != cur_start:
            # close previous bucket
            completed_close.append(cur_close)
            completed_isred.append(cur_close < cur_open)
            cur_start = start; cur_open = o[i]; cur_close = c[i]
        else:
            cur_close = c[i]
        per.append((len(completed_close), cur_open, cur_close, cur_open > cur_close))
    return completed_close, completed_isred, per


def compute_all(raw):
    """Return list feats[i] (dict or None) matching _compute_features_at."""
    ms = raw["ms"]; o = raw["open"]; h = raw["high"]; l = raw["low"]
    c = raw["close"]; vol = raw["vol"]
    n = len(c)
    atr = wilder_atr_series(h, l, c)
    completed_close, completed_isred, per = build_4h(ms, o, h, l, c, vol)
    feats = [None]*n
    # move_per_atr series for the z window
    mpa = [0.0]*n
    atr_pct = [0.0]*n
    for i in range(n):
        if atr[i] > 0 and c[i] > 0:
            atr_pct[i] = atr[i]/c[i]*100
            r1 = (c[i]/c[i-1]-1)*100 if i >= 1 and c[i-1] > 0 else 0.0
            mpa[i] = abs(r1)/atr_pct[i] if atr_pct[i] > 0 else 0.0
    for i in range(n):
        if i < MIN_BARS:
            continue
        if atr[i] <= 0 or c[i] <= 0:
            continue
        ap = atr_pct[i]
        if ap <= 0:
            continue
        ret_1h = (c[i]/c[i-1]-1)*100 if c[i-1] > 0 else 0.0
        ret_4h = (c[i]/c[i-4]-1)*100 if i >= 4 and c[i-4] > 0 else 0.0
        move_per_atr = abs(ret_1h)/ap
        # hist window sub[-169:-1] -> closes[max(0,i-168) .. i-1]
        lo = max(0, i-HIST_LOOKBACK)
        hist_close = c[lo:i]
        hist_vol = vol[lo:i]
        if len(hist_close) < 30:
            continue
        robust_z_close = robust_z(c[i], hist_close)
        vol_z = robust_z(vol[i], hist_vol)
        # hist_moves: module loops j in range(len(sub)-len(hist)-1, len(sub)-1)
        # = range(lo, i). Guards: j>=1, atr[j]>0, close[j]>0, close[j-1]>0.
        hist_moves = []
        for j in range(lo, i):
            if j < 1 or atr[j] <= 0 or c[j] <= 0 or c[j-1] <= 0:
                continue
            m_atr = atr[j]/c[j]*100
            if m_atr <= 0:
                continue
            hist_moves.append(abs((c[j]/c[j-1]-1)*100)/m_atr)
        move_per_atr_z = robust_z(move_per_atr, hist_moves) if hist_moves else 0.0
        # 4h trend/slope/streak
        ncomp, p_open, p_close, p_isred = per[i]
        comp_close = completed_close[:ncomp]
        comp_isred = completed_isred[:ncomp]
        # bars_4h = comp + [partial]; need >=51 for sma50 and >=61 for slope
        total4 = ncomp + 1
        if total4 >= 51:
            # bars_4h[-51:-1] = last 50 of (comp+[partial]) excluding partial
            # = comp_close[-50:]
            sma50 = statistics.mean(comp_close[-50:])
            trend_4h = 1 if p_close > sma50 else (-1 if p_close < sma50 else 0)
        else:
            trend_4h = 0; sma50 = None
        if total4 >= 61 and sma50 is not None:
            sma50_prev = statistics.mean(comp_close[-60:-10])
            trend_4h_slope = -1 if sma50 < sma50_prev else (1 if sma50 > sma50_prev else 0)
        else:
            trend_4h_slope = 0
        # red_4h_streak: from partial backward
        red = 0
        if p_isred:
            red += 1
            k = ncomp-1
            while k >= 0:
                if comp_isred[k]:
                    red += 1; k -= 1
                else:
                    break
        else:
            red = 0
        feats[i] = {
            "close": c[i], "atr_1h": atr[i], "atr_pct": ap,
            "ret_1h": ret_1h, "ret_4h": ret_4h,
            "move_per_atr": move_per_atr, "move_per_atr_z": move_per_atr_z,
            "robust_z_168": robust_z_close, "vol_z_168": vol_z,
            "trend_4h": trend_4h, "trend_4h_slope": trend_4h_slope,
            "red_4h_streak": red, "funding_z_24": 0.0,
        }
    return feats
