"""Aritmética de viabilidad de un proceso repetitivo de alta frecuencia para >=0.7%/día.
Todo analítico o Monte Carlo; sin datos de mercado."""
import numpy as np

TARGET = 0.007
print("1) Edge NETO necesario por fill (bp del nocional) para 0.7%/día = 0.007 / (apalancamiento x fills por día)")
fills = (20, 100, 500, 2000)
levs = (1, 3, 5, 10)
print("   fills/día →   " + "".join(f"{f:>9d}" for f in fills))
for L in levs:
    print(f"   apal. x{L:<2d}      " + "".join(f"{TARGET / (L * f) * 1e4:9.2f}" for f in fills))

print("\n2) Edge BRUTO necesario = neto + comisión por lado (bp). Referencias: taker 5.0, maker 2.0, maker VIP 0.0")
for lab, fee in (("taker 5.0bp", 5.0), ("maker 2.0bp", 2.0), ("maker 0bp", 0.0)):
    print(f"   {lab}: " + " | ".join(
        f"x{L}/{f} fills: {TARGET / (L * f) * 1e4 + fee:5.2f}" for L, f in ((5, 100), (5, 500), (10, 500))))

print("\n3) Volumen operado por día con capital $10.000 (cada fill con nocional = apalancamiento x capital, igual que en 1)")
for L, f in ((5, 100), (5, 500), (10, 500)):
    vol = 1e4 * L * f
    print(f"   x{L}, {f} fills: ${vol:,.0f}/día de volumen -> comisiones maker 2bp = ${vol * 2e-4:,.0f}/día "
          f"({vol * 2e-4 / 1e4:.0%} del capital) | taker 5bp = {vol * 5e-4 / 1e4:.0%} del capital por día")

print("\n4) Monte Carlo (1 año): edge neto por fill mu, riesgo por fill sigma=10bp del nocional, 100 fills/día, apalancamiento x5;")
print("   'ruina' = caída del capital >= 50% desde el pico en algún momento del año")
rng = np.random.default_rng(0)


def sim(mu_bp, sig_bp=10.0, fills=100, L=5, n=4000):
    mu, sig = mu_bp * 1e-4, sig_bp * 1e-4
    eq = np.ones(n)
    peak = np.ones(n)
    dead = np.zeros(n, bool)
    worst = np.zeros(n)
    for _ in range(365):
        r = L * fills * mu + L * sig * np.sqrt(fills) * rng.standard_normal(n)
        eq = np.where(dead, eq, eq * (1 + np.maximum(r, -1.0)))
        peak = np.maximum(peak, eq)
        dd = 1 - eq / peak
        worst = np.maximum(worst, dd)
        dead |= dd >= 0.5
    return eq, dead, worst


print("   mu neto/fill | retorno medio/día | mediana final | % años con caída >=50% | peor DD mediano")
for mu in (1.0, 0.7, 0.3, 0.0, -0.3, -1.0):
    eq, dead, worst = sim(mu)
    print(f"   {mu:+5.1f} bp    |  {5 * 100 * mu * 1e-4:+8.2%}/día   | {np.median(eq):10.2f}x   |"
          f"        {dead.mean():6.0%}          | {np.median(worst):6.0%}")

print("\n5) Escala del margen de error: 0.7bp de BTC a $80.000 =", f"${80000 * 0.7e-4:.2f} por BTC.")
print("   Un error de 0.5bp en el costo real (slippage, selección adversa, cola) anula el edge necesario.")
