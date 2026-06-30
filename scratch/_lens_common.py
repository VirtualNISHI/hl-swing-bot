"""Shared helpers for trend-follow-pullback lens experiments.
ALWAYS imported with duckdb stubbed and PYTHON_JIT=0 at top of each runner.
"""
import sys, types, csv, math, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')

from hl_swing_bot.backtest import HourlyBar, run_backtest, _compute_features_at  # noqa

HOUR_MS = 3600_000
NET_COST = 0.19  # round-trip fees+slippage, subtract from gross realized %


def load_bars(path):
    bars = []
    taker = []
    with open(path, newline='') as f:
        r = csv.DictReader(f)
        for row in r:
            bars.append(HourlyBar(
                hour_ms=int(row['open_time_ms']),
                open=float(row['open']), high=float(row['high']),
                low=float(row['low']), close=float(row['close']),
                volume=float(row['volume']), trades=int(row['trades']),
            ))
            taker.append(float(row['taker_buy_base']) if 'taker_buy_base' in row and row['taker_buy_base'] else 0.0)
    return bars, taker


def split_idx(bars):
    """Return index that splits bars into first-half / second-half by time."""
    return len(bars) // 2


# ---- indicator helpers computed over the full close array (look-ahead safe by index) ----
def ema_series(vals, period):
    k = 2.0 / (period + 1)
    out = [None] * len(vals)
    ema = None
    for i, v in enumerate(vals):
        if ema is None:
            ema = v
        else:
            ema = v * k + ema * (1 - k)
        out[i] = ema
    return out


def sma_series(vals, period):
    out = [None] * len(vals)
    s = 0.0
    from collections import deque
    dq = deque()
    for i, v in enumerate(vals):
        dq.append(v); s += v
        if len(dq) > period:
            s -= dq.popleft()
        if len(dq) == period:
            out[i] = s / period
    return out


def rsi_series(vals, period=14):
    out = [None] * len(vals)
    if len(vals) < period + 1:
        return out
    gains = 0.0; losses = 0.0
    for i in range(1, period + 1):
        d = vals[i] - vals[i - 1]
        if d >= 0: gains += d
        else: losses -= d
    avg_g = gains / period; avg_l = losses / period
    rs = avg_g / avg_l if avg_l > 0 else float('inf')
    out[period] = 100 - 100 / (1 + rs) if avg_l > 0 else 100.0
    for i in range(period + 1, len(vals)):
        d = vals[i] - vals[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
        rs = avg_g / avg_l if avg_l > 0 else float('inf')
        out[i] = 100 - 100 / (1 + rs) if avg_l > 0 else 100.0
    return out


def wilder_atr_series(bars, period=14):
    """ATR aligned to bar index; out[i] is ATR as of close of bar i."""
    n = len(bars)
    out = [None] * n
    if n < period + 1:
        return out
    trs = [0.0] * n
    for i in range(1, n):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        trs[i] = max(h - l, abs(h - pc), abs(l - pc))
    atr = sum(trs[1:period + 1]) / period
    out[period] = atr
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def annualized_return_05pct(realized_net_pcts, n_years, rr_loss_R=1.0):
    """Equity-path at 0.5% risk per trade.
    Each trade's R-multiple = realized_net_pct / risk_pct_at_entry.
    Simpler: we model risk as fixed stop distance => R = realized/(stop_dist%).
    Here we pass realized R-multiples directly. Risk 0.5% equity per R.
    Returns CAGR %.
    """
    equity = 1.0
    for R in realized_net_pcts:
        equity *= (1 + 0.005 * R)
    if n_years <= 0:
        return 0.0
    return (equity ** (1.0 / n_years) - 1.0) * 100
