// =====================================================================
//  rules.h  —  Deterministic water-safety rule engine (NO AI)
//  Solar-Powered Portable Water Quality Monitoring System
//
//  Plain C++ with no Arduino dependency, so the exact same file is:
//    * compiled into the ESP32 firmware (Wokwi + real hardware), and
//    * compiled on a PC by tests/run_tests.py to check every rule.
//  The Streamlit dashboard (dashboard/rules.py) mirrors this file and is
//  checked against the same test vectors (tests/test_vectors.json).
//
//  Limits: IS 10500:2012 (BIS) drinking-water specification + WHO.
// =====================================================================
#pragma once
#include <math.h>
#include <stdint.h>

namespace wqm {

// ---------------- Limits (IS 10500:2012) ----------------
const float PH_MIN            = 6.5f;   // acceptable range 6.5 – 8.5, no relaxation
const float PH_MAX            = 8.5f;
const float TURB_ACCEPTABLE   = 1.0f;   // NTU — acceptable limit
const float TURB_PERMISSIBLE  = 5.0f;   // NTU — permissible only if no alternate source
const float TEMP_WARN_C       = 40.0f;  // project spec: thermal variance warning
const float TEMP_FAULT_C      = -100.0f;// DS18B20 returns -127 °C when disconnected

// ---------------- Colorimetric heavy-metal channel ----------------
// Beer–Lambert:  A = epsilon * l * c.  For iron with 1,10-phenanthroline
// (510 nm, 1 cm cuvette) epsilon ≈ 11,100 L/mol/cm  ->  ≈ 0.20 AU per mg/L Fe.
// IS 10500 limit for iron = 1.0 mg/L  ->  alert when A > 0.20.
// Replace FE_SLOPE after calibrating with your own standard solutions.
const float FE_SLOPE_AU_PER_MGL = 0.20f;
const float FE_LIMIT_MGL        = 1.0f;
const float ABS_THRESHOLD       = FE_SLOPE_AU_PER_MGL * FE_LIMIT_MGL;   // 0.20 AU

enum Level : uint8_t { SAFE = 0, CAUTION = 1, UNSAFE = 2, CRITICAL = 3 };

// Reason flags (bit mask) — more than one can be set at once
enum Reason : uint8_t {
  R_PH_LOW      = 1 << 0,
  R_PH_HIGH     = 1 << 1,
  R_TURB_HIGH   = 1 << 2,   // > 5 NTU            -> UNSAFE
  R_TURB_ABOVE1 = 1 << 3,   // 1 < NTU <= 5       -> CAUTION
  R_TEMP_HIGH   = 1 << 4,   // > 40 °C            -> CAUTION
  R_TEMP_FAULT  = 1 << 5,   // sensor missing     -> CAUTION
  R_METAL       = 1 << 6,   // absorbance > limit -> CRITICAL
};
const uint8_t REASON_COUNT = 7;

struct Reading {
  float ph;          // 0 – 14
  float turbidity;   // NTU
  float tempC;       // °C
  float absorbance;  // AU, log10(I_blank / I_sample)
};

struct Verdict {
  Level   level;
  uint8_t reasons;   // OR of Reason flags
};

inline float absorbanceToFe(float a) {
  if (a < 0) a = 0;
  return a / FE_SLOPE_AU_PER_MGL;
}

inline Level maxLevel(Level a, Level b) { return a > b ? a : b; }

// The whole decision matrix. Boundaries are inclusive on the safe side
// (pH 6.5 and 8.5 are acceptable, 1.0 NTU is acceptable, 5.0 NTU is caution).
inline Verdict evaluate(const Reading& r) {
  Verdict v = { SAFE, 0 };

  if (r.ph < PH_MIN) { v.reasons |= R_PH_LOW;  v.level = maxLevel(v.level, UNSAFE); }
  if (r.ph > PH_MAX) { v.reasons |= R_PH_HIGH; v.level = maxLevel(v.level, UNSAFE); }

  if (r.turbidity > TURB_PERMISSIBLE) {
    v.reasons |= R_TURB_HIGH;   v.level = maxLevel(v.level, UNSAFE);
  } else if (r.turbidity > TURB_ACCEPTABLE) {
    v.reasons |= R_TURB_ABOVE1; v.level = maxLevel(v.level, CAUTION);
  }

  if (r.tempC < TEMP_FAULT_C) {
    v.reasons |= R_TEMP_FAULT;  v.level = maxLevel(v.level, CAUTION);
  } else if (r.tempC > TEMP_WARN_C) {
    v.reasons |= R_TEMP_HIGH;   v.level = maxLevel(v.level, CAUTION);
  }

  if (r.absorbance > ABS_THRESHOLD) {
    v.reasons |= R_METAL;       v.level = maxLevel(v.level, CRITICAL);
  }
  return v;
}

// Texts are <= 16 characters so they fit one line of the 16x2 LCD.
inline const char* levelText(Level l) {
  switch (l) {
    case SAFE:     return "SAFE TO DRINK";
    case CAUTION:  return "CAUTION";
    case UNSAFE:   return "UNSAFE";
    case CRITICAL: return "CRITICAL UNSAFE";
  }
  return "?";
}

inline const char* levelCode(Level l) {
  switch (l) {
    case SAFE:     return "SAFE";
    case CAUTION:  return "CAUTION";
    case UNSAFE:   return "UNSAFE";
    case CRITICAL: return "CRITICAL";
  }
  return "?";
}

inline const char* reasonText(uint8_t bit) {
  switch (bit) {
    case R_PH_LOW:      return "pH too acidic";
    case R_PH_HIGH:     return "pH too alkaline";
    case R_TURB_HIGH:   return "Turbidity >5NTU";
    case R_TURB_ABOVE1: return "Turbidity >1NTU";
    case R_TEMP_HIGH:   return "Water temp >40C";
    case R_TEMP_FAULT:  return "Temp sensor err";
    case R_METAL:       return "HEAVY METAL!";
  }
  return "";
}

inline const char* reasonCode(uint8_t bit) {
  switch (bit) {
    case R_PH_LOW:      return "PH_LOW";
    case R_PH_HIGH:     return "PH_HIGH";
    case R_TURB_HIGH:   return "TURB_HIGH";
    case R_TURB_ABOVE1: return "TURB_ABOVE_ACCEPTABLE";
    case R_TEMP_HIGH:   return "TEMP_HIGH";
    case R_TEMP_FAULT:  return "TEMP_SENSOR_FAULT";
    case R_METAL:       return "HEAVY_METAL";
  }
  return "";
}

}  // namespace wqm
