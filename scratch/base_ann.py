import sys,types; sys.modules['duckdb']=types.ModuleType('duckdb')
import pickle,statistics
from hl_swing_bot.backtest import HourlyBar,_resolve_outcome,BTSignal
from hl_swing_bot.features import MIN_BARS
FEE=0.19;SLIP2=0.10;COST=FEE+SLIP2;HOUR_MS=3600*1000
def load(p):
    d=pickle.load(open(p,'rb'));return [HourlyBar(*t) for t in d['bars']],d['feats']
def years(b):return (b[-1].hour_ms-b[0].hour_ms)/1000/3600/24/365.25
def cscore(f):return 0.30*abs(f['move_per_atr_z'])+0.25*abs(f['robust_z_168'])+0.20*f['vol_z_168']+0.15*abs(f['ret_4h'])/max(f['atr_pct'],1e-9)+0.10
def base(f,i,bars):
    if f['ret_1h']>0:return False
    if cscore(f)<3.0 or f['move_per_atr']<1.0 or f['vol_z_168']<1.0:return False
    if f['trend_4h']>-1 or f['trend_4h_slope']>-1 or f['red_4h_streak']<2:return False
    return True
def run(bars,feats):
    out=[];li=-10**9
    for i in range(MIN_BARS,len(bars)):
        f=feats[i]
        if f is None or i-li<4:continue
        if not base(f,i,bars):continue
        atr=f['atr_1h'];e=f['close']
        sig=BTSignal(idx=i,bar_close_ms=bars[i].hour_ms+HOUR_MS,direction='SHORT',entry=e,stop=e+1.5*atr,target=e-2.5*atr,score=0.0,expires_idx=i+72)
        _resolve_outcome(bars,sig,ttl_bars=72,be_trigger=0.0)
        out.append(sig.realized_pct-COST);li=i
    return out
def ann(nets,yr):
    losers=[x for x in nets if x<0];sl=abs(statistics.median(losers)) if losers else 1.5
    if sl<0.1:sl=0.1
    eq=1.0
    for x in nets:eq*=(1+0.005*(x/sl)); eq=max(eq,1e-9)
    return ((eq**(1/yr))-1)*100
for key,p in [('btc3y','scratch/feats_btc_3y.pkl'),('eth3y','scratch/feats_eth_3y.pkl')]:
    bars,feats=load(p);yr=years(bars);r=run(bars,feats)
    print(f'{key}: BASELINE n={len(r)} net/tr={sum(r)/len(r):.3f} ann@0.5%={ann(r,yr):.2f}%')
