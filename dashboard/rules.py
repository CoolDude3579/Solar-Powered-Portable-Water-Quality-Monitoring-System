"""
Deterministic water-safety rule engine (NO AI) — Python mirror of
firmware/wokwi/rules.h. Both are checked against tests/test_vectors.json,
so the dashboard and the device always give the same verdict.

Limits: IS 10500:2012 (BIS) drinking-water specification + WHO.
"""
from dataclasses import dataclass, field

# ---------------- Limits (IS 10500:2012) ----------------
PH_MIN = 6.5
PH_MAX = 8.5
TURB_ACCEPTABLE = 1.0     # NTU
TURB_PERMISSIBLE = 5.0    # NTU (only if no alternate source)
TEMP_WARN_C = 40.0
TEMP_FAULT_C = -100.0     # DS18B20 reports -127 °C when disconnected

# Colorimetric channel: Beer–Lambert, Fe + 1,10-phenanthroline, 1 cm cuvette
FE_SLOPE_AU_PER_MGL = 0.20
FE_LIMIT_MGL = 1.0
ABS_THRESHOLD = FE_SLOPE_AU_PER_MGL * FE_LIMIT_MGL   # 0.20 AU

LEVELS = ["SAFE", "CAUTION", "UNSAFE", "CRITICAL"]

# Same bit order as rules.h
REASONS = [
    ("PH_LOW", "pH too acidic"),
    ("PH_HIGH", "pH too alkaline"),
    ("TURB_HIGH", "Turbidity > 5 NTU"),
    ("TURB_ABOVE_ACCEPTABLE", "Turbidity > 1 NTU"),
    ("TEMP_HIGH", "Water temperature > 40 °C"),
    ("TEMP_SENSOR_FAULT", "Temperature sensor error"),
    ("HEAVY_METAL", "Heavy-metal colour shift above limit"),
]
REASON_TEXT = dict(REASONS)

LEVEL_TEXT = {
    "SAFE": "Safe to drink",
    "CAUTION": "Caution",
    "UNSAFE": "Unsafe",
    "CRITICAL": "Critical — unsafe",
}


@dataclass
class Verdict:
    level: str
    reasons: list = field(default_factory=list)


def absorbance_to_fe(a: float) -> float:
    return max(a, 0.0) / FE_SLOPE_AU_PER_MGL


def evaluate(ph: float, turbidity: float, temp_c: float, absorbance: float) -> Verdict:
    lvl = 0
    reasons = []

    def hit(code, level):
        nonlocal lvl
        reasons.append(code)
        lvl = max(lvl, level)

    if ph < PH_MIN:
        hit("PH_LOW", 2)
    if ph > PH_MAX:
        hit("PH_HIGH", 2)

    if turbidity > TURB_PERMISSIBLE:
        hit("TURB_HIGH", 2)
    elif turbidity > TURB_ACCEPTABLE:
        hit("TURB_ABOVE_ACCEPTABLE", 1)

    if temp_c < TEMP_FAULT_C:
        hit("TEMP_SENSOR_FAULT", 1)
    elif temp_c > TEMP_WARN_C:
        hit("TEMP_HIGH", 1)

    if absorbance > ABS_THRESHOLD:
        hit("HEAVY_METAL", 3)

    order = [code for code, _ in REASONS]
    reasons.sort(key=order.index)
    return Verdict(LEVELS[lvl], reasons)
