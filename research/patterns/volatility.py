import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tradebot.data import load_csv
ROOT = Path(__file__).resolve().parents[2]
IS_END = pd.Timestamp("2025-01-01", tz="UTC")
h = load_csv(ROOT/"data/BTCUSD_bitstamp_1h.csv.gz"); m15 = load_csv(ROOT/"data/BTCUSD_bitstamp_15m.csv.gz")
r = np.log(h.close).diff().dropna(); ab = r.abs()
sl = lambda s,a: s[s.index<IS_END] if a=="IS" else s[s.index>=IS_END]
print("1) Clustering de volatilidad (autocorrelación de |ret| 1h):")
for per in ("IS","OOS"):
    x = sl(ab,per); print(f"   {per}: lag1={x.autocorr(1):.2f} lag24={x.autocorr(24):.2f} lag168={x.autocorr(168):.2f}  (direccional: ret lag1={sl(r,per).autocorr(1):+.3f}, lag24={sl(r,per).autocorr(24):+.3f})")
print("\n2) Estacionalidad intradía de la volatilidad (|ret| medio por hora UTC, relativo a la media; IS vs OOS)")
prof = {p: sl(ab,p).groupby(sl(ab,p).index.hour).mean()/sl(ab,p).mean() for p in ("IS","OOS")}
d = pd.DataFrame(prof); d["vol_mediana_horaria"] = (d.IS + d.OOS)/2
print(f"   correlación del perfil horario IS vs OOS: {d.IS.corr(d.OOS):.2f}")
print("   horas más activas :", list(d.sort_values('vol_mediana_horaria',ascending=False).head(4).index), "-> ", d.sort_values('vol_mediana_horaria',ascending=False).head(4).vol_mediana_horaria.round(2).tolist(), "x la media")
print("   horas más tranquilas:", list(d.sort_values('vol_mediana_horaria').head(4).index), "-> ", d.sort_values('vol_mediana_horaria').head(4).vol_mediana_horaria.round(2).tolist(), "x la media")
v = h.volume; vp = {p: sl(v,p).groupby(sl(v,p).index.hour).mean()/sl(v,p).mean() for p in ("IS","OOS")}
print(f"   correlación del perfil horario de VOLUMEN IS vs OOS: {pd.Series(vp['IS']).corr(pd.Series(vp['OOS'])):.2f}")
dow = {p: sl(ab,p).groupby(sl(ab,p).index.dayofweek).mean()/sl(ab,p).mean() for p in ("IS","OOS")}
print("   |ret| por día de semana (0=lun) IS:", dow['IS'].round(2).tolist(), "OOS:", dow['OOS'].round(2).tolist())
print("\n3) ¿Se puede predecir la volatilidad? R² de |ret| de las próximas 24h vs vol de las últimas 24h/168h (OOS):")
fut = ab.rolling(24).sum().shift(-24); p24 = ab.rolling(24).sum(); p168 = ab.rolling(168).sum()/7
X = pd.concat([fut,p24,p168],axis=1,keys=["f","a","b"]).dropna()
for per in ("IS","OOS"):
    x = sl(X["f"],per); print(f"   {per}: corr(vol futura, vol 24h)={x.corr(sl(X['a'],per)):.2f}  corr(vol futura, vol 7d)={x.corr(sl(X['b'],per)):.2f}")
print("\n4) Vol-targeting sobre largo BTC (1x tope 1x, vol objetivo 40% anual, costos 0.07%/lado sobre cambio de posición), Sharpe y DD")
ret = h.close.pct_change()
vol = ret.rolling(24*30).std()*np.sqrt(24*365)
for tgt in (0.4,):
    w = (tgt/vol).clip(upper=1).shift(1).fillna(0)
    cost = w.diff().abs().fillna(0)*0.0007
    sc = w*ret - cost
    for per in ("IS","OOS"):
        for lab,s in (("BTC 1x",ret),(f"vol-target {tgt:.0%}",sc)):
            x = sl(s.dropna(),per); dly = x.resample("1D").apply(lambda q:(1+q).prod()-1); eq=(1+x).cumprod()
            print(f"   {per} {lab:16s} Sharpe={dly.mean()/dly.std()*np.sqrt(365):5.2f}  retorno={eq.iloc[-1]-1:+7.1%}  maxDD={(eq/eq.cummax()-1).min():6.1%}")

print("\n5) Escaneo direccional fino en 15m: hora-minuto UTC (96 buckets) -> retorno de las próximas 4 velas (1h). FDR sobre las 192 hipótesis")
c15 = m15.close; f4 = c15.shift(-4)/c15-1
bucket = pd.Series(m15.index.hour*4 + m15.index.minute//15, index=m15.index)
rows=[]
for b in range(96):
    for sd in (1,-1):
        x = (sd*f4)[bucket==b].dropna(); xi,xo = sl(x,"IS"),sl(x,"OOS")
        ti = xi.mean()/(xi.std()/np.sqrt(len(xi))); to = xo.mean()/(xo.std()/np.sqrt(len(xo)))
        rows.append((b,sd,xi.mean()*1e4,ti,xo.mean()*1e4,to))
t = pd.DataFrame(rows,columns=["bucket","side","m_is","t_is","m_oos","t_oos"])
p = 2*(1-stats.norm.cdf(t.t_is.abs())); order=np.argsort(p); ranked=p[order]*len(p)/(np.arange(len(p))+1)
ok=np.zeros(len(p),bool); k=np.where(ranked<=0.10)[0]
if len(k): ok[order[:k.max()+1]]=True
t["fdr"]=ok; t["surv"]=ok&(np.sign(t.m_is)==np.sign(t.m_oos))&(t.t_oos.abs()>=1.65)
print(f"   |t_IS|>=2: {(t.t_is.abs()>=2).sum()} de {len(t)}  pasan FDR: {t.fdr.sum()}  sobreviven OOS: {t.surv.sum()}  (esperables por azar con |t|>=2: ~{0.0455*len(t):.0f})")
