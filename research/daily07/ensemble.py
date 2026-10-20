"""Segunda familia: ensamble de señales de tendencia + volatility targeting + stops por ATR, y cota teórica de Sharpe."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sweep import bars, signal, FEE, SLIP, FUND8H, IS, OOS

def run(df, pos_frac, bh, period, cap_lev):
    c = df.close.values; ret = np.r_[0, c[1:]/c[:-1]-1]
    p = pos_frac.shift(1).fillna(0).clip(-cap_lev, cap_lev).values        # fracción de equity expuesta (con signo)
    prev = np.r_[0, p[:-1]]
    r = p*ret - np.abs(p-prev)*(FEE+SLIP) - p*FUND8H*(bh/8)
    adv = np.where(p>0, df.low.values/np.r_[c[0],c[:-1]]-1, np.where(p<0, -(df.high.values/np.r_[c[0],c[:-1]]-1), 0))
    r = np.where(np.abs(p)*adv <= -0.9, -1.0, r)
    r = pd.Series(r, index=df.index)
    a,b = period
    r = r[(r.index>=pd.Timestamp(a,tz="UTC")) & ((r.index<pd.Timestamp(b,tz="UTC")) if b else True)]
    eq=(1+r).cumprod(); days=max((r.index[-1]-r.index[0]).days,1); f=float(eq.iloc[-1])
    daily = f**(1/days)-1 if f>0 else -1
    d = r.resample("1D").apply(lambda x:(1+x).prod()-1)
    sharpe = d.mean()/d.std()*np.sqrt(365) if d.std()>0 else 0
    return dict(daily=daily, dd=float((eq/eq.cummax()-1).min()), final=f, sharpe=float(sharpe))

res=[]
for tf,bh in (("4h",4),("1d",24)):
    df=bars(tf)
    members=[signal(df,"ema",a,b,True) for a,b in ((10,30),(20,50),(20,100),(50,200))]+\
            [signal(df,"donch",n,0,True) for n in (20,40,55,100)]+[signal(df,"tsmom",n,0,True) for n in (10,20,40,90)]
    ens=sum(members)/len(members)                       # voto promedio en [-1,1]
    bars_per_day=24/bh
    vol=df.close.pct_change().rolling(int(30*bars_per_day)).std()*np.sqrt(365*bars_per_day)
    for target in (0.2,0.4,0.8,1.5):
        pf=(ens*target/vol).fillna(0)
        for cap in (1,3,5,10):
            i=run(df,pf,bh,IS,cap); o=run(df,pf,bh,OOS,cap)
            res.append(dict(tf=tf,vol_target=target,cap_lev=cap,is_daily=i["daily"],is_dd=i["dd"],is_sharpe=i["sharpe"],
                            oos_daily=o["daily"],oos_dd=o["dd"],oos_sharpe=o["sharpe"],oos_final=o["final"]))
r=pd.DataFrame(res); r.to_csv(Path(__file__).parent/"ensemble_results.csv",index=False)
pd.set_option('display.width',200)
print("ensambles probados:",len(r)," >=0.7% IS:",(r.is_daily>=0.007).sum()," >=0.7% OOS:",(r.oos_daily>=0.007).sum())
t=r.sort_values('oos_daily',ascending=False).head(6).copy()
for c in ['is_daily','is_dd','oos_daily','oos_dd']: t[c]=(t[c]*100).round(2)
print(t.round(2).to_string(index=False))
print("\nMejor IS y su OOS:")
t=r.sort_values('is_daily',ascending=False).head(4).copy()
for c in ['is_daily','is_dd','oos_daily','oos_dd']: t[c]=(t[c]*100).round(2)
print(t.round(2).to_string(index=False))

# Cota teórica: Sharpe anual necesario para 0.7% diario geométrico con una vol anual dada (lognormal)
print("\nSharpe necesario para 0.7% diario (geométrico) según volatilidad anual de la cuenta:")
g=np.log(1.007)*365
for vol in (0.1,0.2,0.4,0.8,1.5):
    mu=g+0.5*vol**2
    print(f"  vol anual {vol:.0%}: retorno aritmético {mu:.0%}/año -> Sharpe {mu/vol:.1f}")
