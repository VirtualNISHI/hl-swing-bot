"""Selective trend-follow pullback sweep.

Make the 'sell the bounce' entry SELECTIVE so it doesn't fire on every wiggle:
  Regime: 4h downtrend (close<sma50_4h AND slope_neg) -- same as before.
  Entry, on 1h:
    1) Identify the most recent swing-low and the bounce HIGH after it.
    2) The bounce must retrace into [retr_lo, retr_hi] of the down-leg
       (Fibonacci-style: 0.382-0.618 by default) measured from the leg's
       high(start) to the swing low.
    3) Rollover trigger: current 1h closes below previous 1h low (momentum
       turns back down) OR closes below EMA(ema_p).
    4) RSI(14) at the bounce peak was <= rsi_cap (countertrend rally, not a
       real reversal) -- optional.
  This requires a real pullback structure, so it fires rarely (slow grinds
  included) instead of every bar.

Exit grid: ATR stop/target; also test 'trend-ride' (wider target, breakeven).
Reports NET, split-half, cross-asset.
"""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, r'C:\User\projects\hl-swing-bot\scratch')
import statistics
from _lens_common import (load_bars, ema_series, rsi_series,
                          wilder_atr_series, HOUR_MS, NET_COST)
from pullback_lens import aggregate_4h_aligned, resolve_short, years

SD = r'C:\User\projects\hl-swing-bot\scratch'


def find_swings(closes, lows, highs, i, max_look=48):
    """Look back from i to find: swing_low (lowest low) and the prior leg high
    (highest high before that low within window). Returns (leg_high, swing_low,
    bounce_high). bounce_high = highest high between swing_low and i."""
    lo_idx = i; lo = lows[i]
    for k in range(i, max(0, i - max_look), -1):
        if lows[k] < lo:
            lo = lows[k]; lo_idx = k
    # leg high: highest high in window before lo_idx
    hi = highs[lo_idx]; hi_idx = lo_idx
    for k in range(lo_idx, max(0, lo_idx - max_look), -1):
        if highs[k] > hi:
            hi = highs[k]; hi_idx = k
    # bounce high: highest high from lo_idx..i
    bh = highs[lo_idx]; bh_idx = lo_idx
    for k in range(lo_idx, i + 1):
        if highs[k] > bh:
            bh = highs[k]; bh_idx = k
    return hi, hi_idx, lo, lo_idx, bh, bh_idx


def run(bars, ema_p=20, retr_lo=0.382, retr_hi=0.786, rsi_cap=60, rsi_p=14,
        stop_mult=1.5, tgt_mult=2.5, ttl=72, be_atr=0.0, cooldown_h=12,
        max_look=48, use_rsi_cap=True):
    closes = [b.close for b in bars]
    lows = [b.low for b in bars]
    highs = [b.high for b in bars]
    ema = ema_series(closes, ema_p)
    atrs = wilder_atr_series(bars)
    rsi = rsi_series(closes, rsi_p)
    sma50_at, slope_neg_at = aggregate_4h_aligned(bars)
    trades = []
    last_entry = -10**9
    n = len(bars)
    for i in range(60, n):
        if i - last_entry < cooldown_h:
            continue
        a = atrs[i]
        if not a or a <= 0 or ema[i] is None or sma50_at[i] is None:
            continue
        if not (closes[i] < sma50_at[i] and slope_neg_at[i]):
            continue
        leg_hi, hi_idx, sw_lo, lo_idx, b_hi, bh_idx = find_swings(closes, lows, highs, i, max_look)
        leg = leg_hi - sw_lo
        if leg <= 0:
            continue
        # retracement of the bounce off the low, measured up from the low
        retr = (b_hi - sw_lo) / leg
        if not (retr_lo <= retr <= retr_hi):
            continue
        # bounce must have peaked (bh before current bar) and now rolling over
        if bh_idx >= i:
            continue
        # RSI at bounce peak not too hot (still countertrend)
        if use_rsi_cap and (rsi[bh_idx] is None or rsi[bh_idx] > rsi_cap):
            continue
        # rollover: current close below prior bar low (momentum down) and below ema
        rollover = closes[i] < lows[i-1] and closes[i] < ema[i]
        if not rollover:
            continue
        out = resolve_short(bars, atrs, i, stop_mult, tgt_mult, ttl, be_atr)
        if out is None:
            continue
        gross, status, exit_idx = out
        risk_pct = stop_mult * a / closes[i] * 100
        trades.append({'idx': i, 'net': gross - NET_COST, 'status': status,
                       'R': (gross - NET_COST) / risk_pct, 'risk_pct': risk_pct})
        last_entry = i
    return trades


def summ(trades, yr):
    if not trades:
        return None
    nets = [t['net'] for t in trades]
    Rs = [t['R'] for t in trades]
    eq = 1.0
    for R in Rs:
        eq *= (1 + 0.005 * R)
    cagr = (eq ** (1/yr) - 1) * 100 if yr > 0 else 0
    return {'n': len(trades), 'npt': statistics.mean(nets), 'sumnet': sum(nets),
            'tpy': len(trades)/yr, 'cagr': cagr,
            'wr': sum(1 for x in nets if x>0)/len(nets),
            'tp': sum(1 for t in trades if t['status']=='TP')/len(trades)}


def fmt(s):
    if not s: return "0 trades"
    return (f"n={s['n']:4d} net/t={s['npt']:+.3f}% win%={s['wr']*100:2.0f} "
            f"TP%={s['tp']*100:2.0f} t/yr={s['tpy']:5.1f} sumNet={s['sumnet']:+7.1f}% CAGR={s['cagr']:+.1f}%")


if __name__ == '__main__':
    btc, _ = load_bars(SD+r'\binance_btc_3y.csv')
    eth, _ = load_bars(SD+r'\binance_eth_3y.csv')
    yb = years(btc); ye = years(eth)
    def halves(bars):
        m = len(bars)//2
        return bars[:m], bars[m:]
    bh1, bh2 = halves(btc); eh1, eh2 = halves(eth)
    yb1=years(bh1); yb2=years(bh2); ye1=years(eh1); ye2=years(eh2)

    # Parameter grid: vary retracement band, rsi cap, exit (stop/tgt/ttl/be)
    configs = [
        dict(retr_lo=0.382, retr_hi=0.786, rsi_cap=60, stop_mult=1.5, tgt_mult=2.5, ttl=72, be_atr=0.0),
        dict(retr_lo=0.5,   retr_hi=1.0,   rsi_cap=60, stop_mult=1.5, tgt_mult=2.5, ttl=72, be_atr=0.0),
        dict(retr_lo=0.382, retr_hi=0.786, rsi_cap=55, stop_mult=1.5, tgt_mult=2.5, ttl=72, be_atr=1.0),
        dict(retr_lo=0.382, retr_hi=0.786, rsi_cap=60, stop_mult=2.0, tgt_mult=4.0, ttl=120, be_atr=0.0),  # trend-ride
        dict(retr_lo=0.382, retr_hi=0.786, rsi_cap=60, stop_mult=1.5, tgt_mult=2.0, ttl=48, be_atr=0.0),
        dict(retr_lo=0.382, retr_hi=0.786, rsi_cap=50, stop_mult=1.5, tgt_mult=2.5, ttl=72, be_atr=0.0),
        dict(retr_lo=0.382, retr_hi=1.0,   rsi_cap=100,stop_mult=1.5, tgt_mult=2.5, ttl=72, be_atr=0.0, use_rsi_cap=False),
    ]
    for ci, cfg in enumerate(configs):
        print(f"\n=== CONFIG {ci}: {cfg} ===")
        for nm, full, h1, h2, yf, y1, y2 in [
            ('BTC', btc, bh1, bh2, yb, yb1, yb2),
            ('ETH', eth, eh1, eh2, ye, ye1, ye2)]:
            sf = summ(run(full, **cfg), yf)
            s1 = summ(run(h1, **cfg), y1)
            s2 = summ(run(h2, **cfg), y2)
            print(f"  {nm} FULL {fmt(sf)}")
            print(f"      H1   {fmt(s1)}")
            print(f"      H2   {fmt(s2)}")
