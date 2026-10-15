"""
Solar-Powered Portable Water Quality Monitoring System — Dashboard
B.Tech Multidisciplinary Project, VIT Vellore

Tabs
  1. Live device  — subscribes to the ESP32's MQTT telemetry (Wokwi or real board)
  2. Simulator    — move sliders, see the same IS 10500 verdict the device computes
  3. Rules        — the deterministic decision matrix and the standards behind it

Run locally:  streamlit run dashboard/app.py
"""
import json
import math
import os
import random
import threading
import time
from collections import deque
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import rules

MQTT_HOST = os.environ.get("WQM_MQTT_HOST", "broker.hivemq.com")
MQTT_PORT = 1883
MQTT_TOPIC = "vit-wqm/cooldude3579/device01/telemetry"
HISTORY = 300           # readings kept in memory (~10 min at one reading / 2 s)
OFFLINE_AFTER_S = 10

SERIES = "#2a78d6"      # single-series line colour (one series per chart)
STATUS = {              # reserved status colours, always paired with icon + label
    "SAFE": ("#0ca30c", "✅"),
    "CAUTION": ("#fab219", "⚠️"),
    "UNSAFE": ("#ec835a", "⛔"),
    "CRITICAL": ("#d03b3b", "☠️"),
}

st.set_page_config(page_title="Water Quality Monitor", page_icon="💧", layout="wide")


# ----------------------------------------------------------------------------
# MQTT listener (one shared background client per server process)
# ----------------------------------------------------------------------------
class Telemetry:
    def __init__(self):
        self.rows = deque(maxlen=HISTORY)
        self.lock = threading.Lock()
        self.status = "starting"
        self.last_rx = 0.0
        self.error = ""
        try:
            import paho.mqtt.client as mqtt

            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                      client_id=f"wqm-dash-{random.randint(0, 1 << 24):06x}")
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
            self.client.loop_start()
        except Exception as e:  # broker unreachable, library missing, …
            self.status = "error"
            self.error = str(e)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.status = "connected"
        client.subscribe(MQTT_TOPIC)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.status = "reconnecting"

    def _on_message(self, client, userdata, msg):
        try:
            d = json.loads(msg.payload.decode())
            d["received"] = datetime.now()
            with self.lock:
                self.rows.append(d)
            self.last_rx = time.time()
        except Exception:
            pass

    def frame(self) -> pd.DataFrame:
        with self.lock:
            return pd.DataFrame(list(self.rows))


@st.cache_resource
def telemetry() -> Telemetry:
    return Telemetry()


# ----------------------------------------------------------------------------
# UI helpers
# ----------------------------------------------------------------------------
def verdict_banner(level: str, reasons: list, subtitle: str = ""):
    color, icon = STATUS[level]
    items = "".join(f"<li>{rules.REASON_TEXT.get(r, r)}</li>" for r in reasons) or \
        "<li>All parameters within IS 10500:2012 limits</li>"
    st.markdown(
        f"""
        <div style="border-left:8px solid {color}; background:{color}1f; padding:14px 18px;
                    border-radius:6px; margin:4px 0 12px 0;">
          <div style="font-size:1.6rem; font-weight:700;">{icon} {rules.LEVEL_TEXT[level]}</div>
          <ul style="margin:6px 0 0 0;">{items}</ul>
          <div style="opacity:.7; font-size:.85rem; margin-top:6px;">{subtitle}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def metric_row(ph, turb, temp, absorb):
    c = st.columns(4)
    c[0].metric("pH", f"{ph:.2f}", help="Acceptable 6.5 – 8.5")
    c[1].metric("Turbidity", f"{turb:.2f} NTU", help="Acceptable ≤ 1, permissible ≤ 5")
    c[2].metric("Temperature", "sensor error" if temp < rules.TEMP_FAULT_C else f"{temp:.1f} °C",
                help="Warning above 40 °C")
    c[3].metric("Absorbance", f"{absorb:.3f} AU",
                help=f"≈ {rules.absorbance_to_fe(absorb):.2f} mg/L Fe-equivalent. Alert above "
                     f"{rules.ABS_THRESHOLD:.2f} AU (Fe limit 1.0 mg/L)")


def trend(df, col, title, unit, limits=(), y_range=None):
    """One measure per chart (no dual axes); limits drawn as labelled reference lines."""
    fig = go.Figure(go.Scatter(
        x=df["received"], y=df[col], mode="lines", line=dict(color=SERIES, width=2),
        hovertemplate=f"%{{x|%H:%M:%S}}<br>{title}: %{{y:.2f}} {unit}<extra></extra>"))
    for i, (value, label) in enumerate(limits):
        fig.add_hline(y=value, line=dict(color="#8a8984", width=1, dash="dot"),
                      annotation_text=label,
                      annotation_position="bottom left" if i == 0 and len(limits) > 1 else "top left",
                      annotation_font_size=11)
    fig.update_layout(title=dict(text=f"{title} ({unit})" if unit else title, font_size=14),
                      height=230, margin=dict(l=10, r=10, t=40, b=10), showlegend=False,
                      hovermode="x unified")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,.15)", range=y_range)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def demo_reading(t: float) -> dict:
    """Clearly-labelled demo stream for when no device is online."""
    phase = (t / 20) % 4           # cycles through four scenarios every 80 s
    ph, turb, temp, a = 7.3, 0.6, 26.0, 0.03
    if 1 <= phase < 2:
        turb = 3.2
    elif 2 <= phase < 3:
        ph, turb = 6.1, 7.5
    elif phase >= 3:
        a = 0.34
    jitter = lambda s: random.gauss(0, s)
    ph, turb, temp, a = ph + jitter(.03), max(0, turb + jitter(.08)), temp + jitter(.1), max(0, a + jitter(.004))
    v = rules.evaluate(ph, turb, temp, a)
    bat = 3.85 + 0.15 * math.sin(t / 60)
    return dict(id="DEMO", ph=ph, turbidity=turb, temp=temp, absorbance=a,
                fe_mgl=rules.absorbance_to_fe(a), level=v.level, reasons=v.reasons,
                battery_v=bat, battery_pct=int((bat - 3.0) / 1.2 * 100), solar_v=5.8,
                charging=True, received=datetime.now())


# ----------------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------------
st.title("💧 Solar-Powered Portable Water Quality Monitor")
st.caption("pH · turbidity · temperature · colorimetric heavy-metal detection · "
           "rule-based IS 10500:2012 safety verdict (no AI) · solar + Li-ion powered")

tab_live, tab_sim, tab_rules = st.tabs(["📡 Live device", "🧪 Simulator", "📘 Rules & standards"])

# ---------------- Live ----------------
with tab_live:
    tel = telemetry()
    demo = st.toggle("No device online? Show a demo data stream", value=False,
                     help="Generates labelled DEMO readings locally. Turn off to see the real device.")

    @st.fragment(run_every="2s")
    def live_panel():
        if demo:
            if "demo_rows" not in st.session_state:
                st.session_state.demo_rows = deque(maxlen=HISTORY)
            st.session_state.demo_rows.append(demo_reading(time.time()))
            df = pd.DataFrame(list(st.session_state.demo_rows))
            st.info("Showing **DEMO data** generated by the dashboard — not from a sensor.")
        else:
            df = tel.frame()
            age = time.time() - tel.last_rx if tel.last_rx else None
            online = age is not None and age < OFFLINE_AFTER_S
            st.markdown(
                f"**Broker:** `{MQTT_HOST}` ({tel.status}) &nbsp;·&nbsp; **Topic:** `{MQTT_TOPIC}` "
                f"&nbsp;·&nbsp; **Device:** {'🟢 online' if online else '⚪ offline'}"
                + (f" (last packet {age:.0f}s ago)" if age is not None else ""))
            if tel.status == "error":
                st.error(f"Could not start MQTT client: {tel.error}")
            if df.empty:
                st.warning("Waiting for the device… Start the Wokwi simulation (▶) — readings appear "
                           "here within a few seconds of it connecting to Wi-Fi. "
                           "Or switch on the demo stream above.")
                return

        last = df.iloc[-1]
        verdict_banner(last["level"], list(last.get("reasons", [])),
                       f"Verdict computed on the device · {last['received']:%H:%M:%S}")
        metric_row(last["ph"], last["turbidity"], last["temp"], last["absorbance"])

        p = st.columns(3)
        p[0].metric("Battery", f"{last['battery_v']:.2f} V · {int(last['battery_pct'])}%")
        p[1].metric("Solar panel", f"{last['solar_v']:.1f} V")
        p[2].metric("Charging", "Yes ☀️" if last["charging"] else "No")

        g = st.columns(2)
        with g[0]:
            trend(df, "ph", "pH", "", [(6.5, "6.5 min"), (8.5, "8.5 max")], y_range=[0, 14])
            trend(df, "temp", "Temperature", "°C", [(40, "40 °C warning")])
        with g[1]:
            trend(df, "turbidity", "Turbidity", "NTU", [(1, "1 acceptable"), (5, "5 permissible")])
            trend(df, "absorbance", "Absorbance", "AU", [(rules.ABS_THRESHOLD, "heavy-metal alert")])

        with st.expander("Table view / download"):
            show = df[["received", "ph", "turbidity", "temp", "absorbance", "fe_mgl", "level",
                       "battery_v", "solar_v", "charging"]].iloc[::-1]
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.download_button("Download CSV", show.to_csv(index=False), "wqm_readings.csv", "text/csv")

    live_panel()

# ---------------- Simulator ----------------
with tab_sim:
    st.write("Move the sliders or pick a scenario. The verdict uses **exactly the same rules** as the "
             "ESP32 firmware (checked by the same test cases).")
    presets = {
        "Clean tap water": (7.2, 0.5, 26.0, 0.02),
        "River water after rain": (7.4, 12.0, 24.0, 0.05),
        "Acid mine drainage": (5.2, 3.0, 27.0, 0.12),
        "Industrial effluent (metals)": (7.8, 0.8, 31.0, 0.45),
        "Hot water from tank": (7.0, 0.6, 46.0, 0.02),
    }
    for k, v in zip(("s_ph", "s_turb", "s_temp", "s_abs"), presets["Clean tap water"]):
        st.session_state.setdefault(k, v)

    def apply_preset(vals):
        st.session_state.s_ph, st.session_state.s_turb, st.session_state.s_temp, st.session_state.s_abs = vals

    cols = st.columns(len(presets))
    for c, (name, vals) in zip(cols, presets.items()):
        c.button(name, use_container_width=True, on_click=apply_preset, args=(vals,))

    left, right = st.columns([1, 1.3])
    with left:
        ph = st.slider("pH", 0.0, 14.0, step=0.05, key="s_ph")
        turb = st.slider("Turbidity (NTU)", 0.0, 50.0, step=0.1, key="s_turb")
        temp = st.slider("Water temperature (°C)", 0.0, 60.0, step=0.5, key="s_temp")
        absorb = st.slider("Absorbance from colorimeter (AU)", 0.0, 1.0, step=0.005, key="s_abs")
        st.caption(f"Absorbance A = log₁₀(I_blank / I_sample). "
                   f"{absorb:.3f} AU ≈ **{rules.absorbance_to_fe(absorb):.2f} mg/L** Fe-equivalent.")
    with right:
        v = rules.evaluate(ph, turb, temp, absorb)
        verdict_banner(v.level, v.reasons, "Same decision matrix as the on-board firmware")
        checks = pd.DataFrame([
            ("pH", f"{ph:.2f}", "6.5 – 8.5", "✅ pass" if rules.PH_MIN <= ph <= rules.PH_MAX else "⛔ fail"),
            ("Turbidity", f"{turb:.1f} NTU", "≤ 1 (≤ 5 permissible)",
             "✅ pass" if turb <= 1 else ("⚠️ caution" if turb <= 5 else "⛔ fail")),
            ("Temperature", f"{temp:.1f} °C", "≤ 40 °C", "✅ pass" if temp <= 40 else "⚠️ caution"),
            ("Heavy metal (colour)", f"{absorb:.3f} AU", f"≤ {rules.ABS_THRESHOLD:.2f} AU",
             "✅ pass" if absorb <= rules.ABS_THRESHOLD else "☠️ critical"),
        ], columns=["Parameter", "Reading", "IS 10500 limit", "Result"])
        st.dataframe(checks, use_container_width=True, hide_index=True)

# ---------------- Rules ----------------
with tab_rules:
    st.subheader("Deterministic safety verdict (no AI)")
    st.write("Every reading goes through fixed threshold rules. The worst result wins: "
             "**CRITICAL > UNSAFE > CAUTION > SAFE**.")
    st.table(pd.DataFrame([
        ("pH", "6.5 – 8.5", "pH < 6.5 or pH > 8.5", "UNSAFE — acidity / alkalinity alert"),
        ("Turbidity", "≤ 1 NTU acceptable, ≤ 5 NTU permissible", "1 < NTU ≤ 5", "CAUTION"),
        ("Turbidity", "", "NTU > 5", "UNSAFE — excessive suspended solids"),
        ("Temperature", "ambient", "T > 40 °C", "CAUTION — high thermal variance"),
        ("Temperature sensor", "", "no reading (−127 °C)", "CAUTION — sensor error"),
        ("Heavy metals (colorimetric)", "Fe ≤ 1.0 mg/L", f"A > {rules.ABS_THRESHOLD:.2f} AU",
         "CRITICAL — heavy-metal contamination"),
    ], columns=["Parameter", "IS 10500:2012 limit", "Condition", "Verdict"]))
    st.subheader("How the colorimeter works")
    st.markdown(
        "A reagent reacts with the metal ion and changes the sample's colour. An LED shines through the "
        "cuvette onto a light sensor. Press **CAL BLANK** with clean water to store *I_blank*; then the "
        "device measures *I_sample* and computes absorbance **A = log₁₀(I_blank / I_sample)**. "
        "By the Beer–Lambert law, A = ε·l·c, so absorbance is proportional to concentration. "
        "For iron with 1,10-phenanthroline (ε ≈ 11,100 L mol⁻¹ cm⁻¹, 1 cm path) that is ≈ 0.20 AU per mg/L, "
        "so the IS 10500 iron limit of 1.0 mg/L corresponds to A = 0.20. "
        "The slope must be re-calibrated with standard solutions on the real device.")
    st.caption("References: BIS IS 10500:2012 Drinking Water Specification; "
               "WHO Guidelines for Drinking-water Quality (4th ed.).")
