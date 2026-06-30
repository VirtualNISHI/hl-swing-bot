"""Shared loader: stub duckdb, load bars, equity-path annualizer."""
import sys, types, csv, math, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
from hl_swing_bot.backtest import HourlyBar, run_backtest  # noqa: E402

FEE = 0.19  # round-trip fees+slippage to subtract from gross realized %


def load_bars(path):
    bars = []
    taker = {}
    with open(path, newline='') as fh:
        r = csv.DictReader(fh)
        for i, row in enumerate(r):
            bars.append(HourlyBar(
                int(row['open_time_ms']), float(row['open']), float(row['high']),
                float(row['low']), float(row['close']), float(row['volume']),
                int(row['trades']),
            ))
            if 'taker_buy_base' in row and row['taker_buy_base'] not in (None, ''):
                taker[i] = float(row['taker_buy_base'])
    return bars, taker


def net_list(res):
    """NET realized % per trade (gross from harness already had slippage*2 subtracted;
    but mission defines NET = gross_realized_pct - 0.19. The harness's
    expectancy_pct_post_slippage already subtracts slip*2 = 0.10 at 5bps.
    To follow mission rule EXACTLY we recompute from raw signal realized_pct and
    subtract a flat 0.19, independent of harness slippage.)"""
    out = []
    for s in res.get('signals', []):
        rp = s.get('realized_pct')
        if rp is None:
            continue
        out.append(rp - FEE)
    return out


def summarize(res):
    nl = net_list(res)
    n = len(nl)
    if n == 0:
        return dict(n=0, net_per_trade=0.0, total_net=0.0, win_rate=0.0)
    wins = sum(1 for x in nl if x > 0)
    return dict(
        n=n,
        net_per_trade=statistics.mean(nl),
        total_net=sum(nl),
        win_rate=wins / n,
        med=statistics.median(nl),
    )


def annualized_return(res, bars, risk_frac=0.005):
    """R-multiple equity path at risk_frac of equity per trade.
    R per trade = net_realized_% / (stop_distance_% ). stop_distance derived from
    entry & stop in signal. Equity compounds: eq *= (1 + risk_frac * R).
    Annualize over the span of bars actually covered."""
    sigs = [s for s in res.get('signals', []) if s.get('realized_pct') is not None]
    if not sigs:
        return 0.0
    eq = 1.0
    for s in sigs:
        entry = s['entry']; stop = s['stop']
        stop_dist_pct = abs(stop - entry) / entry * 100.0
        if stop_dist_pct <= 0:
            continue
        net = s['realized_pct'] - FEE
        R = net / stop_dist_pct
        eq *= (1.0 + risk_frac * R)
        if eq <= 0:
            eq = 1e-9
            break
    span_ms = bars[-1].hour_ms - bars[0].hour_ms
    years = span_ms / (365.25 * 24 * 3600 * 1000)
    if years <= 0:
        return 0.0
    ann = eq ** (1.0 / years) - 1.0
    return ann * 100.0


def split_half(bars):
    mid = len(bars) // 2
    return bars[:mid], bars[mid:]
