"""Fast O(n) replica of the shipped SHORT baseline gate, validated against
run_backtest on a slice. Mirrors _compute_features_at + run_backtest exactly:
 - move_per_atr = |ret_1h| / atr_pct
 - vol_z_168 = robust_z(volume, last 168 vols before current)
 - robust_z_168 = robust_z(close, last 168 closes before current)
 - move_per_atr_z = robust_z over last 168 move/atr values
 - ret_4h, atr_pct
 - trend_4h: 4h close vs sma50 of 4h (last 51 buckets excl current)
 - slope: sma50 vs sma50 10 buckets earlier
 - red_4h_streak
 - composite score, gates, cooldown (same dir 240min=4 bars, opp 60min=1 bar)
Then ATR stop=entry+1.5atr, target=entry-2.5atr, ttl=72.
"""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, r'C:\User\projects\hl-swing-bot\scratch')
import statistics
from _lens_common import load_bars, NET_COST, HOUR_MS
from hl_swing_bot.backtest import run_backtest  # for validation

SD = r'C:\User\projects\hl-swing-bot\scratch'
MIN_BARS = 60
HIST = 168

def robust_z(value, hist):
    h = [x for x in hist if x is not None]
    if len(h) < 10:
        return 0.0
    med = statistics.median(h)
    mad = statistics.median(abs(x - med) for x in h) or 0.0
    if mad == 0:
        return 0.0
    return (value - med) / (1.4826 * mad)

def wilder_atr(bars, period=14):
    n = len(bars); out=[None]*n
    if n < period+1: return out
    trs=[0.0]*n
    for i in range(1,n):
        h,l,pc=bars[i].high,bars[i].low,bars[i-1].close
        trs[i]=max(h-l,abs(h-pc),abs(l-pc))
    atr=sum(trs[1:period+1])/period; out[period]=atr
    for i in range(period+1,n):
        atr=(atr*(period-1)+trs[i])/period; out[i]=atr
    return out

def build_4h(bars):
    """Return for each 1h idx: trend_4h(-1/0/1), slope(-1/0/1), red_streak.
    Buckets by UTC wall-clock (hour_ms % 4h), aligned 00/04/08/12/16/20,
    mirroring aggregate_to_4h exactly. Builds bucket OHLC incrementally; for
    each 1h index i the LAST bucket is the partial in-progress one (its close
    is the current 1h close), matching how _compute_features_at slices."""
    n=len(bars)
    trend=[0]*n; slope=[0]*n; red=[0]*n
    BUCKET=4*HOUR_MS
    # incremental bucket list of (open, close, is_red) for completed buckets;
    # the current partial bucket is tracked separately.
    bopen=[]; bclose=[]  # completed buckets
    cur_start=None; cur_open=None; cur_close=None
    for i in range(n):
        b=bars[i]
        start=b.hour_ms-(b.hour_ms%BUCKET)
        if cur_start is None:
            cur_start=start; cur_open=b.open; cur_close=b.close
        elif start!=cur_start:
            # close out previous bucket
            bopen.append(cur_open); bclose.append(cur_close)
            cur_start=start; cur_open=b.open; cur_close=b.close
        else:
            cur_close=b.close
        # build the view = completed buckets + current partial as last bucket
        co = bclose + [cur_close]
        op = bopen + [cur_open]
        m=len(co)
        if m>=51:
            sma50=statistics.mean(co[-51:-1])
            trend[i]= 1 if co[-1]>sma50 else (-1 if co[-1]<sma50 else 0)
        if m>=61:
            sma50=statistics.mean(co[-51:-1])
            sma50p=statistics.mean(co[-61:-11])
            slope[i]= -1 if sma50<sma50p else (1 if sma50>sma50p else 0)
        rs=0
        for j in range(m-1,-1,-1):
            if co[j]<op[j]: rs+=1
            else: break
        red[i]=rs
    return trend,slope,red

def run_baseline_fast(bars, score_min=3.0, move_min=1.0, vol_min=1.0,
                      slope_gate=True, red_streak_min=2,
                      stop_mult=1.5, tgt_mult=2.5, ttl=72):
    n=len(bars)
    closes=[b.close for b in bars]; vols=[b.volume for b in bars]
    atrs=wilder_atr(bars)
    trend,slope,red=build_4h(bars)
    sigs=[]
    last_dir=None; last_idx=-10000
    for i in range(MIN_BARS,n):
        atr=atrs[i]
        if not atr or atr<=0 or closes[i]<=0: continue
        atr_pct=atr/closes[i]*100
        if atr_pct<=0: continue
        ret_1h=(closes[i]/closes[i-1]-1)*100 if closes[i-1]>0 else 0
        if i>=4 and closes[i-4]>0:
            ret_4h=(closes[i]/closes[i-4]-1)*100
        else: ret_4h=0
        direction='LONG' if ret_1h>0 else 'SHORT'
        if direction=='LONG': continue  # short_only
        elapsed=(i-last_idx)*60
        if last_dir is not None:
            if last_dir==direction and elapsed<240: continue
            if last_dir!=direction and elapsed<60: continue
        move_per_atr=abs(ret_1h)/atr_pct
        # hist windows: closes[i-168:i], vols[i-168:i]
        hist_c=closes[max(0,i-HIST):i]; hist_v=vols[max(0,i-HIST):i]
        if len(hist_c)<30: continue
        rz=robust_z(closes[i],hist_c)
        vz=robust_z(vols[i],hist_v)
        # move/atr z over hist
        hist_m=[]
        for j in range(max(1,i-HIST), i):
            if atrs[j] and atrs[j]>0 and closes[j]>0 and closes[j-1]>0:
                m_atr=atrs[j]/closes[j]*100
                if m_atr>0:
                    hist_m.append(abs((closes[j]/closes[j-1]-1)*100)/m_atr)
        mz=robust_z(move_per_atr,hist_m) if hist_m else 0.0
        score=0.30*abs(mz)+0.25*abs(rz)+0.20*vz+0.15*abs(ret_4h)/max(atr_pct,1e-9)+0.10
        passes = (score>=score_min and move_per_atr>=move_min and vz>=vol_min
                  and trend[i]<=-1
                  and ((not slope_gate) or slope[i]<=-1)
                  and (red_streak_min<=0 or red[i]>=red_streak_min))
        if not passes: continue
        entry=closes[i]; stop=entry+stop_mult*atr; target=entry-tgt_mult*atr
        # resolve
        end=min(i+ttl,n-1); status='EXP'; px=closes[end]; exit_idx=end
        for k in range(i+1,end+1):
            if bars[k].high>=stop:
                px=stop; status='SL'; exit_idx=k; break
            if bars[k].low<=target:
                px=target; status='TP'; exit_idx=k; break
        gross=(entry/px-1)*100
        sigs.append({'idx':i,'gross':gross,'net':gross-NET_COST,'status':status,
                     'risk_pct':stop_mult*atr/entry*100,'exit_idx':exit_idx})
        last_dir=direction; last_idx=i
    return sigs

if __name__=='__main__':
    btc,_=load_bars(SD+r'\binance_btc_3y.csv')
    if len(sys.argv)>1 and sys.argv[1]=='validate':
        sub=btc[:3000]
        fast=run_baseline_fast(sub)
        ref=run_backtest(sub, short_only=True)
        rsig=ref['signals']
        print('FAST n=%d  REF n=%d'%(len(fast),len(rsig)))
        fi=[s['idx'] for s in fast]; ri=[s['idx'] for s in rsig]
        print('fast idxs',fi)
        print('ref  idxs',ri)
        print('match idxs:', fi==ri)
        # compare realized
        for a,b in zip(fast,rsig):
            print(a['idx'],'fast_gross=%.3f'%a['gross'],'ref=%.3f'%b['realized_pct'],a['status'],b['status'])
