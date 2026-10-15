// Minimal stubs so sketch.ino can be syntax-checked on a PC. NOT used on the device.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cstdarg>
#include <cstddef>
using std::isfinite;
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline int digitalRead(int) { return 1; }
inline int analogRead(int) { return 0; }
inline void analogReadResolution(int) {}
inline unsigned long millis() { return 0; }
inline void delay(unsigned long) {}
inline void tone(int, unsigned int) {}
inline void noTone(int) {}
inline uint32_t esp_random() { return 4; }
struct SerialStub {
  void begin(long) {}
  template <class T> void print(T) {}
  template <class T> void println(T) {}
  void println() {}
  int printf(const char* f, ...) __attribute__((format(printf, 2, 3))) { return 0; }
};
static SerialStub Serial;
struct TwoWire { void begin(int, int) {} };
static TwoWire Wire;
