import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
import csv, math, json, os, statistics
from hl_swing_bot.backtest import HourlyBar, _compute_features_at, _resolve_outcome, BTSignal
from hl_swing_bot.features import MIN_BARS

FEE = 0.19
SLIP2 = 0.10  # 5bps each side -> 0.10 pct, matches run_backtest realized adjustment
STOP_ATR = 1.5
HOUR_MS = 3600*1000

def load(path):
    bars = []
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            bars.append(HourlyBar(int(row['open_time_ms']), float(row['open']), float(row['high']),
                                   float(row['low']), float(row['close']), float(row['volume']), int(row['trades'])))
    return bars

def plog(m):
    with open('scratch/expand_progress.txt','a') as f:
        f.write(m+'\n')

def get_feats(key, bars):
    # Do NOT JSON-cache: serializing 26k dicts segfaults CPython3.13 alongside the loop.
    feats = []
    for i in range(len(bars)):
        try:
            feats.append(_compute_features_at(bars, i))
        except Exception:
            feats.append(None)
        if i % 4000 == 0:
            plog(f'  feats {key} at {i}')
    return feats

def resolve(bars, idx, entry, stop, target, ttl, be_trigger=0.0):
    sig = BTSignal(idx=idx, bar_close_ms=bars[idx].hour_ms+HOUR_MS, direction='SHORT',
                   entry=entry, stop=stop, target=target, score=0.0, expires_idx=idx+ttl)
    _resolve_outcome(bars, sig, ttl_bars=ttl, be_trigger=be_trigger)
    return sig

def run_rule(bars, feats, entry_fn, *, target_atr, ttl, cooldown_h, be_trigger_atr=0.0, stop_atr=STOP_ATR):
    """Generic short-only rule runner. entry_fn(feats,i,bars)->bool.
    Returns list of net realized pct + ms."""
    out = []
    last_idx = -10**9
    for i in range(MIN_BARS, len(bars)):
        f = feats[i]
        if f is None: continue
        if i - last_idx < cooldown_h: continue
        if not entry_fn(feats, i, bars): continue
        atr = f['atr_1h']; entry = f['close']
        stop = entry + stop_atr*atr
        target = entry - target_atr*atr
        be = be_trigger_atr*atr if be_trigger_atr>0 else 0.0
        sig = resolve(bars, i, entry, stop, target, ttl, be)
        net = sig.realized_pct - SLIP2 - FEE
        out.append((bars[i].hour_ms, net, sig.status))
        last_idx = i
    return out

# ---------- candidate entry rules ----------
def in_downtrend(f):
    return f['trend_4h'] <= -1 and f['trend_4h_slope'] <= -1

def rule_redstreak_only(feats, i, bars, red_min=2):
    """Slow-bleed: confirmed downtrend + red 4h streak, NO impulse gate. Enter every cooldown window."""
    f = feats[i]
    return in_downtrend(f) and f['red_4h_streak'] >= red_min

def make_lowerlow(N):
    def rule(feats, i, bars):
        f = feats[i]
        if not in_downtrend(f): return False
        lo = bars[i].low
        # new N-bar low (continuation breakout to downside)
        return all(bars[i].close <= bars[j].low for j in range(max(0,i-N), i))
    return rule

def make_pullback_fade(bounce_atr):
    """Short on a green 1h bounce inside a downtrend (fade the rally)."""
    def rule(feats, i, bars):
        f = feats[i]
        if not in_downtrend(f): return False
        # current bar is green (bounce) of size >= bounce_atr*atr in ret_1h
        return f['ret_1h'] > 0 and (f['ret_1h']/max(f['atr_pct'],1e-9)) >= bounce_atr
    return rule

def make_sma_reclaim_fail(N):
    """Short when close is below the N-bar SMA in a downtrend (trend-follow continuation)."""
    def rule(feats, i, bars):
        f = feats[i]
        if not in_downtrend(f): return False
        sma = statistics.mean(b.close for b in bars[max(0,i-N+1):i+1])
        return bars[i].close < sma
    return rule

def stats(rows, years):
    if not rows:
        return dict(n=0, net_sum=0.0, net_per=0.0, per_yr=0.0, wr=0.0)
    nets = [r[1] for r in rows]
    n=len(nets); s=sum(nets); wr=sum(1 for x in nets if x>0)/n
    return dict(n=n, net_sum=s, net_per=s/n, per_yr=n/years, wr=wr*100)

def split_half(rows, mid_ms):
    h1=[r for r in rows if r[0]<mid_ms]; h2=[r for r in rows if r[0]>=mid_ms]
    return (sum(r[1] for r in h1), len(h1)), (sum(r[1] for r in h2), len(h2))

def annualized_05pct(rows, years):
    """R-multiple equity path at 0.5% risk/trade. Risk = stop distance => loss=-1R.
    Convert each trade net% to R: net%/(stop_atr*atr_pct) approx. Simpler: assume each
    trade risks 0.5% equity; R = net_pct / (typical stop loss pct). We approximate stop
    loss pct as the avg losing trade magnitude. Use compounding over equity.
    Here we map: position sized so a stop-out = -0.5% equity. So equity mult per trade =
    1 + 0.005 * (net_pct / stop_loss_pct_abs)."""
    nets=[r[1] for r in rows]
    losers=[x for x in nets if x<0]
    if not losers:
        stop_loss_abs = STOP_ATR  # fallback
    else:
        stop_loss_abs = abs(statistics.median(losers))
    if stop_loss_abs < 0.1: stop_loss_abs=0.1
    eq=1.0
    for x in nets:
        R = x/stop_loss_abs
        eq *= (1 + 0.005*R)
        if eq<=0: eq=1e-9
    total_ret = eq-1
    ann = (eq**(1/years)-1) if eq>0 else -1
    return ann*100, total_ret*100

def main():
    open('scratch/expand_progress.txt','w').close()
    plog('=== EXPAND START ===')
    assets = [('btc','scratch/binance_btc_3y.csv'), ('eth','scratch/binance_eth_3y.csv')]
    data={}
    for key,path in assets:
        print(f'[load {key}]', flush=True)
        bars=load(path)
        feats=get_feats(key,bars)
        years=(bars[-1].hour_ms-bars[0].hour_ms)/1000/3600/24/365.25
        mid=(bars[0].hour_ms+bars[-1].hour_ms)//2
        data[key]=(bars,feats,years,mid)
        print(f'[ready {key}] bars={len(bars)} years={years:.2f}', flush=True)

    # candidate definitions: (name, entry_fn_factory, target_atr, ttl, cooldown_h, be)
    candidates = [
        ('redstreak2_t2.5_ttl72_cd24', lambda f,i,b: rule_redstreak_only(f,i,b,2), 2.5, 72, 24, 0.0),
        ('redstreak2_t4_ttl120_cd24',  lambda f,i,b: rule_redstreak_only(f,i,b,2), 4.0, 120, 24, 0.0),
        ('redstreak3_t4_ttl120_cd24',  lambda f,i,b: rule_redstreak_only(f,i,b,3), 4.0, 120, 24, 0.0),
        ('lowerlow24_t4_ttl120_cd12',  make_lowerlow(24), 4.0, 120, 12, 0.0),
        ('lowerlow48_t4_ttl168_cd24',  make_lowerlow(48), 4.0, 168, 24, 0.0),
        ('pullback0.7_t2.5_ttl72_cd12', make_pullback_fade(0.7), 2.5, 72, 12, 0.0),
        ('pullback1.0_t3_ttl96_cd12',  make_pullback_fade(1.0), 3.0, 96, 12, 0.0),
        ('sma24below_t4_ttl120_cd24',  make_sma_reclaim_fail(24), 4.0, 120, 24, 0.0),
        ('sma48below_t5_ttl168_cd48',  make_sma_reclaim_fail(48), 5.0, 168, 48, 0.0),
        # be variants on best structural ones
        ('lowerlow24_t4_ttl120_cd12_be1', make_lowerlow(24), 4.0, 120, 12, 1.0),
        ('redstreak2_t4_ttl120_cd24_be1', lambda f,i,b: rule_redstreak_only(f,i,b,2), 4.0, 120, 24, 1.0),
    ]

    print('\n===== CANDIDATE RESULTS (NET per trade, after fees+slip) =====', flush=True)
    print(f'{"name":36s} {"asset":4s} {"n":>4s} {"net/tr":>7s} {"netSum":>8s} {"tr/yr":>6s} {"wr%":>5s} {"H1net":>7s} {"H2net":>7s} {"ann%":>7s}', flush=True)
    results={}
    for cname, fac, tgt, ttl, cd, be in candidates:
        for key,(bars,feats,years,mid) in data.items():
            rows = run_rule(bars, feats, fac, target_atr=tgt, ttl=ttl, cooldown_h=cd, be_trigger_atr=be)
            st = stats(rows, years)
            (h1s,h1n),(h2s,h2n)=split_half(rows, mid)
            ann,_=annualized_05pct(rows, years)
            results[(cname,key)]=(st,(h1s,h1n),(h2s,h2n),ann)
            line=f'{cname:36s} {key:4s} {st["n"]:4d} {st["net_per"]:7.3f} {st["net_sum"]:8.1f} {st["per_yr"]:6.1f} {st["wr"]:5.1f} {h1s:7.1f} {h2s:7.1f} {ann:7.2f}'
            print(line, flush=True); plog(line)
        print('', flush=True)

    # decide robustness: net_per>0 both assets, H1>0 and H2>0 both assets
    print('===== ROBUSTNESS SCREEN =====', flush=True)
    cnames = list(dict.fromkeys(c[0] for c in candidates))
    for cname in cnames:
        ok=True; detail=[]
        for key in ('btc','eth'):
            st,(h1s,h1n),(h2s,h2n),ann = results[(cname,key)]
            cond = st['net_per']>0 and h1s>0 and h2s>0 and st['n']>=20
            ok = ok and cond
            detail.append(f"{key}:net/tr={st['net_per']:.3f},H1={h1s:.0f},H2={h2s:.0f},n={st['n']}")
        flag='PASS' if ok else 'FAIL'
        rline=f'  [{flag}] {cname} | '+' | '.join(detail)
        print(rline, flush=True); plog(rline)
    plog('=== EXPAND DONE ===')

if __name__=='__main__':
    main()
