"""Phase 1 (minimal/isolated): run baseline run_backtest per asset+source, dump
signals to JSON. Nothing else in this process to avoid CPython3.13 instability."""
import sys, types, gc
sys.modules['duckdb'] = types.ModuleType('duckdb')
gc.disable()  # CPython 3.13 corrupts objects under heavy short-lived alloc in tight O(n^2) loop
import csv, json
from hl_swing_bot.backtest import HourlyBar, run_backtest

SCRATCH = r"C:\User\projects\hl-swing-bot\scratch"

def load_bars(path):
    bars = []
    with open(path, newline="") as f:
        r = csv.reader(f); next(r)
        for row in r:
            bars.append(HourlyBar(int(float(row[0])), float(row[1]), float(row[2]),
                                  float(row[3]), float(row[4]), float(row[5]), int(float(row[6]))))
    return bars

if __name__ == "__main__":
    src = sys.argv[1]   # csv filename
    tag = sys.argv[2]   # output tag
    bars = load_bars(f"{SCRATCH}\\{src}")
    res = run_backtest(bars, short_only=True)
    sigs = [{"idx": s["idx"], "entry": s["entry"], "stop": s["stop"],
             "direction": s["direction"], "ms": s["ms"],
             "base_status": s["status"], "base_realized": s["realized_pct"]}
            for s in res["signals"]]
    out = {"n_signals": res["n_signals"],
           "exp_post_slip": res["expectancy_pct_post_slippage"],
           "first_ms": bars[0].hour_ms, "last_ms": bars[-1].hour_ms,
           "n_bars": len(bars), "signals": sigs}
    with open(f"{SCRATCH}\\base_{tag}.json", "w") as f:
        json.dump(out, f)
    print(f"{tag}: n={res['n_signals']} exp={res['expectancy_pct_post_slippage']:.4f}")
