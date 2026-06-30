import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, r'C:\User\projects\hl-swing-bot\scratch')
import statistics
from _lens_common import load_bars, HOUR_MS, NET_COST
from hl_swing_bot.backtest import run_backtest

def net_per_trade(res):
    sigs = res.get('signals', [])
    if not sigs:
        return 0.0, 0
    nets = [s['realized_pct'] - NET_COST for s in sigs if s['realized_pct'] is not None]
    return statistics.mean(nets), len(nets)

def years(bars):
    return (bars[-1].hour_ms - bars[0].hour_ms) / (HOUR_MS * 24 * 365.25)

def identify_downtrends(bars, min_drop=0.08, min_len_h=72):
    """Find peak->trough downtrend episodes >= min_drop over >= min_len_h hours.
    Returns list of (peak_idx, trough_idx, drop_frac, duration_h, max_1h_move_atr).
    Uses a simple peak-to-trough scan with drawdown threshold."""
    closes = [b.close for b in bars]
    from _lens_common import wilder_atr_series
    atrs = wilder_atr_series(bars)
    episodes = []
    n = len(closes)
    i = 0
    while i < n - 1:
        # find local peak: scan forward while we can find lower lows
        peak_idx = i
        peak = closes[i]
        # extend: track running min after peak
        trough_idx = i
        trough = closes[i]
        j = i + 1
        while j < n:
            if closes[j] > peak * 1.001:  # new higher high resets if before meaningful drop
                if (peak - trough) / peak < 0.02:
                    peak_idx = j; peak = closes[j]; trough_idx = j; trough = closes[j]
                else:
                    break
            if closes[j] < trough:
                trough = closes[j]; trough_idx = j
            j += 1
        drop = (peak - trough) / peak
        dur = trough_idx - peak_idx
        if drop >= min_drop and dur >= min_len_h:
            # max single-bar move/atr within episode
            mx = 0.0
            for k in range(peak_idx + 1, trough_idx + 1):
                if atrs[k] and atrs[k] > 0:
                    mv = abs(closes[k] - closes[k - 1]) / atrs[k]
                    mx = max(mx, mv)
            episodes.append((peak_idx, trough_idx, drop, dur, mx))
        i = max(trough_idx, i + 1)
    return episodes

SD = r'C:\User\projects\hl-swing-bot\scratch'
for name, path in [('BTC', SD+r'\binance_btc_3y.csv'), ('ETH', SD+r'\binance_eth_3y.csv')]:
    bars, _ = load_bars(path)
    yr = years(bars)
    res = run_backtest(bars, short_only=True)  # baseline: slope_gate=True, red_streak_min=2
    npt, n = net_per_trade(res)
    tpw = res.get('signals_per_week', 0)
    tpy = n / yr
    print(f"=== {name} BASELINE (shipped) | {yr:.2f}y, {len(bars)} bars ===")
    print(f"  trades={n}  net/trade={npt:.3f}%  trades/yr={tpy:.1f}  hit_tp={res.get('hit_rate_tp',0):.3f}")
    # downtrend coverage
    eps = identify_downtrends(bars)
    slow = [e for e in eps if e[4] < 1.0]  # never a sharp >=1.0 move/ATR bar
    fast = [e for e in eps if e[4] >= 1.0]
    sig_idxs = sorted(s['idx'] for s in res.get('signals', []))
    def covered(ep):
        p, t = ep[0], ep[1]
        return any(p <= si <= t for si in sig_idxs)
    slow_cov = sum(1 for e in slow if covered(e))
    fast_cov = sum(1 for e in fast if covered(e))
    print(f"  downtrends>=8%/72h: total={len(eps)}  slow(no sharp bar)={len(slow)}  fast={len(fast)}")
    print(f"  slow-bleed covered by >=1 trade: {slow_cov}/{len(slow)}  ({(slow_cov/len(slow)*100) if slow else 0:.0f}%)")
    print(f"  fast covered: {fast_cov}/{len(fast)}")
