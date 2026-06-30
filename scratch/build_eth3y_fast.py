"""Build eth3y (and any) cache via feat_fast (allocation-light, no corruption)."""
import sys, types, os, pickle
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_common import load_bars
import feat_fast

SCRATCH = os.path.dirname(os.path.abspath(__file__))
MAP = {"eth3y": "binance_eth_3y.csv", "btc3y": "binance_btc_3y.csv"}

tag = sys.argv[1]
bars, tbb = load_bars(MAP[tag])
raw = {
    "ms":[b.hour_ms for b in bars], "open":[b.open for b in bars],
    "high":[b.high for b in bars], "low":[b.low for b in bars],
    "close":[b.close for b in bars], "vol":[b.volume for b in bars],
    "tbb": tbb,
}
feats = feat_fast.compute_all(raw)
out = os.path.join(SCRATCH, f"fcache_{tag}.pkl")
with open(out, "wb") as fh:
    pickle.dump({"feats": feats, "raw": raw, "n": len(bars)}, fh)
print(f"{tag}: {sum(1 for f in feats if f)} rows / {len(bars)} bars -> {out}")
