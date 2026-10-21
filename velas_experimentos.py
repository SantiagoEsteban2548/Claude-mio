"""Cuadrícula de experimentos: ¿más ventana, más features, más neuronas, más salidas
o un modelo tipo LLM (tokens + embeddings + atención) mejoran la predicción con velas?

Todo con validación walk-forward (con embargo para que las etiquetas a 5 días no se
solapen con el entrenamiento). Se ignoran costos y competencia. Uso:
    python3 velas_experimentos.py            # completo
    QUICK=1 python3 velas_experimentos.py    # prueba rápida
Variables: CACHE_DIR (caché de datos), WORKERS (procesos en paralelo).
"""
import os
import json
import time
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from multiprocessing import get_context

QUICK = bool(os.environ.get("QUICK"))
CACHE = os.environ.get("CACHE_DIR", "datos_cache")
TICKERS = ["SPY"] if QUICK else ["SPY", "QQQ", "AAPL", "BTC-USD"]
TRAIN, TEST, GAP, START = 1500, 250, 5, 260
SEEDS = 1 if QUICK else 2
TARGETS = ["y1_vela_sig_sube", "y2_retorno_5d_sube", "y3_vol_5d_alta"]

# ---------- datos ----------
def load(ticker):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{ticker}.csv")
    if not os.path.exists(path):
        import yfinance as yf
        df = yf.download(ticker, start="2010-01-01", progress=False, auto_adjust=True)
        df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
        df[["open", "high", "low", "close", "volume"]].dropna().to_csv(path, index=False)
    return pd.read_csv(path)


BASIC = ["body", "up_wick", "lo_wick", "range", "vol_rel", "gap"]
RICH = BASIC + ["ret", "dist_ma20", "dist_ma50", "rsi", "atr", "vol20", "ret5", "ret20"]


def features(df):
    o, h, l, c, v = (df[k].to_numpy(float) for k in ["open", "high", "low", "close", "volume"])
    S = pd.Series
    pc = np.r_[c[0], c[:-1]]
    ret = c / pc - 1
    delta = np.diff(c, prepend=c[0])
    up = S(np.clip(delta, 0, None)).rolling(14).mean()
    dn = S(np.clip(-delta, 0, None)).rolling(14).mean()
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    F = {
        "body": (c - o) / o, "up_wick": (h - np.maximum(o, c)) / o,
        "lo_wick": (np.minimum(o, c) - l) / o, "range": (h - l) / o,
        "vol_rel": v / S(v).rolling(20).mean().to_numpy(), "gap": (o - pc) / pc,
        "ret": ret, "dist_ma20": c / S(c).rolling(20).mean().to_numpy() - 1,
        "dist_ma50": c / S(c).rolling(50).mean().to_numpy() - 1,
        "rsi": (up / (up + dn + 1e-12) - 0.5).to_numpy(),
        "atr": (S(tr).rolling(14).mean() / c).to_numpy(), "vol20": S(ret).rolling(20).std().to_numpy(),
        "ret5": S(c).pct_change(5).to_numpy(), "ret20": S(c).pct_change(20).to_numpy(),
    }
    M = np.column_stack([F[k] for k in RICH])
    M = np.nan_to_num(M, nan=0.0, posinf=0.0, neginf=0.0)

    T = len(c)
    y1 = np.full(T, np.nan); y1[:-1] = c[1:] > o[1:]
    y2 = np.full(T, np.nan); y2[:-5] = c[5:] > c[:-5]
    pv = S(ret).rolling(5).std()
    thr = pv.rolling(250).median()
    fut = pv.shift(-5)
    y3 = np.array((fut > thr).astype(float)); y3[np.isnan(fut.to_numpy())] = np.nan
    persist = (pv > thr).astype(float).to_numpy()
    idx = np.arange(START, T - 5)
    Y = np.column_stack([y1, y2, y3])[idx]
    return M, Y, persist[idx], idx


# ---------- modelos ----------
class MLP(nn.Module):
    def __init__(self, nin, h, layers, nout, drop=0.2):
        super().__init__()
        mods, d = [], nin
        for _ in range(layers):
            mods += [nn.Linear(d, h), nn.ReLU(), nn.Dropout(drop)]
            d = h
        self.net = nn.Sequential(*mods, nn.Linear(d, nout))

    def forward(self, x):
        return self.net(x.flatten(1))


class Tfm(nn.Module):
    """Como un LLM pequeño: cada vela es un 'token' -> embedding -> atención -> cabezas de salida."""
    def __init__(self, mode, nf, vocab, w, nout, d=32):
        super().__init__()
        self.emb = nn.Embedding(vocab, d) if mode == "tok" else nn.Linear(nf, d)
        self.pos = nn.Parameter(torch.randn(1, w, d) * 0.02)
        layer = nn.TransformerEncoderLayer(d, 4, 64, 0.1, batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(layer, 2, enable_nested_tensor=False)
        self.head = nn.Linear(d, nout)

    def forward(self, x):
        return self.head(self.enc(self.emb(x) + self.pos)[:, -1])


def tokenize(Xraw_tr, Xraw_te):
    """Discretiza cada vela en una 'palabra' usando cuantiles del entrenamiento."""
    ix = [RICH.index(k) for k in ["body", "up_wick", "lo_wick", "vol_rel"]]
    nb = [7, 3, 3, 3]
    flat = Xraw_tr.reshape(-1, Xraw_tr.shape[-1])
    edges = [np.quantile(flat[:, i], np.linspace(0, 1, n + 1)[1:-1]) for i, n in zip(ix, nb)]

    def tok(X):
        t = 0
        for i, e, n in zip(ix, edges, nb):
            t = t * n + np.digitize(X[..., i], e)
        return t
    return tok(Xraw_tr), tok(Xraw_te), int(np.prod(nb))


def fit_predict(make, Xtr, Ytr, Xte, epochs, seed):
    torch.manual_seed(seed)
    m = make()
    opt = torch.optim.AdamW(m.parameters(), lr=1e-3, weight_decay=1e-2)
    lossf = nn.BCEWithLogitsLoss()
    N = len(Xtr)
    for _ in range(epochs):
        m.train()
        perm = torch.randperm(N)
        for i in range(0, N, 128):
            b = perm[i:i + 128]
            opt.zero_grad()
            lossf(m(Xtr[b]), Ytr[b]).backward()
            opt.step()
    m.eval()
    with torch.no_grad():
        return torch.sigmoid(m(Xte)).numpy()


CONFIGS = {
    "A_base: w5, 6 feats, 16 neuronas":        dict(kind="mlp", w=5,  feats=BASIC, h=16,  layers=1, multi=False),
    "B1_mas_historia: w20":                    dict(kind="mlp", w=20, feats=BASIC, h=16,  layers=1, multi=False),
    "B2_mas_historia: w60":                    dict(kind="mlp", w=60, feats=BASIC, h=16,  layers=1, multi=False),
    "C_mas_features: w20, 14 feats":           dict(kind="mlp", w=20, feats=RICH,  h=16,  layers=1, multi=False),
    "D_mas_neuronas: 2x256, w20, 14 feats":    dict(kind="mlp", w=20, feats=RICH,  h=256, layers=2, multi=False),
    "E0_control 1 salida: h64, w20, 14 feats": dict(kind="mlp", w=20, feats=RICH,  h=64,  layers=1, multi=False),
    "E1_mas_salidas (3 a la vez): h64":        dict(kind="mlp", w=20, feats=RICH,  h=64,  layers=1, multi=True),
    "F_todo junto MLP: w60, 14f, 2x256, 3sal": dict(kind="mlp", w=60, feats=RICH,  h=256, layers=2, multi=True),
    "G1_estilo LLM: tokens+atencion, w30":     dict(kind="tok", w=30, feats=RICH,  multi=True),
    "G2_atencion sobre features, w30":         dict(kind="cont", w=30, feats=RICH, multi=True),
}


def run_job(args):
    torch.set_num_threads(1)
    ticker, name = args
    cfg = CONFIGS[name]
    df = load(ticker)
    M, Y, persist, idx = features(df)
    w, cols = cfg["w"], [RICH.index(k) for k in cfg["feats"]]
    N = len(idx)
    Xs = np.stack([M[t - w + 1:t + 1] for t in idx])           # (N, w, 14) crudo
    out = {t: dict(ok=0, n=0, base=0, pers=0) for t in TARGETS}
    pnl = 0.0
    epochs = 25 if cfg["kind"] != "mlp" else 30
    for s in range(0, N - TRAIN - GAP - TEST + 1, TEST):
        tr = np.arange(s, s + TRAIN)
        te = np.arange(s + TRAIN + GAP, s + TRAIN + GAP + TEST)
        Ytr, Yte = Y[tr], Y[te]
        if cfg["kind"] == "tok":
            Xtr, Xte, vocab = tokenize(Xs[tr], Xs[te])
            Xtr, Xte = torch.tensor(Xtr), torch.tensor(Xte)
        else:
            A, B = Xs[tr][..., cols], Xs[te][..., cols]
            mu, sd = A.reshape(-1, len(cols)).mean(0), A.reshape(-1, len(cols)).std(0) + 1e-9
            Xtr = torch.tensor(np.clip((A - mu) / sd, -5, 5), dtype=torch.float32)
            Xte = torch.tensor(np.clip((B - mu) / sd, -5, 5), dtype=torch.float32)
        groups = [[0, 1, 2]] if cfg["multi"] else [[0], [1], [2]]
        P = np.zeros((len(te), 3))
        for g in groups:
            Yt = torch.tensor(Ytr[:, g], dtype=torch.float32)
            if cfg["kind"] == "mlp":
                make = lambda: MLP(Xtr.shape[1] * Xtr.shape[2], cfg["h"], cfg["layers"], len(g))
            elif cfg["kind"] == "tok":
                make = lambda: Tfm("tok", 0, vocab, w, len(g))
            else:
                make = lambda: Tfm("cont", len(cols), 0, w, len(g))
            P[:, g] = np.mean([fit_predict(make, Xtr, Yt, Xte, epochs, sd_) for sd_ in range(SEEDS)], axis=0)
        for k, tname in enumerate(TARGETS):
            pred = (P[:, k] > 0.5).astype(float)
            o = out[tname]
            o["ok"] += int((pred == Yte[:, k]).sum()); o["n"] += len(te)
            o["base"] += int(((1.0 if Ytr[:, k].mean() > 0.5 else 0.0) == Yte[:, k]).sum())
            if k == 2:
                o["pers"] += int((persist[te] == Yte[:, 2]).sum())
        # PnL de la señal de dirección a 1 vela (sin costos)
        nxt = (df["close"].to_numpy()[idx[te] + 1] - df["open"].to_numpy()[idx[te] + 1]) / df["open"].to_numpy()[idx[te] + 1]
        pnl += float(np.sum(np.where(P[:, 0] > 0.5, nxt, -nxt)))
    return ticker, name, out, pnl


if __name__ == "__main__":
    t0 = time.time()
    for t in TICKERS:
        load(t)
    jobs = [(t, n) for n in CONFIGS for t in TICKERS]
    if QUICK:
        jobs = [(t, n) for n in list(CONFIGS)[:2] + list(CONFIGS)[-2:] for t in TICKERS]
    with get_context("fork").Pool(int(os.environ.get("WORKERS", 4))) as p:
        res = []
        for r in p.imap_unordered(run_job, jobs):
            res.append(r)
            print(f"  listo {r[0]:8s} {r[1]}  ({time.time() - t0:.0f}s)", flush=True)
    json.dump(res, open(os.path.join(CACHE, "resultados.json"), "w"))

    print("\nDiferencia de acierto vs baseline, en puntos porcentuales (promedio sobre activos).")
    print("Baseline = clase mayoritaria del entrenamiento; para y3 también 'persistencia' (vol actual alta -> futura alta).")
    for tname in TARGETS:
        print(f"\n### {tname}")
        print(f"{'config':45s} {'acierto':>8s} {'vs base':>8s} {'vs pers':>8s} {'activos+':>9s}")
        for name in CONFIGS:
            rows = [(r[2][tname], r[0]) for r in res if r[1] == name]
            if not rows:
                continue
            acc = np.mean([o["ok"] / o["n"] for o, _ in rows])
            d = [(o["ok"] - o["base"]) / o["n"] * 100 for o, _ in rows]
            dp = np.mean([(o["ok"] - o["pers"]) / o["n"] * 100 for o, _ in rows]) if tname.startswith("y3") else float("nan")
            n_tot = sum(o["n"] for o, _ in rows)
            print(f"{name:45s} {acc * 100:7.1f}% {np.mean(d):+7.1f}  {dp:+7.1f}  {sum(x > 0 for x in d)}/{len(d)}")
        print(f"   (ruido típico ≈ ±{1.96 * 50 / np.sqrt(n_tot):.1f} pp; en y2/y3 las etiquetas se solapan, ~el doble)")
    print("\nPnL acumulado sin costos de la señal 'vela siguiente' (suma de retornos, promedio de activos):")
    for name in CONFIGS:
        v = [r[3] for r in res if r[1] == name]
        if v:
            print(f"  {name:45s} {np.mean(v):+.3f}")
    print(f"\nTiempo total: {time.time() - t0:.0f}s")
