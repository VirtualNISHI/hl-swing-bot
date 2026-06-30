"""Validate the fast engine reproduces run_backtest baseline on btc3y & HL.

Compares engine signal idx set + net/trade against the real run_backtest.
"""
import sys, types, os
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_common import load_bars
from hl_swing_bot.backtest import run_backtest
from lens_engine import load_cache, run_variant, sig_baseline, stats, ann_05, years_span, FEE

CSV = {"btc3y": "binance_btc_3y.csv", "btchl": "hist_btc.csv", "ethhl": "hist_eth.csv"}

for tag in ["btchl", "ethhl", "btc3y"]:
    c = load_cache(tag)
    sigs = run_variant(c, sig_baseline, tag=tag)
    st = stats(sigs)
    ms = c["raw"]["ms"]
    ann, eq = ann_05(sigs, ms)
    yrs = years_span(ms)
    # real backtest
    bars, _ = load_bars(CSV[tag])
    real = run_backtest(bars, short_only=True, slippage_bps=5)
    rsig = real.get("signals", [])
    real_idx = set(s["idx"] for s in rsig)
    fast_idx = set(s["idx"] for s in sigs)
    only_real = real_idx - fast_idx
    only_fast = fast_idx - real_idx
    rnet = sum(s["realized_pct"] - FEE for s in rsig)/len(rsig) if rsig else 0
    print(f"{tag}: ENGINE n={st['n']} net/trade={st['net_mean']:.3f}% | "
          f"REAL n={len(rsig)} net/trade={rnet:.3f}% | "
          f"idx only_real={len(only_real)} only_fast={len(only_fast)}")
    print(f"   ann@0.5%={ann:.2f}% {st['n']/yrs:.1f}/yr tp={st['tp']} sl={st['sl']} exp={st['exp']}")
    if only_real or only_fast:
        print("   sample only_real:", sorted(only_real)[:5], "only_fast:", sorted(only_fast)[:5])
