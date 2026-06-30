"""HL 208d live-instrument check: same entries (baseline) + same exit variants
on hist_btc.csv / hist_eth.csv. Reports baseline + all variants net/trade & n."""
import sys, types
sys.modules['duckdb'] = types.ModuleType('duckdb')
import csv, statistics, json
from hl_swing_bot.backtest import HourlyBar, run_backtest
from hl_swing_bot.features import wilder_atr
import importlib.util
spec = importlib.util.spec_from_file_location("lens_run", r"C:\User\projects\hl-swing-bot\scratch\lens_run.py")
# we only want the engine fns; re-import by exec to avoid running __main__
mod_src = open(r"C:\User\projects\hl-swing-bot\scratch\lens_run.py").read()
mod_src = mod_src.split('if __name__')[0]
ns = {}
exec(compile(mod_src, "lens_run_fns", "exec"), ns)
load_bars=ns['load_bars']; build_flips=ns['build_flips']; make_trades=ns['make_trades']
summ=ns['summ']; ann_return=ns['ann_return']; years_span=ns['years_span']
ex_fixed=ns['ex_fixed']; ex_ttl=ns['ex_ttl']; ex_chandelier=ns['ex_chandelier']
ex_flip=ns['ex_flip']; ex_scaleout=ns['ex_scaleout']

SCRATCH=r"C:\User\projects\hl-swing-bot\scratch"

if __name__=="__main__":
    out={}
    for asset,fn in [("BTC","hist_btc.csv"),("ETH","hist_eth.csv")]:
        bars=load_bars(f"{SCRATCH}\\{fn}")
        atr_arr=wilder_atr(bars); flips=build_flips(bars)
        res=run_backtest(bars, short_only=True)
        sigs=res["signals"]; yr=years_span(bars)
        a={"asset":asset,"n_bars":len(bars),"years":round(yr,3),"n_base":res["n_signals"]}
        base=make_trades(bars,sigs,atr_arr,flips,ex_fixed,ttl=72,tmult=2.5)
        a["baseline"]=summ(base); a["baseline"]["ann"]=round(ann_return(base,bars),2)
        v={}
        for ttl in (168,336,720):
            tr=make_trades(bars,sigs,atr_arr,flips,ex_ttl,ttl=ttl)
            v[f"ttl{ttl}"]=summ(tr)
        for ttl in (168,336):
            for k in (2.0,3.0,4.0):
                tr=make_trades(bars,sigs,atr_arr,flips,ex_chandelier,ttl=ttl,k=k)
                v[f"chand_ttl{ttl}_k{k}"]=summ(tr)
        for ttl in (336,720):
            for mode in ("sma","slope"):
                tr=make_trades(bars,sigs,atr_arr,flips,ex_flip,ttl=ttl,mode=mode)
                v[f"flip_{mode}_ttl{ttl}"]=summ(tr)
        for fmult in (1.5,2.5):
            for rk in (3.0,4.0):
                tr=make_trades(bars,sigs,atr_arr,flips,ex_scaleout,ttl=336,fmult=fmult,rk=rk)
                v[f"scaleout_f{fmult}_rk{rk}"]=summ(tr)
        a["variants"]=v
        out[asset]=a
    with open(f"{SCRATCH}\\lens_hl_out.json","w") as f:
        json.dump(out,f,indent=1,default=float)
    print("DONE_HL"); print(json.dumps(out,indent=1,default=float))
