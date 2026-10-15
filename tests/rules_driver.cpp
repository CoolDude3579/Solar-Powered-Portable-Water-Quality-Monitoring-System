// Reads "ph turb temp abs" lines, prints "LEVEL CODE1,CODE2" — used by run_tests.py
#include <cstdio>
#include "../firmware/wokwi/rules.h"
int main() {
  float ph, tb, t, a;
  while (scanf("%f %f %f %f", &ph, &tb, &t, &a) == 4) {
    wqm::Verdict v = wqm::evaluate({ph, tb, t, a});
    printf("%s ", wqm::levelCode(v.level));
    bool first = true;
    for (int i = 0; i < wqm::REASON_COUNT; i++)
      if (v.reasons & (1 << i)) { printf("%s%s", first ? "" : ",", wqm::reasonCode(1 << i)); first = false; }
    printf("\n");
  }
}
