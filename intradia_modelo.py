"""Pasos 2 y 3: un solo modelo tipo LLM sobre un corpus de velas de 5 min de varios activos,
preentrenado a predecir la siguiente vela-token y luego afinado a tareas concretas.

Etapas (python3 intradia_modelo.py <etapa>):
  prep      tokeniza las velas y calcula etiquetas -> prep.npz
  bench     mide velocidad de entrenamiento
  pretrain  preentrenamiento autosupervisado (siguiente token)         -> pre.pt
  finetune  afina: desde cero / desde preentrenado / sonda lineal       -> ft_*.pt
  eval      evalúa todo en test (activos vistos y activos NUNCA vistos) -> resultados
Variables: INTRA_DIR, PRE_SECS, FT_SECS. Se ignoran costos y competencia.
"""
import os, sys, time, json
import numpy as np, pandas as pd, torch, torch.nn as nn, torch.nn.functional as F

D = os.environ.get("INTRA_DIR", "intradia")
ALL = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LTCUSDT"]
TRAIN_SYMS, HELD = ALL[:6], ALL[6:]          # ADA y LTC no se ven nunca al entrenar
IDX = {s: i for i, s in enumerate(ALL)}
L, H, WARM, VOCAB = 64, 12, 300, 576
TASKS = ["y1 vela sig. sube", "y2 retorno 1h sube", "y3 vol 1h alta"]
torch.set_num_threads(4)
dev = "cpu"


# ---------------- prep ----------------
def prep():
    raw = {s: pd.read_pickle(f"{D}/{s}.pkl") for s in ALL}
    common = raw[ALL[0]]["t"].to_numpy()
    for s in ALL[1:]:
        common = np.intersect1d(common, raw[s]["t"].to_numpy())
    N = len(common)
    i_val = int(np.searchsorted(common, pd.Timestamp("2024-07-01").value // 10**6))
    i_test = int(np.searchsorted(common, pd.Timestamp("2025-01-01").value // 10**6))
    feats = {}
    for s in ALL:
        d = raw[s].set_index("t").loc[common]
        o, h, l, c, v = (d[k].to_numpy(float) for k in ["open", "high", "low", "close", "volume"])
        lr = np.log(c / np.r_[c[0], c[:-1]])
        sig = pd.Series(lr).rolling(288).std().to_numpy()
        vm = pd.Series(v).rolling(288).mean().to_numpy()
        with np.errstate(all="ignore"):
            bn = np.log(c / o) / sig
            un = np.log(h / np.maximum(o, c)) / sig
            ln_ = np.log(np.minimum(o, c) / l) / sig
            vr = v / vm
        feats[s] = dict(o=o, c=c, lr=lr, sig=sig, bn=bn, un=un, ln=ln_, vr=vr)
    # bordes de los bins: cuantiles del entrenamiento de los activos de entrenamiento
    cat = lambda k, f=lambda x: x: np.concatenate([f(feats[s][k][WARM:i_val]) for s in TRAIN_SYMS])
    ab = cat("bn", lambda x: np.abs(x[x != 0]))
    e_b = np.quantile(ab, [.25, .5, .75])
    e_u = np.quantile(cat("un"), [.25, .5, .75])
    e_l = np.quantile(cat("ln"), [.25, .5, .75])
    e_v = np.quantile(cat("vr"), [.25, .5, .75])
    tok = np.zeros((len(ALL), N), np.int16)
    y = np.full((len(ALL), 3, N), np.nan, np.float32)
    ret = np.zeros((len(ALL), 2, N), np.float32)
    pers = np.zeros((len(ALL), N), np.float32)
    for s in ALL:
        f = feats[s]
        mag = np.digitize(np.abs(f["bn"]), e_b)
        bb = np.where(f["bn"] == 0, 4, np.where(f["bn"] > 0, 5 + mag, 3 - mag))
        t = ((bb * 4 + np.digitize(f["un"], e_u)) * 4 + np.digitize(f["ln"], e_l)) * 4 + np.digitize(f["vr"], e_v)
        tok[IDX[s]] = np.nan_to_num(t, nan=0).astype(np.int16)
        o, c, lr, sig = f["o"], f["c"], f["lr"], f["sig"]
        up = np.full(N, np.nan); up[:-1] = (c[1:] > o[1:]).astype(float); up[:-1][c[1:] == o[1:]] = np.nan
        y2 = np.full(N, np.nan); y2[:-H] = (c[H:] > c[:-H]).astype(float)
        rv = pd.Series(lr).rolling(H).std()
        fv = rv.shift(-H).to_numpy()
        y3 = np.where(np.isnan(fv), np.nan, (fv > sig).astype(float))
        y[IDX[s]] = np.stack([up, y2, y3])
        r1 = np.zeros(N); r1[:-1] = c[1:] / o[1:] - 1
        r12 = np.zeros(N); r12[:-H] = c[H:] / c[:-H] - 1
        ret[IDX[s]] = np.stack([r1, r12])
        pers[IDX[s]] = (rv.to_numpy() > sig).astype(float)
    np.savez(f"{D}/prep.npz", tok=tok, y=y, ret=ret, pers=pers, common=common, i_val=i_val, i_test=i_test)
    print(f"N={N} velas por activo  train=[{WARM},{i_val})  val=[{i_val},{i_test})  test=[{i_test},{N})")
    print("vocabulario:", VOCAB, "| tokens distintos usados:", len(np.unique(tok[:6, WARM:i_val])))


class Data:
    def __init__(self):
        z = np.load(f"{D}/prep.npz")
        self.tok, self.y, self.ret, self.pers = z["tok"], z["y"], z["ret"], z["pers"]
        self.i_val, self.i_test, self.N = int(z["i_val"]), int(z["i_test"]), self.tok.shape[1]
        self.seg = {"train": (WARM, self.i_val), "val": (self.i_val, self.i_test), "test": (self.i_test, self.N)}

    def windows(self, rng, syms, seg, n, length, tail=0):
        lo, hi = self.seg[seg]
        si = np.array([IDX[s] for s in syms])[rng.integers(0, len(syms), n)]
        st = rng.integers(lo, hi - length - tail + 1, n)
        return si, st

    def tokens(self, si, st, length):
        return torch.from_numpy(self.tok[si[:, None], st[:, None] + np.arange(length)].astype(np.int64))


# ---------------- modelo ----------------
class GPT(nn.Module):
    def __init__(self, d=64, layers=4, heads=4):
        super().__init__()
        self.emb = nn.Embedding(VOCAB, d)
        self.pos = nn.Parameter(torch.randn(1, L, d) * 0.02)
        lay = nn.TransformerEncoderLayer(d, heads, 4 * d, 0.1, batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(lay, layers, enable_nested_tensor=False)
        self.ln = nn.LayerNorm(d)
        self.lm = nn.Linear(d, VOCAB)
        self.cls = nn.Linear(d, 3)
        self.register_buffer("mask", nn.Transformer.generate_square_subsequent_mask(L))

    def hidden(self, x):
        n = x.shape[1]
        return self.ln(self.enc(self.emb(x) + self.pos[:, :n], mask=self.mask[:n, :n], is_causal=True))

    def forward(self, x):
        h = self.hidden(x)
        return self.lm(h), self.cls(h[:, -1])

    def backbone_state(self):
        return {k: v for k, v in self.state_dict().items() if not k.startswith(("lm.", "cls."))}


def lr_at(step, total, base, warm=200):
    if step < warm:
        return base * (step + 1) / warm
    p = (step - warm) / max(1, total - warm)
    return base * (0.1 + 0.9 * 0.5 * (1 + np.cos(np.pi * p)))


def set_lr(opt, v):
    for g in opt.param_groups:
        g["lr"] = v


# ---------------- entrenamiento ----------------
def pretrain(secs, bs=256):
    data, rng = Data(), np.random.default_rng(0)
    torch.manual_seed(0)
    m = GPT()
    opt = torch.optim.AdamW(m.parameters(), lr=1e-3, weight_decay=0.01)
    print("parámetros:", sum(p.numel() for p in m.parameters()))
    t0, step, hist = time.time(), 0, []
    vsi, vst = data.windows(np.random.default_rng(1), TRAIN_SYMS, "val", 4000, L + 1)
    vx = data.tokens(vsi, vst, L + 1)
    # estimar pasos totales con el ritmo de los primeros pasos
    total = None
    while True:
        el = time.time() - t0
        if step == 20:
            total = int(secs / (el / 20))
            print(f"ritmo {el / 20:.3f}s/paso -> {total} pasos en {secs}s ({total * bs * L / 1e6:.0f}M tokens)", flush=True)
        if total is not None and step >= total:
            break
        set_lr(opt, lr_at(step, total or 10**9, 1e-3))
        si, st = data.windows(rng, TRAIN_SYMS, "train", bs, L + 1)
        w = data.tokens(si, st, L + 1)
        m.train()
        logits, _ = m(w[:, :-1])
        loss = F.cross_entropy(logits.reshape(-1, VOCAB), w[:, 1:].reshape(-1))
        opt.zero_grad(); loss.backward()
        nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step(); step += 1
        if step % 250 == 0:
            m.eval()
            with torch.no_grad():
                lg, _ = m(vx[:, :-1])
                vl = F.cross_entropy(lg[:, 16:].reshape(-1, VOCAB), vx[:, 17:].reshape(-1)).item()
            print(f"paso {step:6d}  train {loss.item():.4f}  val {vl:.4f}  ({time.time() - t0:.0f}s)", flush=True)
    torch.save(m.state_dict(), f"{D}/pre.pt")


def masked_bce(logit, y):
    ok = ~torch.isnan(y)
    return F.binary_cross_entropy_with_logits(logit[ok], y[ok]) if ok.any() else logit.sum() * 0


def batch_xy(data, si, st):
    t = st + L - 1
    return data.tokens(si, st, L), torch.from_numpy(data.y[si, :, t])


def finetune(name, init, secs, lr, frozen=False, bs=256):
    data, rng = Data(), np.random.default_rng(2)
    torch.manual_seed(2)
    m = GPT()
    if init:
        m.load_state_dict(torch.load(f"{D}/pre.pt"), strict=True)
    params = list(m.cls.parameters()) if frozen else list(m.parameters())
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    vsi, vst = data.windows(np.random.default_rng(3), TRAIN_SYMS, "val", 30000, L, H)
    vx, vy = batch_xy(data, vsi, vst)

    def val():
        m.eval()
        with torch.no_grad():
            return float(np.mean([masked_bce(m(vx[i:i + 5000])[1], vy[i:i + 5000]).item() for i in range(0, len(vx), 5000)]))
    t0, step, total, best, best_sd = time.time(), 0, None, 9, None
    while True:
        el = time.time() - t0
        if step == 20:
            total = int(secs / (el / 20))
            print(f"[{name}] {total} pasos", flush=True)
        if total is not None and step >= total:
            break
        set_lr(opt, lr_at(step, total or 10**9, lr))
        si, st = data.windows(rng, TRAIN_SYMS, "train", bs, L, H)
        x, y = batch_xy(data, si, st)
        m.train()
        if frozen:
            m.eval()
        loss = masked_bce(m(x)[1], y)
        opt.zero_grad(); loss.backward()
        nn.utils.clip_grad_norm_(params, 1.0)
        opt.step(); step += 1
        if step % 250 == 0:
            v = val()
            if v < best:
                best, best_sd = v, {k: t.clone() for k, t in m.state_dict().items()}
            print(f"[{name}] paso {step:5d}  train {loss.item():.4f}  val {v:.4f}  mejor {best:.4f}", flush=True)
    v = val()
    if v < best:
        best, best_sd = v, {k: t.clone() for k, t in m.state_dict().items()}
    torch.save(best_sd, f"{D}/ft_{name}.pt")
    print(f"[{name}] listo, mejor val {best:.4f}")


# ---------------- evaluación ----------------
def stats(p, y, r, label, pers=None):
    ok = ~np.isnan(y)
    p, y = p[ok], y[ok]
    r = r[ok] if r is not None else None
    n = len(y)
    acc = ((p > .5) == (y > .5)).mean()
    maj = max(y.mean(), 1 - y.mean())
    row = dict(n=int(n), acc=acc, base=maj, ci=1.96 * np.sqrt(.25 / n))
    if pers is not None:
        row["pers"] = (pers[ok] == y).mean()
    if r is not None:
        s = np.where(p > .5, 1.0, -1.0) * r
        row["bps"], row["t"] = s.mean() * 1e4, s.mean() / (s.std() / np.sqrt(n) + 1e-12)
        top = np.abs(p - .5) >= np.quantile(np.abs(p - .5), .9)
        row["acc_top10"], row["bps_top10"] = ((p[top] > .5) == (y[top] > .5)).mean(), s[top].mean() * 1e4
    return row


@torch.no_grad()
def eval_all(n_per_sym=40000):
    data = Data()
    models = {}
    for k in ["scratch", "pre_ft", "probe"]:
        if os.path.exists(f"{D}/ft_{k}.pt"):
            mm = GPT(); mm.load_state_dict(torch.load(f"{D}/ft_{k}.pt")); mm.eval(); models[k] = mm
    lm = GPT(); lm.load_state_dict(torch.load(f"{D}/pre.pt")); lm.eval()
    # estadísticas de bigramas/unigramas del entrenamiento (referencia para el preentrenamiento)
    tr = data.tok[:6, WARM:data.i_val].astype(np.int64)
    uni = np.bincount(tr.ravel(), minlength=VOCAB) + 1.0; uni /= uni.sum()
    bi = np.ones((VOCAB, VOCAB)) * 0.1
    np.add.at(bi, (tr[:, :-1].ravel(), tr[:, 1:].ravel()), 1); bi /= bi.sum(1, keepdims=True)
    bodybin = np.arange(VOCAB) // 64
    out = {}
    for gname, syms in [("activos vistos (test 2025-26)", TRAIN_SYMS), ("activos NUNCA vistos (ADA, LTC)", HELD)]:
        rng = np.random.default_rng(7)
        si, st = data.windows(rng, syms, "test", n_per_sym * len(syms), L, H)
        x, ytrue = batch_xy(data, si, st)
        t = st + L - 1
        r1, r12, pers = data.ret[si, 0, t], data.ret[si, 1, t], data.pers[si, t]
        y = ytrue.numpy()
        res = {}
        # --- preentrenado: entropía cruzada y dirección extraída de su distribución
        nll_lm, nll_u, nll_b, pup = [], [], [], []
        for i in range(0, len(x), 4000):
            xb = x[i:i + 4000]
            lg = lm.hidden(xb[:, :-1]); lg = lm.lm(lg[:, -1])        # predice token L-1 desde L-1 previos
            tgt = xb[:, -1]
            lp = F.log_softmax(lg, -1)
            nll_lm.append(-lp.gather(1, tgt[:, None]).squeeze(1).numpy())
            nll_u.append(-np.log(uni[tgt.numpy()]))
            nll_b.append(-np.log(bi[xb[:, -2].numpy(), tgt.numpy()]))
        # dirección de la SIGUIENTE vela desde el LM (contexto completo de L tokens)
        for i in range(0, len(x), 4000):
            pr = F.softmax(lm.lm(lm.hidden(x[i:i + 4000])[:, -1]), -1).numpy()
            up, dn = pr[:, bodybin >= 5].sum(1), pr[:, bodybin <= 3].sum(1)
            pup.append(up / (up + dn))
        pup = np.concatenate(pup)
        res["LM"] = dict(ce=np.concatenate(nll_lm).mean(), ce_uni=np.concatenate(nll_u).mean(), ce_bi=np.concatenate(nll_b).mean())
        res["LM->dir"] = stats(pup, y[:, 0], r1, "lm")
        res["continuar"] = stats(np.where(bodybin[x[:, -1].numpy()] >= 5, 1.0, 0.0), y[:, 0], r1, "cont")
        for k, mm in models.items():
            P = np.concatenate([torch.sigmoid(mm(x[i:i + 4000])[1]).numpy() for i in range(0, len(x), 4000)])
            res[k] = [stats(P[:, 0], y[:, 0], r1, k), stats(P[:, 1], y[:, 1], r12, k), stats(P[:, 2], y[:, 2], None, k, pers)]
        out[gname] = res
    return out


def show(out):
    for g, res in out.items():
        print(f"\n===== {g} =====")
        lm = res["LM"]
        print(f"Preentrenamiento (siguiente token), nats/token:  modelo {lm['ce']:.4f} | bigrama {lm['ce_bi']:.4f} | unigrama {lm['ce_uni']:.4f}")
        r = res["LM->dir"]
        print(f"Dirección sacada del LM:  acierto {r['acc'] * 100:.2f}% ±{r['ci'] * 100:.2f} (base {r['base'] * 100:.2f}%)  bruto {r['bps']:+.2f} bps/op (t={r['t']:+.1f})  n={r['n']}")
        r = res["continuar"]
        print(f"Regla 'misma dirección que la última vela': acierto {r['acc'] * 100:.2f}%  bruto {r['bps']:+.2f} bps/op")
        for k in ["scratch", "pre_ft", "probe"]:
            if k not in res:
                continue
            print(f"-- {k}")
            for name, r in zip(TASKS, res[k]):
                extra = f" persist {r['pers'] * 100:.2f}%" if "pers" in r else ""
                tail = f"  bruto {r['bps']:+.2f} bps/op (t={r['t']:+.1f}) | top10%: acc {r['acc_top10'] * 100:.2f}% {r['bps_top10']:+.2f} bps" if "bps" in r else ""
                print(f"   {name:20s} acierto {r['acc'] * 100:.2f}% ±{r['ci'] * 100:.2f} (mayoría {r['base'] * 100:.2f}%{extra}){tail}")


if __name__ == "__main__":
    st = sys.argv[1]
    if st == "prep":
        prep()
    elif st == "bench":
        data, m = Data(), GPT()
        opt = torch.optim.AdamW(m.parameters())
        rng = np.random.default_rng(0)
        t0 = time.time()
        for _ in range(10):
            si, st_ = data.windows(rng, TRAIN_SYMS, "train", 256, L + 1)
            w = data.tokens(si, st_, L + 1)
            loss = F.cross_entropy(m(w[:, :-1])[0].reshape(-1, VOCAB), w[:, 1:].reshape(-1))
            opt.zero_grad(); loss.backward(); opt.step()
        dt = (time.time() - t0) / 10
        print(f"{dt:.3f} s/paso, {256 * L / dt / 1e3:.0f}k tokens/s")
    elif st == "pretrain":
        pretrain(float(os.environ.get("PRE_SECS", 1200)))
    elif st == "finetune":
        s = float(os.environ.get("FT_SECS", 480))
        finetune("scratch", False, s, 1e-3)
        finetune("pre_ft", True, s, 3e-4)
        finetune("probe", True, s / 2, 1e-3, frozen=True)
    elif st == "eval":
        out = eval_all()
        json.dump(out, open(f"{D}/eval.json", "w"), default=float)
        show(out)
