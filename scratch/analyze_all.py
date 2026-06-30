import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
import pickle, math, statistics
from hl_swing_bot.backtest import HourlyBar, _resolve_outcome, BTSignal
from hl_swing_bot.features import MIN_BARS

FEE = 0.19
SLIP2 = 0.10      # 5bps each side
STOP_ATR = 1.5
HOUR_MS = 3600*1000
COST = FEE + SLIP2   # total round-trip cost in pct applied to gross realized

def load(pkl):
    with open(pkl,'rb') as f: d=pickle.load(f)
    bars=[HourlyBar(*t) for t in d['bars']]
    feats=d['feats']
    return bars, feats

def years_of(bars):
    return (bars[-1].hour_ms-bars[0].hour_ms)/1000/3600/24/365.25

# ---------------- shipped baseline (replicate run_backtest gating from cached feats) ----------------
from hl_swing_bot.signal import (COOLDOWN_OPP_DIR_MIN, COOLDOWN_SAME_DIR_MIN,
    FIRE_MOVE_PER_ATR_MIN, FIRE_RED_4H_MIN, FIRE_SCORE_MIN, FIRE_VOL_Z_MIN,
    SIGNAL_TTL_HOURS, STOP_ATR_MULT, TARGET_ATR_MULT)

def composite_score(f):
    return (0.30*abs(f['move_per_atr_z']) + 0.25*abs(f['robust_z_168']) + 0.20*f['vol_z_168']
            + 0.15*abs(f['ret_4h'])/max(f['atr_pct'],1e-9) + 0.10*1.0)

def resolve_short(bars, i, target_atr, ttl, be_trigger_atr=0.0, stop_atr=STOP_ATR):
    f_atr = None
    # use feats atr via bars? we need atr_1h from feats; pass in
    raise RuntimeError('use resolve2')

def run_short_rule(bars, feats, entry_fn, *, target_atr, ttl, cooldown_h, be_trigger_atr=0.0, stop_atr=STOP_ATR, dir_logic=False):
    """entry_fn(feats,i,bars)->bool. SHORT only. Returns [(ms, net, status, idx, exit_idx)]."""
    out=[]; last_idx=-10**9
    for i in range(MIN_BARS, len(bars)):
        f=feats[i]
        if f is None: continue
        if i-last_idx < cooldown_h: continue
        if not entry_fn(feats,i,bars): continue
        atr=f['atr_1h']; entry=f['close']
        stop=entry+stop_atr*atr; target=entry-target_atr*atr
        be=be_trigger_atr*atr if be_trigger_atr>0 else 0.0
        sig=BTSignal(idx=i,bar_close_ms=bars[i].hour_ms+HOUR_MS,direction='SHORT',
                     entry=entry,stop=stop,target=target,score=0.0,expires_idx=i+ttl)
        _resolve_outcome(bars,sig,ttl_bars=ttl,be_trigger=be)
        net=sig.realized_pct - COST
        out.append((bars[i].hour_ms, net, sig.status, i, sig.exit_idx))
        last_idx=i
    return out

# ----- shipped baseline rule (mirrors run_backtest short_only defaults) -----
def baseline_entry(feats,i,bars):
    f=feats[i]
    if f['ret_1h']>0: return False  # SHORT requires down 1h
    score=composite_score(f)
    if not (score>=FIRE_SCORE_MIN): return False
    if not (f['move_per_atr']>=FIRE_MOVE_PER_ATR_MIN): return False
    if not (f['vol_z_168']>=FIRE_VOL_Z_MIN): return False
    if not (f['trend_4h']<=-1): return False
    if not (f['trend_4h_slope']<=-1): return False
    if not (f['red_4h_streak']>=FIRE_RED_4H_MIN): return False
    return True

def run_baseline(bars,feats):
    # baseline uses its own cooldown (same-dir 240min=4 bars). Approx with cd=4 and short-only.
    return run_short_rule(bars,feats,baseline_entry,target_atr=TARGET_ATR_MULT,ttl=SIGNAL_TTL_HOURS,cooldown_h=4)

# ---------------- episode detection ----------------
def find_episodes(bars, drop_thresh=-8.0, min_len_h=240, recover_frac=0.5):
    """Peak->trough downtrend episodes. State machine:
    track running peak; when price recovers >= recover_frac of the peak->trough drop
    above the trough, the episode closes. Record [peak_idx..trough_idx] if the
    drawdown <= drop_thresh and duration >= min_len_h. Non-overlapping, ordered."""
    closes=[b.close for b in bars]; n=len(closes); episodes=[]
    i=0
    while i<n:
        peak_idx=i; peak=closes[i]
        # advance peak while making new highs immediately
        trough_idx=i; trough=closes[i]
        j=i+1
        closed=False
        while j<n:
            c=closes[j]
            if c>peak and trough_idx==peak_idx:
                # still rising before any drop: move peak up
                peak=c; peak_idx=j; trough=c; trough_idx=j
            else:
                if c<trough:
                    trough=c; trough_idx=j
                # recovery test: has price retraced recover_frac of the drop?
                drop=peak-trough
                if drop>0 and (c-trough) >= recover_frac*drop and trough_idx>peak_idx:
                    closed=True
                    break
                # also: new higher-high before any meaningful drop resets the peak
                if c>peak and trough_idx==peak_idx:
                    peak=c; peak_idx=j; trough=c; trough_idx=j
            j+=1
        dd=(trough/peak-1)*100 if peak>0 else 0.0
        if dd<=drop_thresh and (trough_idx-peak_idx)>=min_len_h:
            episodes.append((peak_idx,trough_idx,dd))
            i=trough_idx+1
        else:
            # advance past this peak region
            i = (trough_idx+1) if closed else (peak_idx+1)
        if i<=peak_idx: i=peak_idx+1
    return episodes

def pctile(xs,q):
    if not xs: return float('nan')
    s=sorted(xs); idx=q*(len(s)-1); lo=int(math.floor(idx)); hi=int(math.ceil(idx))
    return s[lo] if lo==hi else s[lo]+(s[hi]-s[lo])*(idx-lo)

def stat(rows, years):
    if not rows: return dict(n=0,net_sum=0,net_per=0,per_yr=0,wr=0)
    nets=[r[1] for r in rows]; n=len(nets); s=sum(nets)
    return dict(n=n,net_sum=s,net_per=s/n,per_yr=n/years,wr=sum(1 for x in nets if x>0)/n*100)

def split_half(rows, mid):
    h1=[r for r in rows if r[0]<mid]; h2=[r for r in rows if r[0]>=mid]
    return (sum(r[1] for r in h1),len(h1)),(sum(r[1] for r in h2),len(h2))

def annualized_05(rows, years):
    nets=[r[1] for r in rows]
    if not nets: return 0.0
    losers=[x for x in nets if x<0]
    sl=abs(statistics.median(losers)) if losers else STOP_ATR
    if sl<0.1: sl=0.1
    eq=1.0
    for x in nets:
        eq*=(1+0.005*(x/sl))
        if eq<=0: eq=1e-9
    return ((eq**(1/years))-1)*100 if eq>0 else -100

def out(*a):
    line=' '.join(str(x) for x in a)
    print(line, flush=True)
    with open('scratch/analyze_out.txt','a') as f: f.write(line+'\n')

# ---------------- candidate entry rules (slow-bleed capture) ----------------
def in_downtrend(f):
    return f['trend_4h']<=-1 and f['trend_4h_slope']<=-1

def rule_redstreak(red_min):
    def r(feats,i,bars):
        f=feats[i]
        return in_downtrend(f) and f['red_4h_streak']>=red_min
    return r

def rule_lowerlow(N):
    def r(feats,i,bars):
        f=feats[i]
        if not in_downtrend(f): return False
        c=bars[i].close
        return all(c <= bars[j].low for j in range(max(0,i-N), i))
    return r

def rule_pullback_fade(bounce_atr):
    def r(feats,i,bars):
        f=feats[i]
        if not in_downtrend(f): return False
        return f['ret_1h']>0 and (f['ret_1h']/max(f['atr_pct'],1e-9))>=bounce_atr
    return r

def rule_sma_below(N):
    def r(feats,i,bars):
        f=feats[i]
        if not in_downtrend(f): return False
        sma=statistics.mean(b.close for b in bars[max(0,i-N+1):i+1])
        return bars[i].close < sma
    return r

# ---------------- DIAGNOSTIC ----------------
def diagnose(name, bars, feats, baseline_rows):
    n=len(bars); years=years_of(bars)
    out(f'\n===== DIAGNOSE {name} (years={years:.2f}) =====')
    st=stat(baseline_rows, years)
    out(f'[BASELINE shipped] trades={st["n"]} net/trade={st["net_per"]:.3f}% net_sum={st["net_sum"]:.1f}% trades/yr={st["per_yr"]:.1f} wr={st["wr"]:.1f}%')
    eps=find_episodes(bars,-8.0,240)
    out(f'[EPISODES] count={len(eps)} (peak->trough dd<=-8%, dur>=10d)')
    base_idx={r[3]:r[1] for r in baseline_rows}
    SLOW_MAX_MPA=3.0
    tot_h=0; slow_h=0; fast_h=0; slow_cap=0.0; fast_cap=0.0; slow_e=0; fast_e=0
    in_ep_tr=0; in_ep_net=0.0; mpa_in=[]; volz_in=[]; ep_rows=[]
    for (p,t,dd) in eps:
        dur=t-p; tot_h+=dur
        mm=0.0
        for k in range(p+1,t+1):
            f=feats[k]
            if f is None: continue
            a=abs(f['move_per_atr']); mpa_in.append(a); volz_in.append(f['vol_z_168'])
            if a>mm: mm=a
        gross_hold=(bars[p].close/bars[t].close-1)*100  # short profit peak->trough
        net_hold=gross_hold-COST
        et=0; en=0.0
        for k in range(p,t+1):
            if k in base_idx: et+=1; en+=base_idx[k]
        in_ep_tr+=et; in_ep_net+=en
        slow = mm<SLOW_MAX_MPA
        if slow: slow_e+=1; slow_h+=dur; slow_cap+= gross_hold
        else: fast_e+=1; fast_h+=dur; fast_cap+= gross_hold
        ep_rows.append((p,t,dd,dur,mm,gross_hold,et,en,'SLOW' if slow else 'FAST'))
    out(f'[EP COVERAGE] ep_hours={tot_h} ({tot_h/n*100:.1f}% of bars)  trades_in_eps={in_ep_tr} net_in_eps={in_ep_net:.1f}%')
    out(f'  SLOW eps={slow_e} hrs={slow_h} ({slow_h/max(1,tot_h)*100:.0f}%)  capturable_shortmove_sum={slow_cap:.0f}%')
    out(f'  FAST eps={fast_e} hrs={fast_h} ({fast_h/max(1,tot_h)*100:.0f}%)  capturable_shortmove_sum={fast_cap:.0f}%')
    tc=slow_cap+fast_cap
    out(f'  capturable move share: SLOW={slow_cap/max(.01,tc)*100:.0f}%  FAST={fast_cap/max(.01,tc)*100:.0f}%')
    out(f'[NAIVE peak->trough short, 1 per ep] sum_gross={sum(r[5] for r in ep_rows):.0f}% sum_net={sum(r[5]-COST for r in ep_rows):.0f}%')
    out(f'[WHY NO FIRE inside eps] |move_per_atr|: p50={pctile([abs(x) for x in mpa_in],.5):.2f} p90={pctile([abs(x) for x in mpa_in],.9):.2f} p99={pctile([abs(x) for x in mpa_in],.99):.2f}')
    out(f'  frac bars |move_per_atr|>=1.0: {sum(1 for x in mpa_in if abs(x)>=1)/max(1,len(mpa_in))*100:.1f}%   frac vol_z>=1.0: {sum(1 for x in volz_in if x>=1)/max(1,len(volz_in))*100:.1f}%')
    # top episodes
    from datetime import datetime, timezone
    out('[TOP EPISODES by depth]')
    for r in sorted(ep_rows,key=lambda x:x[2])[:12]:
        p,t,dd,dur,mm,gh,et,en,cls=r
        ps=datetime.fromtimestamp(bars[p].hour_ms/1000,tz=timezone.utc).strftime('%Y-%m-%d')
        ts=datetime.fromtimestamp(bars[t].hour_ms/1000,tz=timezone.utc).strftime('%Y-%m-%d')
        out(f'  {ps}->{ts} dd={dd:6.1f}% dur={dur:4d}h maxMPA={mm:4.1f} shortHold={gh:6.1f}% baseTr={et} baseNet={en:6.2f}% {cls}')
    return dict(years=years, base=st, eps=len(eps), slow_e=slow_e, fast_e=fast_e,
                slow_cap=slow_cap, fast_cap=fast_cap, in_ep_tr=in_ep_tr, in_ep_net=in_ep_net,
                naive_net=sum(r[5]-COST for r in ep_rows), ep_rows=ep_rows)

# ---------------- EXPANSION ----------------
CANDS=[
    ('redstreak2_t2.5_ttl72_cd24', rule_redstreak(2), 2.5,72,24,0.0),
    ('redstreak2_t4_ttl120_cd24',  rule_redstreak(2), 4.0,120,24,0.0),
    ('redstreak3_t4_ttl120_cd24',  rule_redstreak(3), 4.0,120,24,0.0),
    ('lowerlow24_t4_ttl120_cd12',  rule_lowerlow(24), 4.0,120,12,0.0),
    ('lowerlow48_t4_ttl168_cd24',  rule_lowerlow(48), 4.0,168,24,0.0),
    ('lowerlow48_t6_ttl240_cd24',  rule_lowerlow(48), 6.0,240,24,0.0),
    ('pullback0.7_t2.5_ttl72_cd12',rule_pullback_fade(0.7),2.5,72,12,0.0),
    ('pullback1.0_t3_ttl96_cd12',  rule_pullback_fade(1.0),3.0,96,12,0.0),
    ('sma24below_t4_ttl120_cd24',  rule_sma_below(24), 4.0,120,24,0.0),
    ('sma48below_t5_ttl168_cd48',  rule_sma_below(48), 5.0,168,48,0.0),
    ('lowerlow24_t4_ttl120_cd12_be1', rule_lowerlow(24),4.0,120,12,1.0),
    ('redstreak2_t4_ttl120_cd24_be1', rule_redstreak(2),4.0,120,24,1.0),
]

def expand(data):
    out('\n===== EXPANSION CANDIDATES (NET/trade after fees+slip 0.29%) =====')
    out(f'{"name":34s} {"as":3s} {"n":>4s} {"net/tr":>7s} {"netSum":>8s} {"tr/yr":>6s} {"wr%":>5s} {"H1":>7s} {"H2":>7s} {"ann%":>7s}')
    R={}
    for cn,fn,tg,tl,cd,be in CANDS:
        for key,(bars,feats,years,mid) in data.items():
            rows=run_short_rule(bars,feats,fn,target_atr=tg,ttl=tl,cooldown_h=cd,be_trigger_atr=be)
            st=stat(rows,years); (h1,_),(h2,_)=split_half(rows,mid); ann=annualized_05(rows,years)
            R[(cn,key)]=(st,h1,h2,ann,rows)
            out(f'{cn:34s} {key:3s} {st["n"]:4d} {st["net_per"]:7.3f} {st["net_sum"]:8.1f} {st["per_yr"]:6.1f} {st["wr"]:5.1f} {h1:7.1f} {h2:7.1f} {ann:7.2f}')
        out('')
    out('===== ROBUSTNESS SCREEN (need: net/tr>0 both, H1>0 & H2>0 both, n>=20) =====')
    passers=[]
    for cn in dict.fromkeys(c[0] for c in CANDS):
        ok=True; det=[]
        for key in [k for k in data]:
            st,h1,h2,ann,_=R[(cn,key)]
            cond=st['net_per']>0 and h1>0 and h2>0 and st['n']>=20
            ok=ok and cond
            det.append(f"{key}:n={st['n']},net/tr={st['net_per']:.3f},H1={h1:.0f},H2={h2:.0f},ann={ann:.1f}")
        flag='PASS' if ok else 'FAIL'
        if ok: passers.append(cn)
        out(f'  [{flag}] {cn} | '+' | '.join(det))
    return R, passers


# ---------------- HL 208d check ----------------
def hl_check(R_passers, hl_data):
    out('\n===== HL 208d LIVE-INSTRUMENT CHECK (same sign required) =====')
    res={}
    for cn,fn,tg,tl,cd,be in CANDS:
        for key,(bars,feats,years,mid) in hl_data.items():
            rows=run_short_rule(bars,feats,fn,target_atr=tg,ttl=tl,cooldown_h=cd,be_trigger_atr=be)
            st=stat(rows,years); ann=annualized_05(rows,years)
            res[(cn,key)]=(st,ann)
    return res

def main():
    open('scratch/analyze_out.txt','w').close()
    # 3y data
    d3={}
    for key,pkl in [('btc','scratch/feats_btc_3y.pkl'),('eth','scratch/feats_eth_3y.pkl')]:
        bars,feats=load(pkl); d3[key]=(bars,feats,years_of(bars),(bars[0].hour_ms+bars[-1].hour_ms)//2)
    # HL data
    dhl={}
    for key,pkl in [('btc','scratch/feats_hist_btc.pkl'),('eth','scratch/feats_hist_eth.pkl')]:
        bars,feats=load(pkl); dhl[key]=(bars,feats,years_of(bars),(bars[0].hour_ms+bars[-1].hour_ms)//2)

    # baselines (replicated from cached feats)
    base_rows={}
    for key,(bars,feats,years,mid) in d3.items():
        base_rows[key]=run_baseline(bars,feats)
    out('=== BASELINE VALIDATION (replicated vs known run_backtest: BTC should ~86 sigs) ===')
    for key in d3:
        out(f'  {key}: replicated_baseline_trades={len(base_rows[key])}')

    # diagnostic
    diag={}
    for key,(bars,feats,years,mid) in d3.items():
        diag[key]=diagnose(key, bars, feats, base_rows[key])

    # expansion
    R,passers=expand(d3)
    out(f'\n[3y PASSERS] {passers}')

    # HL check for everything
    hlres=hl_check(passers, dhl)
    out('\n===== HL 208d results (all candidates) =====')
    out(f'{"name":34s} {"as":3s} {"n":>4s} {"net/tr":>7s} {"netSum":>8s} {"ann%":>7s}')
    for cn,fn,tg,tl,cd,be in CANDS:
        for key in dhl:
            st,ann=hlres[(cn,key)]
            out(f'{cn:34s} {key:3s} {st["n"]:4d} {st["net_per"]:7.3f} {st["net_sum"]:8.1f} {ann:7.2f}')

    # FINAL combined verdict per candidate
    out('\n===== FINAL: 3y-pass AND HL-same-sign =====')
    for cn in dict.fromkeys(c[0] for c in CANDS):
        threey_ok = cn in passers
        hl_ok=True; hldet=[]
        for key in dhl:
            st,ann=hlres[(cn,key)]
            # same sign = net/tr>0 on HL (lenient: just positive, n>=10)
            cond = st['net_per']>0 and st['n']>=10
            hl_ok=hl_ok and cond
            hldet.append(f"{key}:n={st['n']},net/tr={st['net_per']:.3f}")
        verdict='ROBUST' if (threey_ok and hl_ok) else ('3y-only' if threey_ok else 'reject')
        out(f'  [{verdict}] {cn} | 3y_pass={threey_ok} | HL: '+' | '.join(hldet))

    out('\n=== ANALYZE DONE ===')

if __name__=='__main__':
    main()
