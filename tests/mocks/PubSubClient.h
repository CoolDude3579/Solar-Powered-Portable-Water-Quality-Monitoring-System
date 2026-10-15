#pragma once
#include "WiFi.h"
struct PubSubClient { PubSubClient(WiFiClient&) {} void setServer(const char*, int) {} bool setBufferSize(uint16_t) { return true; }
  void setSocketTimeout(uint16_t) {} bool connected() { return false; } bool connect(const char*) { return false; }
  int state() { return 0; } bool loop() { return true; } bool publish(const char*, const char*) { return true; } };
