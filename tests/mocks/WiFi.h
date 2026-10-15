#pragma once
#include "Arduino.h"
#define WL_CONNECTED 3
#define WIFI_STA 1
struct WiFiClass { void mode(int) {} void begin(const char*, const char*, int) {} int status() { return 0; } };
static WiFiClass WiFi;
struct WiFiClient {};
