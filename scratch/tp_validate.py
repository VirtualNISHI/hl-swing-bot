"""Strict validation of the marginal survivor (cad48h/trend) + robustness probes.

Gates: (a) split-half 3y both net-positive, (b) cross-asset BTC&ETH both positive,
(c) HL 208d same sign. Also probe wider stops / cluster_cap=1 to see if anything
flips the whole regime profitable.
"""
import sys, types, json, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch'); sys.path.insert(0, 'src')
import warnings; warnings.filterwarnings('ignore')
from trend_participation import load_bars, FEE, net_stats
from tp_sweep import engine, get, DS, captures_slowbleed
from hl_swing_bot.features import MIN_BARS


def split_half(name, **kw):
    bars, feats = get(name, DS[name])
    mid = MIN_BARS + (len(bars) - MIN_BARS) // 2
    s1 = engine(bars, feats, idx_lo=MIN_BARS, idx_hi=mid, **kw)
    s2 = engine(bars, feats, idx_lo=mid, idx_hi=len(bars), **kw)
    full = engine(bars, feats, **kw)
    return net_stats(s1, bars), net_stats(s2, bars), net_stats(full, bars), feats, full


def show(tag, h1, h2, full, feats, sigs):
    sf = captures_slowbleed(sigs, feats)
    print(f"\n--- {tag} ---")
    print(f"  H1: n={h1['n']:4d} net/tr={h1['net_per_trade']:+.3f} tot={h1['net_total']:+.1f}")
    print(f"  H2: n={h2['n']:4d} net/tr={h2['net_per_trade']:+.3f} tot={h2['net_total']:+.1f}")
    print(f"  FULL: n={full['n']:4d} net/tr={full['net_per_trade']:+.3f} tot={full['net_total']:+.1f} "
          f"win={full['winrate']:.2f} ann={full['ann']:+.1f}% slow={sf:.2f}")
    return h1['net_per_trade']>0 and h2['net_per_trade']>0


VARIANTS = {
    'cad48h/trend cap3': dict(cadence_hours=48, exit_mode='trend', cluster_cap=3, require_slope=True, ttl_hours=72),
    'cad48h/trend cap1': dict(cadence_hours=48, exit_mode='trend', cluster_cap=1, require_slope=True, ttl_hours=72),
    'cad24h/trend cap1': dict(cadence_hours=24, exit_mode='trend', cluster_cap=1, require_slope=True, ttl_hours=72),
    'cad24h/atr6 cap1':  dict(cadence_hours=24, exit_mode='atr', target_atr_mult=6.0, cluster_cap=1, require_slope=True, ttl_hours=72),
    'cad48h/trend ttl168': dict(cadence_hours=48, exit_mode='trend', cluster_cap=1, require_slope=True, ttl_hours=168),
}

print("=== BTC 3y split-half on candidate variants ===")
btc_pass = {}
for tag, kw in VARIANTS.items():
    h1, h2, full, feats, sigs = split_half('btc_3y', **kw)
    btc_pass[tag] = show(tag, h1, h2, full, feats, sigs)

print("\n\n=== ETH 3y (cross-asset) on same variants ===")
for tag, kw in VARIANTS.items():
    h1, h2, full, feats, sigs = split_half('eth_3y', **kw)
    show(tag, h1, h2, full, feats, sigs)

print("\n\n=== HL 208d (live instrument) ===")
for tag, kw in VARIANTS.items():
    for asset in ('btc_hl','eth_hl'):
        bars, feats = get(asset, DS[asset])
        sigs = engine(bars, feats, **kw)
        st = net_stats(sigs, bars)
        print(f"  {asset} {tag:22s}: n={st['n']:3d} net/tr={st['net_per_trade']:+.3f} tot={st['net_total']:+.1f} ann={st['ann']:+.1f}%")

print("\nVALIDATE DONE", flush=True)
