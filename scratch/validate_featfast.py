"""Validate feat_fast.compute_all == module _compute_features_at, using the
already-built module caches (btc3y, btchl, ethhl)."""
import sys, types, os, pickle
sys.modules['duckdb'] = types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feat_fast

SCRATCH = os.path.dirname(os.path.abspath(__file__))
KEYS = ["close","atr_1h","atr_pct","ret_1h","ret_4h","move_per_atr",
        "move_per_atr_z","robust_z_168","vol_z_168","trend_4h",
        "trend_4h_slope","red_4h_streak"]

for tag in ["btchl","ethhl","btc3y"]:
    with open(os.path.join(SCRATCH, f"fcache_{tag}.pkl"),"rb") as fh:
        cache = pickle.load(fh)
    mod = cache["feats"]; raw = cache["raw"]
    fast = feat_fast.compute_all(raw)
    n = cache["n"]
    nboth = 0; nmis = 0; maxdiff = {k:0.0 for k in KEYS}
    none_mismatch = 0
    examples = []
    for i in range(n):
        a = mod[i]; b = fast[i]
        if (a is None) != (b is None):
            none_mismatch += 1
            if len(examples) < 5: examples.append(("NONE",i,a is None,b is None))
            continue
        if a is None:
            continue
        nboth += 1
        bad = False
        for k in KEYS:
            d = abs((a[k] or 0) - (b[k] or 0))
            if d > maxdiff[k]: maxdiff[k] = d
            if k in ("trend_4h","trend_4h_slope","red_4h_streak"):
                if a[k] != b[k]:
                    bad = True
            else:
                if d > 1e-6:
                    bad = True
        if bad:
            nmis += 1
            if len(examples) < 8:
                examples.append((i, {k:(round(a[k],4),round(b[k],4)) for k in KEYS if abs((a[k] or 0)-(b[k] or 0))>1e-6 or a[k]!=b[k]}))
    print(f"{tag}: both={nboth} none_mismatch={none_mismatch} value_mismatch={nmis}")
    print("   maxdiff:", {k:round(v,8) for k,v in maxdiff.items() if v>1e-9})
    for e in examples[:6]:
        print("   ex", e)
