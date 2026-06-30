"""Cadence x Exit sweep for mechanical trend participation, using cached feats.

Reuses _resolve_outcome (needs bars) but reads cached feature dicts to avoid the
O(n^2) recompute. Reports NET. Split-half + cross-asset + HL for survivors.
"""
import sys, types, json, os, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch'); sys.path.insert(0, 'src')
import warnings; warnings.filterwarnings('ignore')
from trend_participation import load_bars, FEE, net_stats, annualized_return
from hl_swing_bot.backtest import BTSignal, _resolve_outcome
from hl_swing_bot.signal import STOP_ATR_MULT
from hl_swing_bot.features import MIN_BARS

BARS = {}
FEATS = {}
def get(name, path):
    if name not in BARS:
        b, _ = load_bars(path)
        BARS[name] = b
        FEATS[name] = json.load(open(f'scratch/tp_feat_{name}.json'))['feats']
    return BARS[name], FEATS[name]

DS = {'btc_3y':'scratch/binance_btc_3y.csv','eth_3y':'scratch/binance_eth_3y.csv',
      'btc_hl':'scratch/hist_btc.csv','eth_hl':'scratch/hist_eth.csv'}


def engine(bars, feats, *, cadence_hours, exit_mode, target_atr_mult=2.5,
           ttl_hours=72, cluster_cap=3, require_slope=True, require_streak=0,
           idx_lo=None, idx_hi=None):
    sigs = []
    open_pos = []
    last_entry = -10**9
    lo = idx_lo if idx_lo is not None else MIN_BARS
    hi = idx_hi if idx_hi is not None else len(bars)
    for i in range(lo, hi):
        f = feats[i]
        if f is None:
            continue
        open_pos = [e for e in open_pos if e > i]
        if not (f['trend_4h'] <= -1):
            continue
        if require_slope and not (f['trend_4h_slope'] <= -1):
            continue
        if require_streak > 0 and f['red_4h_streak'] < require_streak:
            continue
        if (i - last_entry) < cadence_hours:
            continue
        if len(open_pos) >= cluster_cap:
            continue
        atr = f['atr_1h']; entry = f['close']
        if atr <= 0:
            continue
        stop = entry + STOP_ATR_MULT * atr
        if exit_mode == 'atr':
            target = entry - target_atr_mult * atr
            sig = BTSignal(idx=i, bar_close_ms=bars[i].hour_ms+3600000, direction='SHORT',
                           entry=entry, stop=stop, target=target, score=0.0,
                           expires_idx=i+ttl_hours)
            _resolve_outcome(bars, sig, ttl_bars=ttl_hours)
            exit_idx, realized, status = sig.exit_idx, sig.realized_pct, sig.status
        else:  # trend exit
            exit_idx = min(i+ttl_hours, len(bars)-1); status='TTL'; realized=None
            for j in range(i+1, min(i+ttl_hours, len(bars)-1)+1):
                b = bars[j]
                if b.high >= stop:
                    exit_idx=j; status='HIT_SL'; realized=(entry/stop-1)*100; break
                fj = feats[j]
                if fj is not None and fj['trend_4h'] >= 0:
                    exit_idx=j; status='TREND_FLIP'; realized=(entry/b.close-1)*100; break
            if realized is None:
                realized = (entry/bars[exit_idx].close-1)*100
        stop_dist = (stop/entry-1)*100
        sigs.append({'idx':i,'exit_idx':exit_idx,'realized_pct':realized,
                     'status':status,'stop_dist_pct':stop_dist})
        last_entry = i
        open_pos.append(exit_idx)
    return sigs


def captures_slowbleed(sigs, feats):
    """Fraction of trades entered on a NON-impulse bar (move_per_atr<1.0 AND
    vol_z<1.0) — i.e. bars the baseline would never have fired on."""
    if not sigs: return 0.0
    slow = 0
    for s in sigs:
        f = feats[s['idx']]
        if f and f['move_per_atr'] < 1.0 and f['vol_z_168'] < 1.0:
            slow += 1
    return slow/len(sigs)


def run_variant(name_btc, name_eth, **kw):
    bb, fb = get(name_btc, DS[name_btc])
    sb = engine(bb, fb, **kw)
    st = net_stats(sb, bb)
    st['slow_frac'] = captures_slowbleed(sb, fb)
    return st, sb


if __name__ == '__main__':
    # ---- 3y sweep on BTC, cadence x exit ----
    print("=== BTC 3y cadence x exit sweep (slope_gate ON, cluster_cap=3) ===")
    grid = []
    for cad in [4, 8, 12, 24, 48]:
        for exit_mode, tam in [('atr',2.5),('atr',4.0),('atr',6.0),('trend',None)]:
            kw = dict(cadence_hours=cad, exit_mode=exit_mode, cluster_cap=3,
                      require_slope=True, ttl_hours=72)
            if tam is not None: kw['target_atr_mult']=tam
            st, _ = run_variant('btc_3y','btc_3y', **kw)
            tag = f"cad{cad}h/{exit_mode}{'' if tam is None else tam}"
            grid.append((tag, kw, st))
            print(f"{tag:18s} n={st['n']:4d} net/trade={st['net_per_trade']:+.3f} "
                  f"net_tot={st['net_total']:+8.1f} tpy={st['trades_per_yr']:6.1f} "
                  f"win={st['winrate']:.2f} ann={st['ann']:+.1f}% slow={st['slow_frac']:.2f}", flush=True)
    # rank by net_total (must be positive)
    grid.sort(key=lambda x: x[2]['net_total'], reverse=True)
    json.dump([{'tag':t,'kw':{k:v for k,v in kw.items()},'st':st} for t,kw,st in grid],
              open('scratch/tp_sweep_btc3y.json','w'), indent=2, default=str)
    print("\nTOP 5 by net_total:")
    for t,kw,st in grid[:5]:
        print(f"  {t}: net/trade={st['net_per_trade']:+.3f} net_tot={st['net_total']:+.1f} ann={st['ann']:+.1f}%")
    print('SWEEP DONE', flush=True)
