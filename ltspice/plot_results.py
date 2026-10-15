"""Runs the ngspice versions of both circuits and saves result plots to ltspice/results/."""
import os, subprocess, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results"); os.makedirs(OUT, exist_ok=True)
BLUE, ORANGE, GRID, INK = "#2a78d6", "#eb6834", "#e6e5e1", "#52514e"
plt.rcParams.update({"font.size": 11, "axes.edgecolor": "#b9b8b2", "axes.labelcolor": INK,
                     "xtick.color": INK, "ytick.color": INK, "axes.grid": True, "grid.color": GRID,
                     "axes.spines.top": False, "axes.spines.right": False})

def run(cir, dat, wr_singlescale=False):
    subprocess.run(["ngspice", "-b", os.path.join(HERE, cir)], capture_output=True, check=True)
    return np.loadtxt(os.path.join(HERE, dat))

# ---- 24 h solar charging ----
d = run("_solar_charging_24h_ngspice.cir", "_day.dat")
t, irr, vpv, vbat, ichg, ild = d[:, 0], d[:, 1], d[:, 2], d[:, 3], d[:, 4], d[:, 5]
fig, ax = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
ax[0].plot(t, irr * 1000, color=BLUE, lw=2); ax[0].set_ylabel("Irradiance (W/m²)")
ax[0].set_title("Solar irradiance over the day", loc="left", fontsize=12)
def avg5(x):   # 5-minute moving average (5 min = 0.0833 s of sim time) for readability
    tt = np.arange(0, 24, 1/3600*30); xi = np.interp(tt, t, x); k = 10
    return tt, np.convolve(xi, np.ones(k)/k, mode="same")
ax[1].plot(*avg5(vbat), color=BLUE, lw=2); ax[1].axhline(4.2, color="#8a8984", ls=":", lw=1)
ax[1].text(0.2, 4.21, "4.2 V full-charge limit (CV)", color=INK, fontsize=9, va="bottom")
ax[1].set_ylabel("Battery voltage (V)"); ax[1].set_title("18650 battery voltage (5-min average)", loc="left", fontsize=12)
ta, ia = avg5(ichg * 1000); ax[2].plot(ta, ia, color=BLUE, lw=2)
ax[2].set_ylabel("Charge current (mA)"); ax[2].set_title("TP4056 charge current into battery (5-min average)", loc="left", fontsize=12)
ax[2].set_xlabel("Time of day (hours)  —  simulated with 1 s = 1 h"); ax[2].set_xticks(range(0, 25, 3))
fig.tight_layout(); fig.savefig(os.path.join(OUT, "solar_charging_24h.png"), dpi=130)

# ---- boost converter at three battery voltages ----
base = open(os.path.join(HERE, "_boost_converter_5v_ngspice.cir")).read()
fig, ax = plt.subplots(2, 1, figsize=(10, 7))
summary = []
for vin, col, ls in [(4.2, BLUE, "-"), (3.7, ORANGE, "--"), (3.3, "#1baf7a", ":")]:
    cir = base.replace(".param Vin=3.7", f".param Vin={vin}").replace("_boost.dat", f"_boost_{vin}.dat")
    p = os.path.join(HERE, f"_boost_{vin}.cir"); open(p, "w").write(cir)
    subprocess.run(["ngspice", "-b", p], capture_output=True, check=True)
    b = np.loadtxt(os.path.join(HERE, f"_boost_{vin}.dat"))
    tb, vo = b[:, 0] * 1e3, b[:, 1]
    ax[0].plot(tb, vo, color=col, lw=1.6, ls=ls, label=f"Battery {vin} V")
    m = (tb > 3) & (tb < 3.5); m2 = (tb > 5.5) & (tb < 6)
    summary.append((vin, vo[m].mean(), vo[m].max() - vo[m].min(), vo[m2].mean()))
    if vin == 3.7:
        z = (tb > 3.0) & (tb < 3.02)
        ax[1].plot(tb[z] * 1e3 - 3000, vo[z], color=BLUE, lw=1.6)
ax[0].axvline(3.5, color="#8a8984", ls=":", lw=1); ax[0].text(3.55, 3.7, "load step +250 mA", fontsize=9, color=INK)
ax[0].set_ylabel("Output voltage (V)"); ax[0].set_xlabel("Time (ms)"); ax[0].legend(frameon=False, loc="lower right")
ax[0].set_title("Boost converter output: soft-start, regulation and load step", loc="left", fontsize=12)
ax[0].set_ylim(3, 5.6)
ax[1].set_title("Zoom: output ripple at 3.7 V battery (500 kHz switching)", loc="left", fontsize=12)
ax[1].set_xlabel("Time (µs)"); ax[1].set_ylabel("Output voltage (V)")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "boost_converter_5v.png"), dpi=130)
for s in summary:
    print(f"Vin={s[0]} V: Vout={s[1]:.3f} V ripple={s[2]*1000:.0f} mVpp after-step={s[3]:.3f} V")
