"""TREND-FOLLOW PULLBACK ENTRY lens (sell-the-bounce in a downtrend).

Rule (ONE clean rule, few params):
  Regime gate (confirmed 4h downtrend):
    - 4h close < 4h SMA50  (price below trend)
    - 4h SMA50 slope < 0   (SMA50 now < SMA50 10 bars ago)  [mirrors live slope gate]
  Entry trigger (mean-reversion bounce that rolls over), on 1h bars:
    - price had RALLIED into EMA20: prior bar high >= EMA20 (touched from below)
      OR close was above EMA20 in the last `lookback` bars
    - current 1h bar CLOSES back below EMA20 (rollover / rejection)
    - require we are below EMA20 now (close < ema20)
  This fires on slow grinds because it needs no volatility impulse.

Exit: ATR stop/target mirror baseline by default: stop=entry+1.5*ATR,
      target=entry-2.5*ATR (R:R 1:1.67), TTL 72h, intrabar via high/low.
      Optional breakeven.

Self-contained outcome resolver (SHORT only) so we don't depend on BTSignal wiring.
Reports NET (gross - 0.19), split-half, cross-asset; HL check done in a separate runner.
"""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, r'C:\User\projects\hl-swing-bot\scratch')
import statistics, math
from _lens_common import (load_bars, ema_series, sma_series, rsi_series,
                          wilder_atr_series, HOUR_MS, NET_COST)

SD = r'C:\User\projects\hl-swing-bot\scratch'

def aggregate_4h_aligned(bars):
    """Build 4h buckets; return per-1h-index (sma50_4h, slope_neg_bool) aligned
    so values at 1h index i use only completed info up to bar i (look-ahead safe).
    We bucket by floor(ms / 4h). For each 1h bar i, the '4h context' is the
    SMA50 of the last 50 COMPLETED 4h buckets before/including the current
    partial bucket's prior closes."""
    # Build 4h closes incrementally.
    h4_close = []     # close of each completed 4h bucket
    h4_bucket_of = [None]*len(bars)
    sma50_at = [None]*len(bars)
    slope_neg_at = [False]*len(bars)
    cur_bucket = None
    last_close_in_bucket = None
    h4_closes_list = []
    for i, b in enumerate(bars):
        bk = b.hour_ms // (4*HOUR_MS)
        if cur_bucket is None:
            cur_bucket = bk
        if bk != cur_bucket:
            # previous bucket completed
            h4_closes_list.append(last_close_in_bucket)
            cur_bucket = bk
        last_close_in_bucket = b.close
        # compute SMA50 over completed buckets so far (len list)
        if len(h4_closes_list) >= 60:
            sma50 = sum(h4_closes_list[-50:]) / 50
            sma50_prev = sum(h4_closes_list[-60:-10]) / 50
            sma50_at[i] = sma50
            slope_neg_at[i] = sma50 < sma50_prev
    return sma50_at, slope_neg_at


def resolve_short(bars, atrs, entry_idx, stop_mult=1.5, tgt_mult=2.5, ttl=72, be_atr=0.0):
    atr = atrs[entry_idx]
    if not atr or atr <= 0:
        return None
    entry = bars[entry_idx].close
    stop = entry + stop_mult * atr
    target = entry - tgt_mult * atr
    end = min(entry_idx + ttl, len(bars) - 1)
    be_armed = False
    cur_stop = stop
    for j in range(entry_idx + 1, end + 1):
        b = bars[j]
        if be_armed and be_atr > 0:
            cur_stop = min(cur_stop, entry)
        if b.high >= cur_stop:
            px = cur_stop
            return (entry / px - 1) * 100, 'SL' if cur_stop > entry else 'BE', j
        if b.low <= target:
            return (entry / target - 1) * 100, 'TP', j
        if be_atr > 0 and not be_armed and b.low <= entry - be_atr * atr:
            be_armed = True
    last = bars[end].close
    return (entry / last - 1) * 100, 'EXP', end


def run_pullback(bars, ema_p=20, lookback=6, stop_mult=1.5, tgt_mult=2.5,
                 ttl=72, be_atr=0.0, cooldown_h=4, rsi_mode=False, rsi_p=14,
                 retrace_mode=False):
    closes = [b.close for b in bars]
    ema = ema_series(closes, ema_p)
    atrs = wilder_atr_series(bars)
    sma50_at, slope_neg_at = aggregate_4h_aligned(bars)
    rsi = rsi_series(closes, rsi_p) if rsi_mode else None

    trades = []
    last_entry = -10**9
    n = len(bars)
    for i in range(60, n):
        if i - last_entry < cooldown_h:
            continue
        if atrs[i] is None or atrs[i] <= 0:
            continue
        if ema[i] is None or sma50_at[i] is None:
            continue
        # regime: confirmed 4h downtrend
        if not (closes[i] < sma50_at[i] and slope_neg_at[i]):
            continue
        fired = False
        if rsi_mode:
            # RSI rose above 40 within lookback then turns down now
            if rsi[i] is None or rsi[i-1] is None:
                continue
            recent_above = any(rsi[k] is not None and rsi[k] >= 40 for k in range(max(0,i-lookback), i+1))
            turn_down = rsi[i] < rsi[i-1] and closes[i] < ema[i]
            fired = recent_above and turn_down and rsi[i] < 50
        else:
            # EMA20 bounce-rollover: touched/closed above EMA20 recently, now closes back below
            touched = any((bars[k].high >= ema[k]) for k in range(max(1,i-lookback), i) if ema[k] is not None)
            rollover = closes[i] < ema[i] and closes[i-1] >= (ema[i-1] if ema[i-1] else closes[i-1])
            # also accept: prior bar closed above ema, this bar closes below (clean cross)
            cross_below = (closes[i-1] >= (ema[i-1] or closes[i-1])) and closes[i] < ema[i]
            fired = touched and closes[i] < ema[i] and (rollover or cross_below)
        if not fired:
            continue
        out = resolve_short(bars, atrs, i, stop_mult, tgt_mult, ttl, be_atr)
        if out is None:
            continue
        gross, status, exit_idx = out
        R = (gross) / (stop_mult * atrs[i] / bars[i].close * 100)  # R-multiple = realized% / risk%
        trades.append({'idx': i, 'gross': gross, 'net': gross - NET_COST,
                       'status': status, 'exit_idx': exit_idx, 'R': R,
                       'risk_pct': stop_mult * atrs[i] / bars[i].close * 100})
        last_entry = i
    return trades


def summarize(trades, yr, label=''):
    if not trades:
        print(f"  {label}: 0 trades")
        return None
    nets = [t['net'] for t in trades]
    Rs = [t['net'] / t['risk_pct'] for t in trades]  # net R-multiple
    npt = statistics.mean(nets)
    wr = sum(1 for t in trades if t['net'] > 0) / len(trades)
    tp = sum(1 for t in trades if t['status']=='TP')
    # equity at 0.5% risk
    eq = 1.0
    for R in Rs:
        eq *= (1 + 0.005 * R)
    cagr = (eq ** (1/yr) - 1) * 100 if yr > 0 else 0
    print(f"  {label}: n={len(trades)} net/trade={npt:.3f}% win%={wr*100:.0f} TP%={tp/len(trades)*100:.0f} "
          f"trades/yr={len(trades)/yr:.1f} sumNet={sum(nets):.1f}% CAGR@0.5%={cagr:.1f}%")
    return {'n': len(trades), 'npt': npt, 'cagr': cagr, 'tpy': len(trades)/yr,
            'sumnet': sum(nets), 'Rs': Rs, 'wr': wr}


def years(bars):
    return (bars[-1].hour_ms - bars[0].hour_ms) / (HOUR_MS*24*365.25)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'ema'
    rsi_mode = (mode == 'rsi')
    print(f"### PULLBACK LENS mode={mode} ###")
    for name, fn in [('BTC', 'binance_btc_3y.csv'), ('ETH', 'binance_eth_3y.csv')]:
        bars, _ = load_bars(SD + '\\' + fn)
        yr = years(bars)
        mid = len(bars)//2
        h1, h2 = bars[:mid], bars[mid:]
        yr1 = years(h1); yr2 = years(h2)
        print(f"--- {name} ({yr:.2f}y) ---")
        tr = run_pullback(bars, rsi_mode=rsi_mode)
        summarize(tr, yr, 'FULL')
        tr1 = run_pullback(h1, rsi_mode=rsi_mode)
        summarize(tr1, yr1, 'H1  ')
        tr2 = run_pullback(h2, rsi_mode=rsi_mode)
        summarize(tr2, yr2, 'H2  ')
