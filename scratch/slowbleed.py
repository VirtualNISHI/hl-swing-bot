import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, r'C:\User\projects\hl-swing-bot\scratch')
import statistics
from _lens_common import load_bars, HOUR_MS, wilder_atr_series
from baseline_fast import run_baseline_fast
from baseline_full import identify_downtrends, years

SD = r'C:\User\projects\hl-swing-bot\scratch'

for name, fn in [('BTC','binance_btc_3y.csv'),('ETH','binance_eth_3y.csv')]:
    bars,_=load_bars(SD+'\\'+fn)
    sigs=run_baseline_fast(bars)
    sig_idx=sorted(x['idx'] for x in sigs)
    eps=identify_downtrends(bars)  # >=8% / >=72h peak-to-trough
    print(f"=== {name}: {len(eps)} downtrends >=8% over >=72h ===")
    missed=[]; traded=[]
    for ep in eps:
        p,t,drop,dur,mx=ep
        fired=[si for si in sig_idx if p<=si<=t]
        rec={'drop':drop*100,'dur':dur,'max1h':mx,'nfired':len(fired)}
        (traded if fired else missed).append(rec)
    print(f"  TRADED (>=1 fire): {len(traded)}   MISSED (0 fires): {len(missed)}")
    if missed:
        print(f"  MISSED downtrends: avg drop={statistics.mean(m['drop'] for m in missed):.1f}% "
              f"avg dur={statistics.mean(m['dur'] for m in missed):.0f}h "
              f"max1h move/ATR avg={statistics.mean(m['max1h'] for m in missed):.2f} "
              f"(min={min(m['max1h'] for m in missed):.2f} max={max(m['max1h'] for m in missed):.2f})")
        # how many missed are 'slow grind' = max1h move/ATR < 2.0 (no real cascade)
        grind=[m for m in missed if m['max1h']<2.0]
        print(f"  of missed, true slow-grinds (no bar >=2.0 ATR): {len(grind)} "
              f"avg drop={statistics.mean(m['drop'] for m in grind):.1f}%" if grind else "  no pure grinds")
    if traded:
        print(f"  TRADED downtrends: avg drop={statistics.mean(m['drop'] for m in traded):.1f}% "
              f"avg fires={statistics.mean(m['nfired'] for m in traded):.1f} "
              f"max1h move/ATR avg={statistics.mean(m['max1h'] for m in traded):.2f}")
