"""LENS: longer holds / trend-riding exits on the EXISTING bot entries.

We do NOT change entries. We take run_backtest(short_only=True) signal indices
(baseline shipped config: slope_gate=True, red_streak_min=2) and replace the exit
logic on those same entries, testing whether longer holds / trailing / trend-flip
exits convert the bot's existing entries into trend-capture.

Strict evidence: NET = gross - 0.19. split-half (1st 1.5y vs last 1.5y), cross-asset
(BTC & ETH), HL 208d check. Annualized return at 0.5%-equity-risk sizing.
"""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')  # avoid CPython3.13 segfault

import csv, statistics, math
from hl_swing_bot.backtest import HourlyBar, run_backtest, _compute_features_at
from hl_swing_bot.features import aggregate_to_4h, wilder_atr, ATR_PERIOD

SCRATCH = r"C:\User\projects\hl-swing-bot\scratch"
FEE = 0.19  # round-trip fees+slippage, subtract from gross realized %

def load_bars(path):
    bars = []
    with open(path, newline="") as f:
        r = csv.reader(f)
        header = next(r)
        for row in r:
            # open_time_ms,open,high,low,close,volume,trades[,taker_buy_base]
            bars.append(HourlyBar(
                int(float(row[0])), float(row[1]), float(row[2]), float(row[3]),
                float(row[4]), float(row[5]), int(float(row[6])),
            ))
    return bars

def precompute_atr(bars):
    return wilder_atr(bars)

# ---------------------------------------------------------------------------
# Exit replacement engines. Each takes the entry context and walks forward,
# returning gross realized % (SHORT: (entry/exit - 1)*100) and exit_idx.
# Entry, stop, atr_at_entry come from the baseline signal.
# ---------------------------------------------------------------------------

def exit_fixed_tp(bars, entry_idx, entry, stop, atr, *, ttl, target_mult):
    """Baseline-style: fixed TP at target_mult*ATR, hard stop, TTL expiry."""
    target = entry - target_mult * atr
    end = min(entry_idx + ttl, len(bars) - 1)
    for j in range(entry_idx + 1, end + 1):
        b = bars[j]
        if b.high >= stop:
            return (entry / stop - 1) * 100, j, "SL"
        if b.low <= target:
            return (entry / target - 1) * 100, j, "TP"
    c = bars[end].close
    return (entry / c - 1) * 100, end, "EXP"

def exit_ttl_only(bars, entry_idx, entry, stop, atr, *, ttl):
    """Hard stop + extended TTL, no TP (ride to expiry)."""
    end = min(entry_idx + ttl, len(bars) - 1)
    for j in range(entry_idx + 1, end + 1):
        b = bars[j]
        if b.high >= stop:
            return (entry / stop - 1) * 100, j, "SL"
    c = bars[end].close
    return (entry / c - 1) * 100, end, "EXP"

def exit_chandelier(bars, entry_idx, entry, stop, atr, *, ttl, k):
    """Chandelier trail for SHORT: trail stop = lowest_low_since_entry + k*ATR_now.
    Hard initial stop also active. Exit when high crosses the (tighter of) trail/stop."""
    end = min(entry_idx + ttl, len(bars) - 1)
    lowest = bars[entry_idx].low
    cur_stop = stop
    for j in range(entry_idx + 1, end + 1):
        b = bars[j]
        # update trail using ATR at j (precomputed global atr array via closure)
        atr_j = ATR_ARR[j] if ATR_ARR[j] > 0 else atr
        trail = lowest + k * atr_j
        eff_stop = min(cur_stop, trail)  # never loosen above initial stop
        if b.high >= eff_stop:
            return (entry / eff_stop - 1) * 100, j, "TRAIL"
        lowest = min(lowest, b.low)
        cur_stop = eff_stop
    c = bars[end].close
    return (entry / c - 1) * 100, end, "EXP"

def exit_trend_flip(bars, entry_idx, entry, stop, atr, *, ttl, mode):
    """Exit only when 4h trend flips up. mode='sma' -> close>SMA50(4h);
    mode='slope' -> 4h SMA50 slope turns >=0. Hard stop active. TTL cap."""
    end = min(entry_idx + ttl, len(bars) - 1)
    for j in range(entry_idx + 1, end + 1):
        b = bars[j]
        if b.high >= stop:
            return (entry / stop - 1) * 100, j, "SL"
        # check 4h trend flip using bars up to j
        flip = TREND_FLIP[mode][j]
        if flip:
            return (entry / b.close - 1) * 100, j, "FLIP"
    c = bars[end].close
    return (entry / c - 1) * 100, end, "EXP"

def exit_scaleout(bars, entry_idx, entry, stop, atr, *, ttl, first_mult, runner_k):
    """Scale out: 50% at first_mult*ATR TP, move stop to BE on remainder, trail
    runner with chandelier k=runner_k. Hard stop on full size before first TP."""
    end = min(entry_idx + ttl, len(bars) - 1)
    first_tp = entry - first_mult * atr
    half_done = False
    realized_half = 0.0
    lowest = bars[entry_idx].low
    cur_stop = stop
    for j in range(entry_idx + 1, end + 1):
        b = bars[j]
        if not half_done:
            if b.high >= cur_stop:
                return (entry / cur_stop - 1) * 100, j, "SL"
            if b.low <= first_tp:
                realized_half = 0.5 * (entry / first_tp - 1) * 100
                half_done = True
                cur_stop = entry  # BE on runner
                lowest = min(lowest, b.low)
                continue
        else:
            atr_j = ATR_ARR[j] if ATR_ARR[j] > 0 else atr
            trail = lowest + runner_k * atr_j
            eff_stop = min(cur_stop, trail)
            if b.high >= eff_stop:
                runner = 0.5 * (entry / eff_stop - 1) * 100
                return realized_half + runner, j, "TRAIL"
            lowest = min(lowest, b.low)
            cur_stop = eff_stop
    c = bars[end].close
    if not half_done:
        return (entry / c - 1) * 100, end, "EXP"
    runner = 0.5 * (entry / c - 1) * 100
    return realized_half + runner, end, "EXP"

# globals set per-asset
ATR_ARR = []
TREND_FLIP = {}

def build_trend_flip(bars):
    """Precompute, for each 1h idx j, whether a 4h trend-flip-up is active as of bar j.
    sma: close(4h last)>SMA50(4h). slope: SMA50 now >= SMA50 10 bars ago.
    Computed on the 4h aggregation; mapped back to the 1h idx of each 4h bucket's last bar.
    """
    flip_sma = [False] * len(bars)
    flip_slope = [False] * len(bars)
    # Build 4h buckets incrementally is O(n^2); instead aggregate once and map by ms.
    bars4 = aggregate_to_4h(bars)
    # map each 4h bar to the 1h index range it covers (its last 1h bar idx)
    # bucket start ms -> we know each 4h close corresponds to last 1h bar in bucket.
    BUCKET_MS = 4 * 60 * 60 * 1000
    # index 1h bars by hour_ms
    ms_to_idx = {b.hour_ms: i for i, b in enumerate(bars)}
    closes4 = [b.close for b in bars4]
    for k in range(len(bars4)):
        if k < 50:
            continue
        sma50 = statistics.mean(closes4[k-50:k])  # 50 prior (excl current), mirror feature uses [-51:-1]
        is_up_sma = bars4[k].close > sma50
        if k >= 60:
            sma50_prev = statistics.mean(closes4[k-60:k-10])
            is_up_slope = sma50 >= sma50_prev
        else:
            is_up_slope = False
        # last 1h bar of this 4h bucket
        bstart = bars4[k].hour_ms
        last_ms = bstart + BUCKET_MS - 60*60*1000
        # find the actual last 1h idx within bucket (<= last_ms)
        idx = None
        for off in range(3, -1, -1):
            cand = bstart + off*60*60*1000
            if cand in ms_to_idx:
                idx = ms_to_idx[cand]
                break
        if idx is None:
            continue
        # the flip becomes "known" only after this 4h bar closes; apply from next 1h bar onward
        # mark all 1h idx >= idx until next bucket's idx
        nxt = None
        if k+1 < len(bars4):
            nbstart = bars4[k+1].hour_ms
            for off in range(0, 4):
                cand = nbstart + off*60*60*1000
                if cand in ms_to_idx:
                    nxt = ms_to_idx[cand]
                    break
        hi = nxt if nxt is not None else len(bars)
        for jj in range(idx, hi):
            flip_sma[jj] = is_up_sma
            flip_slope[jj] = is_up_slope
    return {"sma": flip_sma, "slope": flip_slope}

def get_baseline_signals(bars):
    """Shipped config: short_only, slope_gate=True, red_streak_min=2 (defaults)."""
    res = run_backtest(bars, short_only=True)
    return res

def annualized_return(realized_net_list, exit_idx_list, entry_idx_list, bars, *, risk_frac=0.005):
    """R-multiple equity path at fixed fractional risk. Risk per trade defined by the
    baseline stop distance => realized_net% is on price; we convert to R using the
    stop distance at entry. But simpler & consistent with prompt: size each trade so
    that a move to the hard stop loses risk_frac of equity. R = realized_net / stop_pct.
    Equity compounds. Annualize by total span in years.
    """
    # need stop_pct per trade; passed separately
    raise NotImplementedError

def equity_path(trades, bars, *, risk_frac=0.005):
    """trades: list of dicts with net_pct (post-fee) and stop_pct (abs % distance entry->stop).
    Size = risk_frac / stop_pct of equity (in 'price exposure' terms). PnL fraction of
    equity = size * net_pct/100 ... but net_pct is the price return on the position.
    Position return on equity = (net_pct/100) * (notional/equity). With risk-based sizing,
    notional/equity = risk_frac / (stop_pct/100). So equity_mult per trade =
    1 + (net_pct/100) * risk_frac / (stop_pct/100) = 1 + risk_frac * net_pct/stop_pct.
    => equity *= (1 + risk_frac * R) where R = net_pct/stop_pct.
    """
    eq = 1.0
    for t in trades:
        sp = t["stop_pct"]
        if sp <= 0:
            continue
        R = t["net_pct"] / sp
        eq *= (1 + risk_frac * R)
        if eq <= 0:
            eq = 1e-9
    return eq

def years_span(bars):
    return (bars[-1].hour_ms - bars[0].hour_ms) / (1000*60*60*24*365.25)

def summarize(trades):
    if not trades:
        return dict(n=0, net_mean=0.0, net_total=0.0, winrate=0.0, med_hold=0.0)
    nets = [t["net_pct"] for t in trades]
    holds = [t["hold"] for t in trades]
    return dict(
        n=len(trades),
        net_mean=statistics.mean(nets),
        net_total=sum(nets),
        net_median=statistics.median(nets),
        winrate=sum(1 for x in nets if x > 0)/len(nets),
        med_hold=statistics.median(holds),
        best=max(nets), worst=min(nets),
    )

if __name__ == "__main__":
    import json
    for asset, path in [("BTC", f"{SCRATCH}\\binance_btc_3y.csv"),
                        ("ETH", f"{SCRATCH}\\binance_eth_3y.csv")]:
        bars = load_bars(path)
        print(f"{asset}: {len(bars)} bars, span {years_span(bars):.2f}y, "
              f"{bars[0].hour_ms} .. {bars[-1].hour_ms}")
        res = get_baseline_signals(bars)
        print(f"  baseline n_signals={res.get('n_signals')}, "
              f"exp_post_slip={res.get('expectancy_pct_post_slippage'):.4f}")
