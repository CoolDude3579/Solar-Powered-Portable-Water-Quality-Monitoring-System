#pragma once
#include "OneWire.h"
struct DallasTemperature { DallasTemperature(OneWire*) {} void begin() {} void setWaitForConversion(bool) {}
  void requestTemperatures() {} float getTempCByIndex(uint8_t) { return 25; } };
