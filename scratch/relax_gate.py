import sys,types; sys.modules['duckdb']=types.ModuleType('duckdb')
import pickle, statistics
from hl_swing_bot.backtest import HourlyBar,_resolve_outcome,BTSignal
from hl_swing_bot.features import MIN_BARS
FEE=0.19; SLIP2=0.10; COST=FEE+SLIP2; HOUR_MS=3600*1000
def load(p):
    d=pickle.load(open(p,'rb')); return [HourlyBar(*t) for t in d['bars']], d['feats']
def years(bars): return (bars[-1].hour_ms-bars[0].hour_ms)/1000/3600/24/365.25
def cscore(f): return 0.30*abs(f['move_per_atr_z'])+0.25*abs(f['robust_z_168'])+0.20*f['vol_z_168']+0.15*abs(f['ret_4h'])/max(f['atr_pct'],1e-9)+0.10
def run(bars,feats,entry,target_atr,ttl,cd,stop_atr=1.5,be=0.0):
    out=[];li=-10**9
    for i in range(MIN_BARS,len(bars)):
        f=feats[i]
        if f is None or i-li<cd: continue
        if not entry(f,i,bars): continue
        atr=f['atr_1h'];e=f['close']
        sig=BTSignal(idx=i,bar_close_ms=bars[i].hour_ms+HOUR_MS,direction='SHORT',entry=e,stop=e+stop_atr*atr,target=e-target_atr*atr,score=0.0,expires_idx=i+ttl)
        _resolve_outcome(bars,sig,ttl_bars=ttl,be_trigger=be*atr if be>0 else 0.0)
        out.append((bars[i].hour_ms,sig.realized_pct-COST)); li=i
    return out
def rep(name,rows,yr,mid):
    if not rows: print(f'{name}: n=0'); return
    nets=[r[1] for r in rows];n=len(nets);s=sum(nets)
    h1=sum(r[1] for r in rows if r[0]<mid);h2=sum(r[1] for r in rows if r[0]>=mid)
    print(f'{name}: n={n} net/tr={s/n:.3f} netSum={s:.1f} tr/yr={n/yr:.1f} H1={h1:.1f} H2={h2:.1f}')

# minimal relaxation: keep score+slope+streak gate but DROP move_min & vol_min (the impulse gates)
def relax_keepscore(f,i,bars):
    if f['ret_1h']>0: return False
    if cscore(f)<3.0: return False
    if f['trend_4h']>-1 or f['trend_4h_slope']>-1: return False
    if f['red_4h_streak']<2: return False
    return True  # move_min/vol_min dropped
# drop score too (pure trend+streak)
def relax_nogate(f,i,bars):
    if f['ret_1h']>0: return False
    if f['trend_4h']>-1 or f['trend_4h_slope']>-1: return False
    if f['red_4h_streak']<2: return False
    return True
# lower the impulse bar instead of removing (move>=0.5, vol>=0.5)
def relax_half(f,i,bars):
    if f['ret_1h']>0: return False
    if cscore(f)<3.0: return False
    if f['move_per_atr']<0.5 or f['vol_z_168']<0.5: return False
    if f['trend_4h']>-1 or f['trend_4h_slope']>-1: return False
    if f['red_4h_streak']<2: return False
    return True
for key,p in [('btc','scratch/feats_btc_3y.pkl'),('eth','scratch/feats_eth_3y.pkl')]:
    bars,feats=load(p);yr=years(bars);mid=(bars[0].hour_ms+bars[-1].hour_ms)//2
    print(f'--- {key} 3y ---')
    rep('relax_keepscore(dropMove/Vol) t2.5 ttl72 cd4', run(bars,feats,relax_keepscore,2.5,72,4),yr,mid)
    rep('relax_nogate(trend+streak only) t2.5 ttl72 cd24', run(bars,feats,relax_nogate,2.5,72,24),yr,mid)
    rep('relax_half(move/vol>=0.5) t2.5 ttl72 cd4', run(bars,feats,relax_half,2.5,72,4),yr,mid)
