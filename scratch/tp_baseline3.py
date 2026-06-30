"""3y baseline replicated from CACHED features (no run_backtest -> no segfault).

Mirrors run_backtest(short_only=True) gate logic exactly:
 score>=3.0, move/ATR>=1.0, vol_z>=1.0, trend_4h<=-1, slope<=-1, red_streak>=2,
 cooldown same-dir 240min(=4 bars), opp-dir 60min(=1 bar),
 stop=+1.5ATR, target=-2.5ATR, ttl=72, exit via _resolve_outcome.
"""
import sys, types, json, statistics
sys.modules['duckdb'] = types.ModuleType('duckdb')
sys.path.insert(0, 'scratch'); sys.path.insert(0, 'src')
import warnings; warnings.filterwarnings('ignore')
from trend_participation import load_bars, FEE
from hl_swing_bot.backtest import BTSignal, _resolve_outcome
from hl_swing_bot.signal import STOP_ATR_MULT, TARGET_ATR_MULT
from hl_swing_bot.features import MIN_BARS

def composite_score(f):
    return (0.30*abs(f['move_per_atr_z']) + 0.25*abs(f['robust_z_168'])
            + 0.20*f['vol_z_168'] + 0.15*abs(f['ret_4h'])/max(f['atr_pct'],1e-9) + 0.10*1.0)

name, path = sys.argv[1], sys.argv[2]
bars, _ = load_bars(path)
feats = json.load(open(f'scratch/tp_feat_{name}.json'))['feats']
y = (bars[-1].hour_ms - bars[MIN_BARS].hour_ms)/(365.25*24*3600*1000)

sigs = []
last_dir=None; last_idx=-10000
COOL_SAME=4; COOL_OPP=1  # bars
for i in range(MIN_BARS, len(bars)):
    f = feats[i]
    if f is None: continue
    direction = 'LONG' if f['ret_1h']>0 else 'SHORT'
    if direction=='LONG': continue  # short_only
    elapsed=i-last_idx
    if last_dir is not None:
        if last_dir==direction and elapsed<COOL_SAME: continue
        if last_dir!=direction and elapsed<COOL_OPP: continue
    score=composite_score(f)
    if not (score>=3.0 and f['move_per_atr']>=1.0 and f['vol_z_168']>=1.0
            and f['trend_4h']<=-1 and f['trend_4h_slope']<=-1 and f['red_4h_streak']>=2):
        continue
    atr=f['atr_1h']; entry=f['close']
    stop=entry+STOP_ATR_MULT*atr; target=entry-TARGET_ATR_MULT*atr
    sig=BTSignal(idx=i,bar_close_ms=bars[i].hour_ms+3600000,direction='SHORT',
                 entry=entry,stop=stop,target=target,score=score,expires_idx=i+72)
    _resolve_outcome(bars,sig,ttl_bars=72)
    sigs.append({'idx':i,'exit_idx':sig.exit_idx,'realized_pct':sig.realized_pct,'status':sig.status})
    last_dir=direction; last_idx=i

nets=[s['realized_pct']-FEE for s in sigs if s['realized_pct'] is not None]
mid=MIN_BARS+(len(bars)-MIN_BARS)//2
h1=[s['realized_pct']-FEE for s in sigs if s['idx']<mid and s['realized_pct'] is not None]
h2=[s['realized_pct']-FEE for s in sigs if s['idx']>=mid and s['realized_pct'] is not None]
dt_idx=[i for i in range(len(feats)) if feats[i] and feats[i]['trend_4h']<=-1 and feats[i]['trend_4h_slope']<=-1]
covered=set()
for s in sigs:
    if s['exit_idx'] is not None: covered.update(range(s['idx'],s['exit_idx']+1))
dt_cov=sum(1 for i in dt_idx if i in covered)
slow=sum(1 for s in sigs if feats[s['idx']] and feats[s['idx']]['move_per_atr']<1.0 and feats[s['idx']]['vol_z_168']<1.0)
out={'name':name,'years':round(y,2),'n':len(nets),
     'net_per_trade':round(statistics.mean(nets),4) if nets else 0,
     'net_total':round(sum(nets),2),'trades_per_yr':round(len(nets)/y,1) if y else 0,
     'winrate':round(sum(1 for x in nets if x>0)/len(nets),3) if nets else 0,
     'h1_net_per_trade':round(statistics.mean(h1),4) if h1 else None,'h1_n':len(h1),
     'h2_net_per_trade':round(statistics.mean(h2),4) if h2 else None,'h2_n':len(h2),
     'dt_regime_hours':len(dt_idx),'dt_coverage_pct':round(dt_cov/len(dt_idx)*100,1) if dt_idx else 0,
     'slow_bleed_entries':slow}
json.dump(out,open(f'scratch/tp_base3_{name}.json','w'),indent=2)
print(json.dumps(out),flush=True)
