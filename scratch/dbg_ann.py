import sys, types; sys.modules['duckdb']=types.ModuleType('duckdb')
import warnings; warnings.filterwarnings('ignore')
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_common import load_bars, annualized_return_05pct, equity_maxdd, FEE
from hl_swing_bot.backtest import run_backtest
import statistics
bars,_=load_bars('binance_btc_3y.csv')
res=run_backtest(bars, short_only=True)
sigs=res['signals']
risks=[abs(s['entry']-s['stop'])/s['entry']*100 for s in sigs]
Rs=[(s['realized_pct']-FEE)/(abs(s['entry']-s['stop'])/s['entry']*100) for s in sigs]
print('n',len(sigs))
print('risk_pct median', round(statistics.median(risks),3),'min',round(min(risks),3),'max',round(max(risks),3))
print('R median', round(statistics.median(Rs),3),'sum R', round(sum(Rs),2),'mean R',round(statistics.mean(Rs),3))
ann,eq,yrs=annualized_return_05pct(sigs,bars)
print('ann',round(ann,3),'eq',round(eq,4),'yrs',round(yrs,3))
eqf,maxdd,path=equity_maxdd(sigs)
print('maxdd',round(maxdd,2),'eq',round(eqf,4))
