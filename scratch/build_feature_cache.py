"""Precompute features for every bar ONCE per dataset, pickle to disk.

This is the O(n^2) cost paid a single time. All variant lenses then read the
cache and apply cheap signal/outcome logic, so iteration is fast.

Stores per-idx: the full feature dict from _compute_features_at, plus raw OHLCV
and taker_buy_base so downstream lenses can build regime features causally.
"""
import sys, types, os, pickle, time
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_common import load_bars
from hl_swing_bot.backtest import _compute_features_at
from hl_swing_bot.features import MIN_BARS

DATASETS = [
    ("btc3y", "binance_btc_3y.csv"),
    ("eth3y", "binance_eth_3y.csv"),
    ("btchl", "hist_btc.csv"),
    ("ethhl", "hist_eth.csv"),
]
SCRATCH = os.path.dirname(os.path.abspath(__file__))


def build(tag, path, lo=None, hi=None, suffix=""):
    bars, tbb = load_bars(path)
    n = len(bars)
    feats = [None] * n
    t0 = time.time()
    rlo = MIN_BARS if lo is None else max(MIN_BARS, lo)
    rhi = n if hi is None else min(n, hi)
    for i in range(rlo, rhi):
        try:
            f = _compute_features_at(bars, i)
        except AssertionError:
            f = None
        feats[i] = f
        if i % 2000 == 0:
            print(f"  {tag}{suffix} {i}/{n} ({time.time()-t0:.0f}s)", flush=True)
    raw = {
        "ms":   [b.hour_ms for b in bars],
        "open": [b.open for b in bars],
        "high": [b.high for b in bars],
        "low":  [b.low for b in bars],
        "close":[b.close for b in bars],
        "vol":  [b.volume for b in bars],
        "tbb":  tbb,  # taker_buy_base or None
    }
    if suffix:
        # partial: store only the feats slice + range
        out = os.path.join(SCRATCH, f"fcache_{tag}{suffix}.pkl")
        with open(out, "wb") as fh:
            pickle.dump({"feats": feats[rlo:rhi], "lo": rlo, "hi": rhi,
                         "raw": raw, "n": n}, fh)
        print(f"{tag}{suffix}: partial {rlo}:{rhi} -> {out} ({time.time()-t0:.0f}s)", flush=True)
        return
    out = os.path.join(SCRATCH, f"fcache_{tag}.pkl")
    with open(out, "wb") as fh:
        pickle.dump({"feats": feats, "raw": raw, "n": n}, fh)
    nf = sum(1 for f in feats if f)
    print(f"{tag}: cached {nf} feature rows / {n} bars -> {out} ({time.time()-t0:.0f}s)", flush=True)


def stitch(tag, path, nchunks):
    bars, tbb = load_bars(path)
    n = len(bars)
    feats = [None] * n
    raw = None
    for k in range(nchunks):
        p = os.path.join(SCRATCH, f"fcache_{tag}_p{k}.pkl")
        with open(p, "rb") as fh:
            d = pickle.load(fh)
        raw = d["raw"]
        feats[d["lo"]:d["hi"]] = d["feats"]
    out = os.path.join(SCRATCH, f"fcache_{tag}.pkl")
    with open(out, "wb") as fh:
        pickle.dump({"feats": feats, "raw": raw, "n": n}, fh)
    nf = sum(1 for f in feats if f)
    print(f"{tag}: STITCHED {nf} feature rows / {n} bars -> {out}", flush=True)


if __name__ == "__main__":
    # modes:
    #   <tag>                      -> full build
    #   <tag> <lo> <hi> <suffix>   -> partial build
    #   stitch <tag> <path> <nchunks>
    if sys.argv[1] == "stitch":
        _, _, tag, nchunks = sys.argv
        path = dict(DATASETS)[tag]
        stitch(tag, path, int(nchunks))
        print("ALL DONE", flush=True)
    else:
        only = sys.argv[1]
        if len(sys.argv) >= 5:
            lo, hi, suffix = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
            path = dict(DATASETS)[only]
            build(only, path, lo, hi, suffix)
        else:
            path = dict(DATASETS)[only]
            out = os.path.join(SCRATCH, f"fcache_{only}.pkl")
            if os.path.exists(out):
                print(f"{only}: exists, skip", flush=True)
            else:
                build(only, path)
        print("ALL DONE", flush=True)
