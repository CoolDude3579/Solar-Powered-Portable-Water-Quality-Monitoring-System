"""
Generates the LTspice schematics (.asc) AND equivalent plain SPICE netlists (.cir)
from ONE circuit description, so the exact circuit opened in LTspice is also
verified with ngspice (python3 ltspice/generate.py --check).

Visible parts (panel diode, resistors, inductor, Schottky, capacitors, sources) are
drawn as real LTspice symbols; behavioural parts (photocurrent, TP4056 charge law,
PWM controller, switch) are SPICE lines in the schematic's directive text.
Only functions common to LTspice and ngspice are used: min, max, tanh.
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Pin offsets of LTspice built-in symbols at rotation R0
PINS = {"res": [(16, 16), (16, 96)], "cap": [(16, 0), (16, 64)], "ind": [(16, 16), (16, 96)],
        "diode": [(16, 0), (16, 64)], "schottky": [(16, 0), (16, 64)],
        "voltage": [(0, 16), (0, 96)], "current": [(0, 0), (0, 80)]}
PREFIX = {"res": "R", "cap": "C", "ind": "L", "diode": "D", "schottky": "D", "voltage": "V", "current": "I"}


def write(name, title, parts, cards, directives, notes, analysis, ngspice_control):
    # ---------- .asc ----------
    asc = ["Version 4", "SHEET 1 1880 1000"]
    seen = {}
    for sym, inst, value, nodes, x, y in parts:
        for (px, py), node in zip(PINS[sym], nodes):
            xy = (x + px, y + py)
            assert seen.get(xy, node) == node, f"pin clash at {xy}: {seen[xy]} vs {node}"
            seen[xy] = node
            asc.append(f"FLAG {xy[0]} {xy[1]} {node}")
    for sym, inst, value, nodes, x, y in parts:
        asc += [f"SYMBOL {sym} {x} {y} R0", f"SYMATTR InstName {inst}", f"SYMATTR Value {value}"]
    ty = 40
    asc.append(f"TEXT 32 {ty - 32} Left 3 ;{title}")
    for line in notes:
        asc.append(f"TEXT 32 {ty} Left 2 ;{line}"); ty += 28
    ty = 560
    for line in cards + directives + [analysis]:
        kind = ";" if line.startswith("*") else "!"          # '*' lines become plain comments
        asc.append(f"TEXT 32 {ty} Left 2 {kind}{line.lstrip('* ') if kind == ';' else line}"); ty += 28
    open(os.path.join(HERE, name + ".asc"), "w", encoding="latin-1").write("\n".join(asc) + "\n")

    # ---------- .cir (same circuit) ----------
    net = [f"* {title}"]
    for sym, inst, value, nodes, x, y in parts:
        full = inst if inst.startswith(PREFIX[sym]) else PREFIX[sym] + inst
        net.append(f"{full} {nodes[0]} {nodes[1]} {value}")
    net += cards + directives + [analysis]
    open(os.path.join(HERE, name + ".cir"), "w").write("\n".join(net) + "\n.end\n")
    open(os.path.join(HERE, "_" + name + "_ngspice.cir"), "w").write(
        "\n".join(net) + "\n.options method=gear\n.control\n" + ngspice_control + "\n.endc\n.end\n")


# =====================================================================
# 1) 24-hour solar charging of the battery (time-scaled: 1 s = 1 hour)
# =====================================================================
day_parts = [
    # sym, name, value, (pin1 node, pin2 node), x, y
    ("diode",   "Dpv",   "DPV",    ("pv", "0"),     176, 176),
    ("res",     "Rsh",   "150",    ("pv", "0"),     272, 160),
    ("res",     "Rs",    "0.4",    ("pv", "pvo"),   368, 160),
    ("cap",     "Cin",   "100u",    ("pvo", "0"),    464, 176),
    ("res",     "Rbat",  "0.08",   ("bat", "cell"), 800, 160),
    ("cap",     "Cbat",  "{Cbat}", ("cell", "0"),   896, 176),
    ("voltage", "Virr",  "PWL(0 0 6 0 7 0.10 8 0.30 9 0.55 10 0.78 11 0.93 12 1.0 13 0.93 14 0.78 15 0.55 16 0.30 17 0.10 18 0 24 0)",
                                   ("irr", "0"),    1056, 160),
    ("voltage", "Vload", "PULSE({Psleep} {Pactive} 0 0.1m 0.1m {Ton} {Tper})",
                                   ("pload", "0"),  1232, 160),
]
day_cards = [
    "* Solar panel 6 V / 2 W: photocurrent proportional to irradiance (1.0 = 1000 W/m2)",
    "Bph 0 pv I=0.40*V(irr)",
    ".model DPV D(Is=1n N=14)",
    "* TP4056 linear Li-ion charger: CC 1 A max, CV 4.2 V, needs ~4 V input, no reverse current",
    "Bchg pvo ichg I=min(1.0, max(0,(V(pvo)-V(bat)-0.15)/0.5)) * min(1,max(0,(V(pvo)-3.9)/0.2)) * min(1,max(0,(4.2-V(bat))/0.05))",
    "Vichg ichg bat 0",
    "* System load drawn from battery through boost converter (efficiency 85%)",
    "Vild bat iload 0",
    "Bload iload 0 I=V(pload)/(0.85*max(V(bat),2.5))",
]
day_dirs = [
    "* 2000 mAh 18650 cell: Q = 7200 C over 3.0-4.2 V -> 6000 F; divided by 3600 because 1 sim-second = 1 hour",
    ".param Cbat=6000/3600",
    "* Load: 30 s measurement + WiFi upload every 5 min at 1.0 W, deep sleep 10 mW otherwise",
    ".param Pactive=1.0 Psleep=0.01 Ton={30/3600} Tper={300/3600}",
    ".ic V(cell)=3.55 V(bat)=3.55",
    "* Power into / out of the battery (W) for the energy integrals",
    "Bpin pin 0 V=V(bat)*I(Vichg)",
    "Bpout pout 0 V=V(bat)*I(Vild)",
    ".meas TRAN Wh_harvested INTEG V(pin)",
    ".meas TRAN Wh_consumed INTEG V(pout)",
    ".meas TRAN Vbat_start FIND V(bat) AT=0.01",
    ".meas TRAN Vbat_end FIND V(bat) AT=24",
    ".meas TRAN Vbat_max MAX V(bat)",
]
day_notes = [
    "Time axis: 1 second of simulation = 1 hour of a day (t = 0 is midnight, t = 12 is noon).",
    "Plot V(bat), V(pvo), I(Vichg) (charge current), I(Vild) (load current). Energy integrals in Wh appear in View > SPICE Error Log.",
    "Battery capacitance is scaled by 1/3600 so currents stay real while hours become seconds.",
]
write("solar_charging_24h", "Solar PV -> TP4056 charger -> 18650 battery -> load  (24 h, 1 s = 1 h)",
      day_parts, day_cards, day_dirs, day_notes, ".tran 1m 24 0 2m uic",
      "set wr_singlescale\nrun\nwrdata " + os.path.join(HERE, "_day.dat") +
      " V(irr) V(pvo) V(bat) I(Vichg) I(Vild)")

# =====================================================================
# 2) Closed-loop boost converter 3.7 V battery -> 5 V for ESP32 + LCD
# =====================================================================
boost_parts = [
    ("voltage",  "Vbat",  "{Vin}",   ("bat", "0"),   96, 160),
    ("res",      "Rdcr",  "0.05",    ("bat", "lx"),  208, 144),
    ("ind",      "L1",    "10u",     ("lx", "sw"),   304, 144),
    ("schottky", "D1",    "SS14",    ("sw", "out"),  416, 160),
    ("res",      "Resr",  "0.15",     ("out", "cx"),  512, 144),
    ("cap",      "Cout",  "220u",     ("cx", "0"),    608, 256),
    ("res",      "Rload", "{Rl}",    ("out", "0"),   704, 160),
    ("voltage",  "Vramp", "PULSE(0.03 1 0 1.99u 5n 0 2u)", ("ramp", "0"), 880, 160),
]
boost_cards = [
    "* Output capacitor: 220 uF electrolytic, its 0.15 ohm ESR damps the LC resonance",
    "* Power MOSFET as a switch, driven by the PWM comparator below (500 kHz)",
    "S1 sw 0 duty ramp NSW",
    ".model NSW SW(Ron=0.06 Roff=1Meg Vt=0 Vh=0.01)",
    ".model SS14 D(Is=5u Rs=0.04 N=1.05 Cjo=110p)",
    "* PI controller: integrator node 'integ' + proportional term, duty clamped 0..0.85",
    "* Feedback low-pass filter (removes switching ripple before the controller)",
    "Rf out fb 1k",
    "Cf fb 0 10n",
    "* Soft-start reference: ramps from the battery voltage up to 5.0 V over 1 ms",
    "Vref ref 0 PWL(0 {Vin} 1m 5.0)",
    "* Integral control (~500 Hz crossover) with anti-windup: integrator stops at 0 and 0.85 duty",
    "Bint 0 integ I=0.5u*( max(V(ref)-V(fb),0)*min(1,max(0,(0.85-V(integ))*50)) + min(V(ref)-V(fb),0)*min(1,max(0,V(integ)*50)) )",
    "Cint integ 0 1n",
    "Rleak integ 0 1G",
    "Bduty dutyr 0 V=min(0.85, max(0, V(integ)))",
    "Rd dutyr duty 100",
    "Cd duty 0 100p",
    "* PWM comparator is built into S1: switch closes while V(duty) > V(ramp) (0-1 V sawtooth)",
]
boost_dirs = [
    ".param Vin=3.7 Rl=20",
    ".ic V(integ)=0.1 V(out)=3.4 V(cx)=3.4 V(fb)=3.4",
    "* Load step: extra 250 mA (ESP32 WiFi transmit burst) at 3.5 ms on top of the 250 mA base",
    "Sload out lstep lctl 0 NSW",
    "Rstep lstep 0 20",
    "Vlctl lctl 0 PULSE(-1 1 3.5m 1u 1u 10 20)",
    ".meas TRAN Vout_avg AVG V(out) FROM=3m TO=3.5m",
    ".meas TRAN Vout_ripple PP V(out) FROM=3m TO=3.5m",
    ".meas TRAN Vout_min_on_step MIN V(out) FROM=3.5m TO=4.5m",
    ".meas TRAN Vout_after_step AVG V(out) FROM=5.5m TO=6m",
    ".meas TRAN Iin_avg AVG I(Vbat) FROM=3m TO=3.5m",
]
boost_notes = [
    "Boost converter (MT3608-style, 500 kHz) keeps the ESP32 rail at 5.0 V while the battery falls 4.2 -> 3.3 V.",
    "Plot V(out), V(bat), I(L1). Try .step param Vin list 3.3 3.7 4.2 to see regulation across the battery range.",
]
write("boost_converter_5v", "Li-ion 3.7 V -> 5.0 V boost converter with PI control and load step",
      boost_parts, boost_cards, boost_dirs, boost_notes, ".tran 10n 6m 0 20n uic",
      "run\nwrdata " + os.path.join(HERE, "_boost.dat") + " V(out) I(L1) V(duty)")

if "--check" in sys.argv:
    for n in ("solar_charging_24h", "boost_converter_5v"):
        r = subprocess.run(["ngspice", "-b", os.path.join(HERE, f"_{n}_ngspice.cir")], capture_output=True, text=True)
        print(f"===== {n} =====")
        print("\n".join(l for l in (r.stdout + r.stderr).splitlines()
                        if "=" in l and any(k in l.lower() for k in ("wh_", "vbat_", "vout_", "iin_"))
                        or "error" in l.lower()))
