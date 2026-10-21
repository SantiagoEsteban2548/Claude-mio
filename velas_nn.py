"""Red neuronal sobre velas japonesas con validación walk-forward (solo NumPy).

Hipótesis: ¿las últimas N velas predicen si la siguiente cierra arriba o abajo?
Se ignoran costos y competencia (ver conversación). Uso:
    python3 velas_nn.py            # controles sintéticos + datos reales si hay red
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(0)


# ---------- datos ----------
def synthetic(n=4000, planted=False):
    """Camino aleatorio OHLC. Con planted=True, tras una vela con mecha inferior
    larga (martillo) la siguiente tiende a subir: una señal real que el modelo debería hallar."""
    close = 100.0
    rows, hammer = [], False
    for _ in range(n):
        drift = 0.010 if (planted and hammer) else 0.0
        o = close
        c = o * (1 + drift + rng.normal(0, 0.01))
        h = max(o, c) * (1 + abs(rng.normal(0, 0.004)))
        low_ext = abs(rng.normal(0, 0.004))
        if rng.random() < 0.15:  # martillo: mecha inferior larga
            low_ext += 0.012
            hammer = True
        else:
            hammer = False
        l = min(o, c) * (1 - low_ext)
        rows.append((o, h, l, c, rng.integers(1e5, 1e6)))
        close = c
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def real(ticker="SPY", start="2005-01-01"):
    import yfinance as yf
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)


# ---------- features: relativas, nunca precios crudos ----------
def make_dataset(df, window=5):
    o, h, l, c, v = (df[k].to_numpy(float) for k in ["open", "high", "low", "close", "volume"])
    body = (c - o) / o
    up_wick = (h - np.maximum(o, c)) / o
    lo_wick = (np.minimum(o, c) - l) / o
    rng_ = (h - l) / o
    vol_rel = v / pd.Series(v).rolling(20).mean().to_numpy()
    gap = np.r_[0, (o[1:] - c[:-1]) / c[:-1]]
    F = np.column_stack([body, up_wick, lo_wick, rng_, vol_rel, gap])
    X, y, ret = [], [], []
    for t in range(20, len(df) - 1):
        X.append(F[t - window + 1: t + 1].ravel())
        nxt = (c[t + 1] - o[t + 1]) / o[t + 1]  # vela siguiente
        y.append(1.0 if nxt > 0 else 0.0)
        ret.append(nxt)
    return np.array(X), np.array(y), np.array(ret)


# ---------- MLP con backprop manual ----------
class MLP:
    def __init__(self, n_in, hidden=16, lr=0.01, l2=1e-3):
        self.W1 = rng.normal(0, np.sqrt(2 / n_in), (n_in, hidden))   # pesos capa 1
        self.b1 = np.zeros(hidden)
        self.W2 = rng.normal(0, np.sqrt(2 / hidden), (hidden, 1))    # pesos capa 2
        self.b2 = np.zeros(1)
        self.lr, self.l2 = lr, l2

    def forward(self, X):
        self.z1 = X @ self.W1 + self.b1
        self.h = np.maximum(0, self.z1)                              # ReLU
        return 1 / (1 + np.exp(-(self.h @ self.W2 + self.b2)))      # sigmoide

    def fit(self, X, y, epochs=60, batch=128):
        y = y.reshape(-1, 1)
        for _ in range(epochs):
            idx = rng.permutation(len(X))
            for i in range(0, len(X), batch):
                b = idx[i:i + batch]
                p = self.forward(X[b])
                d2 = (p - y[b]) / len(b)                  # dLoss/dz2 (entropía cruzada)
                gW2 = self.h.T @ d2 + self.l2 * self.W2
                gb2 = d2.sum(0)
                d1 = (d2 @ self.W2.T) * (self.z1 > 0)     # regla de la cadena
                gW1 = X[b].T @ d1 + self.l2 * self.W1
                gb1 = d1.sum(0)
                self.W2 -= self.lr * gW2; self.b2 -= self.lr * gb2   # w ← w − η·∂L/∂w
                self.W1 -= self.lr * gW1; self.b1 -= self.lr * gb1

    def predict(self, X):
        return self.forward(X).ravel()


# ---------- walk-forward ----------
def walk_forward(X, y, ret, train=1000, test=250):
    accs, base_accs, pnl = [], [], []
    for s in range(0, len(X) - train - test + 1, test):
        Xtr, ytr = X[s:s + train], y[s:s + train]
        Xte, yte, rte = X[s + train:s + train + test], y[s + train:s + train + test], ret[s + train:s + train + test]
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9      # normalizar SOLO con el pasado
        m = MLP(X.shape[1])
        m.fit((Xtr - mu) / sd, ytr)
        p = m.predict((Xte - mu) / sd)
        pred = (p > 0.5).astype(float)
        accs.append((pred == yte).mean())
        base_accs.append(max(ytr.mean(), 1 - ytr.mean()) if False else (yte == (1.0 if ytr.mean() > 0.5 else 0.0)).mean())
        pnl.append(np.sum(np.where(pred == 1, rte, -rte)))   # largo si sube, corto si baja
    return np.array(accs), np.array(base_accs), np.array(pnl)


def report(name, df):
    X, y, ret = make_dataset(df)
    a, b, p = walk_forward(X, y, ret)
    # error estándar del acierto bajo azar puro (p=0.5) con ~test muestras por ventana
    se = 0.5 / np.sqrt(250 * len(a))
    print(f"\n== {name} ==  ({len(df)} velas, {len(a)} ventanas out-of-sample)")
    print(f"  acierto modelo : {a.mean():.3f}   (azar ≈ 0.500 ± {1.96 * se:.3f})")
    print(f"  baseline 'siempre la clase mayoritaria': {b.mean():.3f}")
    print(f"  ventanas donde gana al baseline: {(a > b).sum()}/{len(a)}")
    print(f"  PnL acumulado (sin costos): {p.sum():+.3f}  (suma de retornos por vela)")


if __name__ == "__main__":
    report("CONTROL 1: camino aleatorio (no hay nada que aprender)", synthetic())
    report("CONTROL 2: patrón 'martillo' plantado (sí hay señal)", synthetic(planted=True))
    try:
        report("SPY real, velas diarias", real("SPY"))
    except Exception as e:
        print(f"\n(No pude bajar datos reales: {type(e).__name__}. Pasa un CSV OHLCV a report().)")
