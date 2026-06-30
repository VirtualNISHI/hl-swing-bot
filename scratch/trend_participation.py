"""LENS: TIME-BASED TREND PARTICIPATION.

Mechanical short on a fixed cadence whenever a confirmed 4h downtrend holds
(trend_4h<=-1 AND trend_4h_slope<=-1), NO move/ATR or vol_z impulse gate.
Sweep cadence and exit. ATR stop/target via _resolve_outcome. Pyramiding up
to a cluster cap. Report NET (gross - 0.19). Split-half + cross-asset + HL.
"""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')  # CPython3.13 segfault guard
import os, csv, statistics, math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from hl_swing_bot.features import HourlyBar, MIN_BARS
from hl_swing_bot.backtest import (
    _compute_features_at, _resolve_outcome, BTSignal, run_backtest,
)
from hl_swing_bot.signal import STOP_ATR_MULT, TARGET_ATR_MULT

SCRATCH = os.path.dirname(__file__)
FEE = 0.19  # round-trip net cost (fees+slippage), percent
SLIP_BPS = 5.0  # per-side, matches harness convention (slip*2 applied)


def load_bars(path):
    bars = []
    taker = {}
    with open(path, newline='') as fh:
        r = csv.reader(fh)
        header = next(r)
        has_taker = 'taker_buy_base' in header
        for idx, row in enumerate(r):
            ms = int(row[0])
            o, h, l, c, v = (float(row[1]), float(row[2]), float(row[3]),
                             float(row[4]), float(row[5]))
            trades = int(float(row[6])) if len(row) > 6 and row[6] else 0
            bars.append(HourlyBar(hour_ms=ms, open=o, high=h, low=l, close=c,
                                  volume=v, trades=trades))
            if has_taker and len(row) > 7 and row[7]:
                taker[idx] = float(row[7])
    return bars, taker


def precompute_features(bars):
    """Compute features once per bar index (expensive O(n^2) loop)."""
    feats = [None] * len(bars)
    for i in range(MIN_BARS, len(bars)):
        feats[i] = _compute_features_at(bars, i)
    return feats


# ---- Equity path at fixed fractional risk (R-multiple) -------------------
def annualized_return(signals, bars, risk_frac=0.005):
    """Each trade risks risk_frac of equity at its stop distance. realized_pct
    is price move %; R = realized_pct / stop_dist_pct. Equity compounds by
    risk_frac * R per trade. Annualize over the data span."""
    if not signals:
        return 0.0
    equity = 1.0
    for s in signals:
        if s['realized_pct'] is None:
            continue
        net = s['realized_pct'] - FEE  # net price move %
        stop_dist_pct = s['stop_dist_pct']
        if stop_dist_pct <= 0:
            continue
        R = net / stop_dist_pct
        equity *= (1.0 + risk_frac * R)
        if equity <= 0:
            equity = 1e-9
    span_ms = bars[-1].hour_ms - bars[MIN_BARS].hour_ms
    years = span_ms / (365.25 * 24 * 3600 * 1000)
    if years <= 0:
        return 0.0
    return (equity ** (1.0 / years) - 1.0) * 100.0


# ---- Mechanical trend-participation engine -------------------------------
def trend_participation(bars, feats, *, cadence_hours, exit_mode,
                        target_atr_mult=TARGET_ATR_MULT, ttl_hours=72,
                        cluster_cap=3, require_slope=True, require_streak=0):
    """SHORT on a fixed cadence while in confirmed 4h downtrend.

    cadence_hours: min hours between entries within a trend episode.
    exit_mode: 'atr' (stop=+1.5ATR, target=-target_atr_mult ATR via _resolve_outcome)
               or 'trend' (exit when trend_4h flips up OR ttl, fixed +1.5ATR stop).
    cluster_cap: max simultaneously-open positions (pyramiding limit).
    require_streak: min red_4h_streak (0=off).
    Returns list of signal dicts with realized_pct, stop_dist_pct.
    """
    sigs = []
    open_positions = []  # list of (entry_idx, exit_idx) currently open
    last_entry_idx = -10 ** 9

    for i in range(MIN_BARS, len(bars)):
        f = feats[i]
        if f is None:
            continue
        # prune closed positions
        open_positions = [op for op in open_positions if op > i]
        in_downtrend = f['trend_4h'] <= -1
        slope_ok = (not require_slope) or (f['trend_4h_slope'] <= -1)
        streak_ok = require_streak <= 0 or f['red_4h_streak'] >= require_streak
        if not (in_downtrend and slope_ok and streak_ok):
            continue
        if (i - last_entry_idx) < cadence_hours:
            continue
        if len(open_positions) >= cluster_cap:
            continue

        atr = f['atr_1h']
        entry = f['close']
        if atr <= 0:
            continue
        stop = entry + STOP_ATR_MULT * atr

        if exit_mode == 'atr':
            target = entry - target_atr_mult * atr
            sig = BTSignal(idx=i, bar_close_ms=bars[i].hour_ms + 3600000,
                           direction='SHORT', entry=entry, stop=stop,
                           target=target, score=0.0, expires_idx=i + ttl_hours)
            _resolve_outcome(bars, sig, ttl_bars=ttl_hours)
            exit_idx = sig.exit_idx
            realized = sig.realized_pct
            status = sig.status
        else:  # trend exit: hold until trend_4h flips >=0 or stop hit or ttl
            exit_idx = min(i + ttl_hours, len(bars) - 1)
            status = 'TREND_EXIT'
            realized = None
            for j in range(i + 1, min(i + ttl_hours, len(bars) - 1) + 1):
                b = bars[j]
                if b.high >= stop:  # stop hit
                    exit_idx = j
                    status = 'HIT_SL'
                    realized = (entry / stop - 1) * 100
                    break
                fj = feats[j]
                if fj is not None and fj['trend_4h'] >= 0:  # trend flipped
                    exit_idx = j
                    status = 'TREND_FLIP'
                    realized = (entry / b.close - 1) * 100
                    break
            if realized is None:
                lc = bars[exit_idx].close
                realized = (entry / lc - 1) * 100

        stop_dist_pct = (stop / entry - 1) * 100  # positive for short
        sig_dict = {
            'idx': i, 'exit_idx': exit_idx, 'realized_pct': realized,
            'status': status, 'stop_dist_pct': stop_dist_pct,
            'ms': bars[i].hour_ms,
        }
        sigs.append(sig_dict)
        last_entry_idx = i
        open_positions.append(exit_idx)
    return sigs


def net_stats(sigs, bars, label=''):
    if not sigs:
        return {'n': 0, 'net_per_trade': 0.0, 'trades_per_yr': 0.0,
                'ann': 0.0, 'winrate': 0.0, 'label': label}
    nets = [s['realized_pct'] - FEE for s in sigs if s['realized_pct'] is not None]
    span_ms = bars[-1].hour_ms - bars[MIN_BARS].hour_ms
    years = span_ms / (365.25 * 24 * 3600 * 1000)
    return {
        'n': len(nets),
        'net_per_trade': statistics.mean(nets),
        'net_total': sum(nets),
        'trades_per_yr': len(nets) / years if years > 0 else 0,
        'ann': annualized_return(sigs, bars),
        'winrate': sum(1 for x in nets if x > 0) / len(nets),
        'label': label,
    }
