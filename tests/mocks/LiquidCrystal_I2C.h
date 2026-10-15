#pragma once
#include "Arduino.h"
struct LiquidCrystal_I2C { LiquidCrystal_I2C(uint8_t, uint8_t, uint8_t) {} void init() {} void backlight() {}
  void setCursor(uint8_t, uint8_t) {} void print(const char*) {} };
