"""Shared helpers for the regime-adaptive lens. Stub duckdb FIRST."""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')

import csv, math, statistics, os
from hl_swing_bot.backtest import HourlyBar, run_backtest, _compute_features_at  # noqa

FEE = 0.19  # round-trip net cost in % (fees+slippage). Net = gross - 0.19
SCRATCH = os.path.dirname(os.path.abspath(__file__))


def load_bars(path):
    """Load CSV -> (bars list, taker_buy_base parallel array or None)."""
    if not os.path.isabs(path):
        path = os.path.join(SCRATCH, path)
    bars = []
    tbb = []
    with open(path, newline="") as fh:
        r = csv.DictReader(fh)
        for row in r:
            bars.append(HourlyBar(
                int(row["open_time_ms"]),
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
                float(row["volume"]), int(float(row["trades"])),
            ))
            tbb.append(float(row["taker_buy_base"]) if "taker_buy_base" in row and row["taker_buy_base"] not in (None, "") else None)
    if all(x is None for x in tbb):
        tbb = None
    return bars, tbb


def net_realized(sig):
    """NET realized % for a signal dict (from run_backtest 'signals')."""
    return sig["realized_pct"] - FEE


def summarize_net(sigs):
    """Given list of signal dicts, return net stats."""
    if not sigs:
        return {"n": 0, "net_mean": 0.0, "net_total": 0.0, "win_rate": 0.0}
    nets = [net_realized(s) for s in sigs]
    wins = sum(1 for x in nets if x > 0)
    return {
        "n": len(sigs),
        "net_mean": statistics.mean(nets),
        "net_median": statistics.median(nets),
        "net_total": sum(nets),
        "win_rate": wins / len(sigs),
        "best": max(nets),
        "worst": min(nets),
    }


def years_span(bars):
    if len(bars) < 2:
        return 1.0
    ms = bars[-1].hour_ms - bars[0].hour_ms
    return ms / (365.25 * 24 * 3600 * 1000)


def annualized_return_05pct(sigs, bars, risk_frac=0.005):
    """Equity path at 0.5%-equity risk per trade.

    R-multiple: risk per trade = STOP_ATR_MULT*atr from entry to stop.
    realized_pct (gross) / stop_distance_pct = R. We don't have stop_distance
    per signal in the summary list directly, but entry & stop ARE in the dict.
    R = net_realized_pct / risk_pct, where risk_pct = |entry-stop|/entry*100.
    Equity *= (1 + risk_frac * R). Annualize by geometric span.
    """
    eq = 1.0
    for s in sorted(sigs, key=lambda x: x["idx"]):
        if s.get("stop") is None or s.get("entry") in (None, 0):
            continue
        risk_pct = abs(s["entry"] - s["stop"]) / s["entry"] * 100.0
        if risk_pct <= 0:
            continue
        net = net_realized(s)
        R = net / risk_pct
        eq *= (1.0 + risk_frac * R)
        if eq <= 0:
            eq = 1e-9
            break
    yrs = years_span(bars)
    if yrs <= 0:
        return 0.0, eq, 1.0
    ann = (eq ** (1.0 / yrs) - 1.0) * 100.0
    return ann, eq, yrs


def equity_maxdd(sigs, risk_frac=0.005):
    """Equity path + max drawdown (%) at 0.5% risk sizing."""
    eq = 1.0
    peak = 1.0
    maxdd = 0.0
    path = []
    for s in sorted(sigs, key=lambda x: x["idx"]):
        if s.get("stop") is None or s.get("entry") in (None, 0):
            continue
        risk_pct = abs(s["entry"] - s["stop"]) / s["entry"] * 100.0
        if risk_pct <= 0:
            continue
        net = net_realized(s)
        R = net / risk_pct
        eq *= (1.0 + risk_frac * R)
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100.0
        maxdd = max(maxdd, dd)
        path.append(eq)
    return eq, maxdd, path
