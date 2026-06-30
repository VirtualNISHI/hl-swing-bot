"""Baseline: shipped config + quantify how much slow-bleed it MISSES.

Run on 3y BTC/ETH and HL 208d. Define downtrends, measure capture.
"""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings
warnings.filterwarnings("ignore")

from lens_common import load_bars, summarize_net, annualized_return_05pct, years_span, FEE
from hl_swing_bot.backtest import run_backtest


def find_downtrends(bars, drop_pct=8.0, max_win_hours=24*21):
    """Identify peak->trough downtrend episodes of >= drop_pct within a window.

    Greedy: scan for local peaks, then find subsequent trough within max_win
    that is >= drop_pct below. Record (peak_idx, trough_idx, drop, hours,
    max_1h_move_per_close, is_slow).
    A 'slow-bleed' = the worst single 1h close-to-close move is small relative
    to total drop (no cascade bar). We'll flag is_slow if max |1h ret| < 3%.
    """
    n = len(bars)
    closes = [b.close for b in bars]
    episodes = []
    i = 0
    while i < n - 1:
        peak = closes[i]
        # find trough within window
        j_end = min(i + max_win_hours, n)
        trough = peak
        trough_idx = i
        for j in range(i + 1, j_end):
            if closes[j] < trough:
                trough = closes[j]
                trough_idx = j
            # stop extending if price recovers above peak (new regime)
            if closes[j] > peak * 1.02:
                break
        drop = (peak - trough) / peak * 100.0
        if drop >= drop_pct and trough_idx > i:
            hours = trough_idx - i
            # max single 1h move (down) within the episode
            max_1h_down = 0.0
            for k in range(i + 1, trough_idx + 1):
                r = (closes[k] / closes[k - 1] - 1) * 100.0
                if r < 0:
                    max_1h_down = max(max_1h_down, -r)
            is_slow = max_1h_down < 3.0
            episodes.append({
                "peak_idx": i, "trough_idx": trough_idx, "drop": drop,
                "hours": hours, "max_1h_down": max_1h_down, "is_slow": is_slow,
            })
            i = trough_idx + 1
        else:
            i += 1
    return episodes


def trades_inside(sigs, lo, hi):
    return [s for s in sigs if lo <= s["idx"] <= hi]


def report(name, bars):
    res = run_backtest(bars, short_only=True)  # SHIPPED config
    sigs = res.get("signals", [])
    st = summarize_net(sigs)
    yrs = years_span(bars)
    ann, eq, _ = annualized_return_05pct(sigs, bars)
    print(f"\n==== {name} (span={yrs:.2f}y, bars={len(bars)}) ====")
    print(f"BASELINE shipped: n={st['n']} trades, {st['n']/yrs:.1f}/yr, "
          f"net/trade={st['net_mean']:.3f}% win={st['win_rate']*100:.0f}% "
          f"net_total={st['net_total']:.1f}% ann@0.5%={ann:.2f}% eqx={eq:.3f}")

    eps = find_downtrends(bars, drop_pct=8.0)
    slow = [e for e in eps if e["is_slow"]]
    fast = [e for e in eps if not e["is_slow"]]
    print(f"Downtrends>=8%: {len(eps)} total | slow(no>3% bar)={len(slow)} "
          f"fast/cascade={len(fast)}")
    # capture: did baseline place >=1 trade inside episode window?
    def capture(eplist):
        captured = 0
        total_dd = 0.0
        captured_dd = 0.0
        for e in eplist:
            inside = trades_inside(sigs, e["peak_idx"], e["trough_idx"])
            total_dd += e["drop"]
            if inside:
                captured += 1
                captured_dd += e["drop"]
        return captured, total_dd, captured_dd
    c_all, dd_all, cdd_all = capture(eps)
    c_slow, dd_slow, cdd_slow = capture(slow)
    c_fast, dd_fast, cdd_fast = capture(fast)
    print(f"CAPTURE all: {c_all}/{len(eps)} episodes "
          f"({cdd_all/max(dd_all,1e-9)*100:.0f}% of total drop-pts)")
    print(f"CAPTURE slow: {c_slow}/{len(slow)} episodes "
          f"-> MISSED {len(slow)-c_slow} slow downtrends "
          f"({(1-cdd_slow/max(dd_slow,1e-9))*100:.0f}% of slow drop-pts missed)")
    print(f"CAPTURE fast: {c_fast}/{len(fast)} episodes "
          f"({cdd_fast/max(dd_fast,1e-9)*100:.0f}% of fast drop-pts captured)")
    return res, eps, slow, fast


if __name__ == "__main__":
    for nm, path in [
        ("BTC-3y", "binance_btc_3y.csv"),
        ("ETH-3y", "binance_eth_3y.csv"),
        ("BTC-HL208d", "hist_btc.csv"),
        ("ETH-HL208d", "hist_eth.csv"),
    ]:
        bars, _ = load_bars(path)
        report(nm, bars)
