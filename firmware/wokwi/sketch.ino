// =====================================================================
//  Solar-Powered Portable Water Quality Monitoring System — ESP32 firmware
//  B.Tech Multidisciplinary Project, VIT Vellore
//
//  Reads pH, turbidity, temperature (DS18B20) and a colorimetric
//  light sensor; computes absorbance; runs the rule-based IS 10500 safety
//  verdict (rules.h, no AI); shows it on a 16x2 I2C LCD, RGB status LED
//  and buzzer; monitors the solar/battery supply; and publishes telemetry
//  over MQTT for the Streamlit dashboard.
//
//  SIMULATION = 1 -> Wokwi: slide potentiometers stand in for the pH and
//                    turbidity probes, knobs stand in for battery / solar.
//  SIMULATION = 0 -> real hardware: same code, real conversion formulas.
// =====================================================================
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include "rules.h"

#define SIMULATION 1

// ---------------- Pins (analog inputs on ADC1 so WiFi can run) ----------------
const int PIN_PH      = 34;   // pH probe module (sim: slide pot)
const int PIN_TURB    = 35;   // turbidity module (sim: slide pot)
const int PIN_LDR     = 32;   // colorimeter light sensor (LDR + 10k)
const int PIN_BAT     = 33;   // battery voltage via 100k/100k divider
const int PIN_SOLAR   = 36;   // solar panel voltage via 200k/100k divider
const int PIN_ONEWIRE = 4;    // DS18B20 data
const int PIN_BUZZER  = 25;
const int PIN_LED_R   = 26;
const int PIN_LED_G   = 27;
const int PIN_LED_B   = 14;
const int PIN_BTN_CAL  = 18;  // store current light level as the "blank"
const int PIN_BTN_PAGE = 19;  // next LCD page
const int PIN_BTN_MUTE = 23;  // mute / unmute buzzer

// ---------------- Network (Wokwi gives free internet via Wokwi-GUEST) --------
const char* WIFI_SSID   = "Wokwi-GUEST";
const char* WIFI_PASS   = "";
const char* MQTT_HOST   = "broker.hivemq.com";
const int   MQTT_PORT   = 1883;
const char* MQTT_TOPIC  = "vit-wqm/cooldude3579/device01/telemetry";
const char* DEVICE_ID   = "wqm-device-01";

// ---------------- Calibration constants ----------------
const float ADC_MAX = 4095.0f;
const float VREF    = 3.3f;
// LDR (must match the Wokwi part's rl10 / gamma attributes)
const float LDR_GAMMA = 0.7f;
const float LDR_RL10  = 50.0f;     // kOhm at 10 lux
const float LDR_FIXED = 10000.0f;  // fixed resistor in the module, Ohm
// Real-hardware pH: two-point calibration with pH 7 and pH 4 buffers
const float PH_V7 = 1.65f;         // ADC volts read in pH 7 buffer (measure!)
const float PH_V4 = 2.03f;         // ADC volts read in pH 4 buffer (measure!)
// Real-hardware turbidity (DFRobot SEN0189 curve, defined at 5 V output)
const float TURB_DIVIDER = 1.5f;   // 10k/20k divider brings 5 V down to 3.3 V
const float BAT_DIVIDER   = 2.0f;
const float SOLAR_DIVIDER = 3.0f;

// ---------------- Objects ----------------
LiquidCrystal_I2C lcd(0x27, 16, 2);
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature tempSensor(&oneWire);
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

// ---------------- State ----------------
wqm::Reading reading = { 7.0f, 0.0f, 25.0f, 0.0f };
wqm::Verdict verdict = { wqm::SAFE, 0 };
wqm::Level   lastLevel = wqm::SAFE;
float blankLux = 500.0f;           // light through clear water (calibrate!)
float sampleLux = 500.0f;
float batV = 3.9f, solarV = 0.0f;
int   batPct = 0;
bool  charging = false;
bool  muted = false;
bool  firstSample = true;

int   page = 0;                    // 0 readings, 1 verdict, 2 power, 3 network
const int PAGE_COUNT = 4;
unsigned long pageHoldUntil = 0;   // manual page selection pauses auto-rotate
unsigned long publishCount = 0;

unsigned long tSample = 0, tLcd = 0, tPage = 0, tPublish = 0, tMqttRetry = 0, tTempReq = 0;

// ---------------- Helpers ----------------
float adcVolts(int pin) { return analogRead(pin) / ADC_MAX * VREF; }
float frac(int pin)     { return analogRead(pin) / ADC_MAX; }
float ema(float prev, float x, float a) { return prev + a * (x - prev); }

float readPH() {
#if SIMULATION
  return frac(PIN_PH) * 14.0f;
#else
  float v = adcVolts(PIN_PH);
  return 7.0f + (v - PH_V7) * (4.0f - 7.0f) / (PH_V4 - PH_V7);
#endif
}

float readTurbidity() {
#if SIMULATION
  float f = frac(PIN_TURB);
  return f * f * 100.0f;           // squared: fine control in the 0–5 NTU region
#else
  float v = adcVolts(PIN_TURB) * TURB_DIVIDER;   // back to the module's 5 V scale
  if (v >= 4.2f) return 0.0f;
  if (v < 2.5f)  return 3000.0f;
  float ntu = -1120.4f * v * v + 5742.3f * v - 4352.9f;
  return ntu < 0 ? 0 : ntu;
#endif
}

float readLux() {
  float v = adcVolts(PIN_LDR);
  if (v >= VREF - 0.001f) return 0.0f;           // completely dark
  float r = LDR_FIXED * v / (VREF - v);          // LDR resistance
  if (r < 1.0f) r = 1.0f;
  float lux = pow(LDR_RL10 * 1e3f * pow(10.0f, LDR_GAMMA) / r, 1.0f / LDR_GAMMA);
  return isfinite(lux) ? lux : 100000.0f;
}

float readBattery() {
#if SIMULATION
  return 3.0f + frac(PIN_BAT) * 1.2f;            // 3.0 V (empty) – 4.2 V (full)
#else
  return adcVolts(PIN_BAT) * BAT_DIVIDER;
#endif
}

float readSolar() {
#if SIMULATION
  return frac(PIN_SOLAR) * 7.0f;                 // 6 V panel, ~7 V open-circuit
#else
  return adcVolts(PIN_SOLAR) * SOLAR_DIVIDER;
#endif
}

int batteryPercent(float v) {   // Li-ion open-circuit voltage curve
  const float V[] = {3.00f, 3.50f, 3.70f, 3.80f, 3.90f, 4.00f, 4.10f, 4.20f};
  const int   P[] = {0,     10,    40,    60,    75,    85,    95,    100};
  if (v <= V[0]) return 0;
  for (int i = 1; i < 8; i++)
    if (v <= V[i]) return P[i-1] + (int)((v - V[i-1]) / (V[i] - V[i-1]) * (P[i] - P[i-1]));
  return 100;
}

void setLed(bool r, bool g, bool b) {
  digitalWrite(PIN_LED_R, r); digitalWrite(PIN_LED_G, g); digitalWrite(PIN_LED_B, b);
}

// Returns the n-th active reason flag (cycles through all active reasons)
uint8_t nthReason(uint8_t mask, int n) {
  int count = 0;
  for (uint8_t i = 0; i < wqm::REASON_COUNT; i++) if (mask & (1 << i)) count++;
  if (count == 0) return 0;
  n %= count;
  for (uint8_t i = 0; i < wqm::REASON_COUNT; i++)
    if (mask & (1 << i)) { if (n == 0) return 1 << i; n--; }
  return 0;
}

void lcdLine(int row, const char* text) {
  char buf[17];
  snprintf(buf, sizeof(buf), "%-16s", text);
  lcd.setCursor(0, row);
  lcd.print(buf);
}

// ---------------- Sampling + rule engine ----------------
void sample() {
  float ph   = readPH();
  float turb = readTurbidity();
  sampleLux  = readLux();
  float a    = (sampleLux > 0.01f && blankLux > 0.01f) ? log10(blankLux / sampleLux) : 3.0f;
  if (a < 0) a = 0;

  if (firstSample) {
    reading.ph = ph; reading.turbidity = turb; reading.absorbance = a; firstSample = false;
  } else {            // light smoothing — real probes are noisy
    reading.ph         = ema(reading.ph, ph, 0.5f);
    reading.turbidity  = ema(reading.turbidity, turb, 0.5f);
    reading.absorbance = ema(reading.absorbance, a, 0.5f);
  }

  // DS18B20: non-blocking conversion (request, read ~750 ms later)
  if (millis() - tTempReq >= 800) {
    float t = tempSensor.getTempCByIndex(0);       // -127 if disconnected
    reading.tempC = t;
    tempSensor.requestTemperatures();
    tTempReq = millis();
  }

  batV     = readBattery();
  solarV   = readSolar();
  batPct   = batteryPercent(batV);
  charging = (solarV >= 4.5f) && (solarV > batV + 0.3f) && (batV < 4.19f);

  verdict = wqm::evaluate(reading);
  if (verdict.level > lastLevel) {   // got worse -> jump to verdict page, beep
    page = 1; tPage = millis();
  }
  lastLevel = verdict.level;
}

// ---------------- Outputs ----------------
void updateIndicators() {
  unsigned long t = millis();
  bool blink = (t / 250) % 2;
  switch (verdict.level) {
    case wqm::SAFE:     setLed(0, 1, 0); break;
    case wqm::CAUTION:  setLed(1, 1, 0); break;            // yellow
    case wqm::UNSAFE:   setLed(1, 0, 0); break;
    case wqm::CRITICAL: setLed(blink, 0, 0); break;        // flashing red
  }

  bool beep = false;
  if (!muted) {
    if (verdict.level == wqm::CRITICAL) beep = (t / 200) % 2;             // fast beeping
    else if (verdict.level == wqm::UNSAFE) beep = (t % 2000) < 150;       // chirp every 2 s
  }
  if (beep) tone(PIN_BUZZER, verdict.level == wqm::CRITICAL ? 2500 : 1800);
  else      noTone(PIN_BUZZER);
}

void drawLcd() {
  char l1[24], l2[24];
  switch (page) {
    case 0:   // live readings
      if (reading.tempC < wqm::TEMP_FAULT_C) snprintf(l1, sizeof(l1), "pH%5.2f T --.-C", reading.ph);
      else snprintf(l1, sizeof(l1), "pH%5.2f T%5.1fC", reading.ph, reading.tempC);
      snprintf(l2, sizeof(l2), "NTU%5.1f A%5.3f", reading.turbidity, reading.absorbance);
      break;
    case 1: { // verdict + reasons (cycles)
      snprintf(l1, sizeof(l1), "%s", wqm::levelText(verdict.level));
      uint8_t r = nthReason(verdict.reasons, (int)(millis() / 1500));
      if (r) snprintf(l2, sizeof(l2), "%s", wqm::reasonText(r));
      else   snprintf(l2, sizeof(l2), "IS10500 all OK");
      break;
    }
    case 2:   // power
      snprintf(l1, sizeof(l1), "Bat %4.2fV %3d%%", batV, batPct);
      if (charging)            snprintf(l2, sizeof(l2), "PV %3.1fV CHARGE", solarV);
      else if (solarV >= 1.0f) snprintf(l2, sizeof(l2), "PV %3.1fV LOW SUN", solarV);
      else                     snprintf(l2, sizeof(l2), "PV %3.1fV NO SUN", solarV);
      if (batV < 3.4f && !charging) snprintf(l2, sizeof(l2), "LOW BATTERY!");
      break;
    case 3:   // network + colorimeter
      snprintf(l1, sizeof(l1), "WiFi%s MQTT%s", WiFi.status() == WL_CONNECTED ? "OK" : "--",
               mqtt.connected() ? "OK" : "--");
      snprintf(l2, sizeof(l2), "Fe~%4.2fmg/L #%lu", wqm::absorbanceToFe(reading.absorbance),
               publishCount % 1000);
      break;
  }
  lcdLine(0, l1);
  lcdLine(1, l2);
}

// ---------------- Telemetry ----------------
int buildJson(char* out, size_t n) {
  char reasons[160] = "";
  size_t len = 0;
  for (uint8_t i = 0; i < wqm::REASON_COUNT; i++) {
    uint8_t bit = 1 << i;
    if (verdict.reasons & bit)
      len += snprintf(reasons + len, sizeof(reasons) - len, "%s\"%s\"", len ? "," : "", wqm::reasonCode(bit));
  }
  return snprintf(out, n,
    "{\"id\":\"%s\",\"uptime_ms\":%lu,\"ph\":%.2f,\"turbidity\":%.2f,\"temp\":%.1f,"
    "\"absorbance\":%.3f,\"fe_mgl\":%.2f,\"level\":\"%s\",\"reasons\":[%s],"
    "\"battery_v\":%.2f,\"battery_pct\":%d,\"solar_v\":%.2f,\"charging\":%s}",
    DEVICE_ID, millis(), reading.ph, reading.turbidity, reading.tempC, reading.absorbance,
    wqm::absorbanceToFe(reading.absorbance), wqm::levelCode(verdict.level), reasons,
    batV, batPct, solarV, charging ? "true" : "false");
}

void handleNetwork() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (!mqtt.connected()) {
    if (millis() - tMqttRetry < 5000) return;
    tMqttRetry = millis();
    char cid[40];
    snprintf(cid, sizeof(cid), "%s-%04lx", DEVICE_ID, (unsigned long)(esp_random() & 0xFFFF));
    if (mqtt.connect(cid)) Serial.println("[MQTT] connected to broker");
    else { Serial.print("[MQTT] connect failed, state "); Serial.println(mqtt.state()); }
  }
  mqtt.loop();
}

void publish() {
  char json[400];
  buildJson(json, sizeof(json));
  Serial.println(json);                               // also visible in Wokwi serial monitor
  if (mqtt.connected() && batV >= 3.3f) {             // save power on a near-empty battery
    if (mqtt.publish(MQTT_TOPIC, json)) publishCount++;
  }
}

// ---------------- Buttons ----------------
bool pressed(int pin, bool& prev) {
  bool now = digitalRead(pin) == LOW;
  bool edge = now && !prev;
  prev = now;
  return edge;
}
bool pCal = false, pPage = false, pMute = false;

void handleButtons() {
  if (pressed(PIN_BTN_CAL, pCal)) {
    blankLux = readLux();
    reading.absorbance = 0;
    lcdLine(0, "Blank calibrated");
    char b[17]; snprintf(b, sizeof(b), "I0 = %.0f lux", blankLux); lcdLine(1, b);
    Serial.printf("[CAL] blank set to %.1f lux\n", blankLux);
    delay(900);
  }
  if (pressed(PIN_BTN_PAGE, pPage)) {
    page = (page + 1) % PAGE_COUNT;
    pageHoldUntil = millis() + 10000;
    tPage = millis();
    drawLcd();
  }
  if (pressed(PIN_BTN_MUTE, pMute)) {
    muted = !muted;
    lcdLine(1, muted ? "Buzzer MUTED" : "Buzzer ON");
    delay(500);
  }
}

// ---------------- Setup / loop ----------------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_R, OUTPUT); pinMode(PIN_LED_G, OUTPUT); pinMode(PIN_LED_B, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_BTN_CAL, INPUT_PULLUP);
  pinMode(PIN_BTN_PAGE, INPUT_PULLUP);
  pinMode(PIN_BTN_MUTE, INPUT_PULLUP);
  analogReadResolution(12);

  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  lcdLine(0, "Water Quality");
  lcdLine(1, "Monitor v1.0");
  setLed(0, 0, 1);

  tempSensor.begin();
  tempSensor.setWaitForConversion(false);
  tempSensor.requestTemperatures();
  tTempReq = millis();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);     // channel 6 = fast connect in Wokwi
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setSocketTimeout(3);

  delay(1200);
  Serial.println("[BOOT] Solar-Powered Water Quality Monitor ready");
  Serial.printf("[BOOT] MQTT topic: %s\n", MQTT_TOPIC);
}

void loop() {
  unsigned long t = millis();
  handleButtons();
  handleNetwork();

  if (t - tSample >= 250)   { tSample = t; sample(); }
  updateIndicators();

  if (t - tPage >= 3000 && t >= pageHoldUntil) {
    tPage = t;
    page = (page + 1) % PAGE_COUNT;
  }
  if (t - tLcd >= 500) {
    tLcd = t;
    drawLcd();
  }
  if (t - tPublish >= 2000) { tPublish = t; publish(); }
}
