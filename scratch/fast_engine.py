"""Fast grid engine: replicate run_backtest gating + _resolve_outcome using
precomputed features. Validated to match the real harness exactly.
"""
import pickle, math, statistics

FEE = 0.19
# constants mirrored from signal.py
STOP_ATR_MULT = 1.5
TARGET_ATR_MULT = 2.5
SIGNAL_TTL_HOURS = 72
COOLDOWN_SAME_DIR_MIN = 240
COOLDOWN_OPP_DIR_MIN = 60
from hl_swing_bot.features import MIN_BARS  # noqa: E402


def load(pkl):
    with open(pkl, 'rb') as fh:
        return pickle.load(fh)


def _resolve(bars, idx, direction, entry, stop, target, ttl):
    # bars: list of tuples (hour_ms,open,high,low,close,volume,trades)
    end_idx = min(idx + ttl, len(bars) - 1)
    for j in range(idx + 1, end_idx + 1):
        _, _, _, hi, _, _, _ = bars[j][0], bars[j][1], bars[j][2], bars[j][3], bars[j][4], bars[j][5], bars[j][6]
        b = bars[j]
        bhigh = b[2]; blow = b[3]
        if direction == 'SHORT':
            if bhigh >= stop:
                rp = (entry / stop - 1) * 100
                return 'HIT_SL', j, stop, rp
            if blow <= target:
                rp = (entry / target - 1) * 100
                return 'HIT_TP', j, target, rp
        else:
            if blow <= stop:
                rp = (stop / entry - 1) * 100
                return 'HIT_SL', j, stop, rp
            if bhigh >= target:
                rp = (target / entry - 1) * 100
                return 'HIT_TP', j, target, rp
    last_close = bars[end_idx][4]
    if direction == 'SHORT':
        rp = (entry / last_close - 1) * 100
    else:
        rp = (last_close / entry - 1) * 100
    return 'EXPIRED', end_idx, last_close, rp


def run(data, *, short_only=True, score_min=3.0, move_min=1.0, vol_min=1.0,
        slope_gate=True, red_streak_min=2, ttl=SIGNAL_TTL_HOURS,
        target_atr_mult=TARGET_ATR_MULT):
    bars = data['bars']; feats = data['feats']; scores = data['scores']
    n = len(bars)
    sigs = []
    last_dir = None
    last_idx = -10000
    for i in range(MIN_BARS, n):
        f = feats[i]
        if f is None:
            continue
        direction = 'LONG' if f['ret_1h'] > 0 else 'SHORT'
        if short_only and direction == 'LONG':
            continue
        elapsed_min = (i - last_idx) * 60
        if last_dir is not None:
            if last_dir == direction and elapsed_min < COOLDOWN_SAME_DIR_MIN:
                continue
            if last_dir != direction and elapsed_min < COOLDOWN_OPP_DIR_MIN:
                continue
        score = scores[i]
        if score < score_min:
            continue
        if f['move_per_atr'] < move_min:
            continue
        if f['vol_z_168'] < vol_min:
            continue
        trend_aligned = (direction == 'LONG' and f['trend_4h'] >= 1) or \
                        (direction == 'SHORT' and f['trend_4h'] <= -1)
        if not trend_aligned:
            continue
        if slope_gate:
            slope_aligned = (direction == 'SHORT' and f['trend_4h_slope'] <= -1) or \
                            (direction == 'LONG' and f['trend_4h_slope'] >= 1)
            if not slope_aligned:
                continue
        if red_streak_min > 0:
            if not (direction == 'SHORT' and f['red_4h_streak'] >= red_streak_min):
                continue
        atr = f['atr_1h']; entry = f['close']
        if direction == 'SHORT':
            stop = entry + STOP_ATR_MULT * atr
            target = entry - target_atr_mult * atr
        else:
            stop = entry - STOP_ATR_MULT * atr
            target = entry + target_atr_mult * atr
        status, exit_idx, exit_price, rp = _resolve(bars, i, direction, entry, stop, target, ttl)
        sigs.append(dict(idx=i, ms=bars[i][0] + 3600000, direction=direction,
                         entry=entry, stop=stop, exit=exit_price, exit_idx=exit_idx,
                         status=status, realized_pct=rp, score=score))
        last_dir = direction
        last_idx = i
    return sigs, bars


def metrics(sigs, bars, risk_frac=0.005):
    nl = [s['realized_pct'] - FEE for s in sigs if s['realized_pct'] is not None]
    n = len(nl)
    if n == 0:
        return dict(n=0, net_per_trade=0.0, total_net=0.0, win_rate=0.0,
                    trades_per_year=0.0, ann=0.0)
    span_ms = bars[-1][0] - bars[0][0]
    years = span_ms / (365.25 * 24 * 3600 * 1000)
    eq = 1.0
    for s in sigs:
        if s['realized_pct'] is None:
            continue
        sd = abs(s['stop'] - s['entry']) / s['entry'] * 100
        if sd <= 0:
            continue
        R = (s['realized_pct'] - FEE) / sd
        eq *= (1.0 + risk_frac * R)
        if eq <= 1e-9:
            eq = 1e-9
    ann = (eq ** (1.0 / years) - 1.0) * 100 if years > 0 else 0.0
    wins = sum(1 for x in nl if x > 0)
    return dict(n=n, net_per_trade=statistics.mean(nl), total_net=sum(nl),
                win_rate=wins / n, med=statistics.median(nl),
                trades_per_year=n / years, ann=ann, years=years, eq=eq)
