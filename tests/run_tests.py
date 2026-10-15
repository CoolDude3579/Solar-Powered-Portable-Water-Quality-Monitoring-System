"""Checks firmware (rules.h) and dashboard (rules.py) against the same test vectors,
and compile-checks sketch.ino against stub Arduino headers.  Run:  python3 tests/run_tests.py"""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "dashboard"))
import rules

vectors = json.load(open(os.path.join(HERE, "test_vectors.json")))
exe = os.path.join(tempfile.gettempdir(), "wqm_rules_driver")
subprocess.run(["g++", "-std=c++17", "-Wall", "-Werror", "-o", exe, os.path.join(HERE, "rules_driver.cpp")], check=True)
inp = "".join(f"{v['ph']} {v['turbidity']} {v['temp']} {v['absorbance']}\n" for v in vectors)
cpp_out = subprocess.run([exe], input=inp, capture_output=True, text=True, check=True).stdout.splitlines()

fails = 0
for v, line in zip(vectors, cpp_out):
    lvl, _, rs = line.partition(" ")
    cpp = (lvl, [r for r in rs.split(",") if r])
    py_v = rules.evaluate(v["ph"], v["turbidity"], v["temp"], v["absorbance"])
    py = (py_v.level, py_v.reasons)
    exp = (v["level"], v["reasons"])
    ok = cpp == exp and py == exp
    fails += not ok
    print(("PASS " if ok else "FAIL ") + v["name"] + ("" if ok else f"  expected={exp} cpp={cpp} py={py}"))

# Compile-check the full sketch with stub headers (catches typos before Wokwi)
sk = os.path.join(tempfile.gettempdir(), "sketch_check.cpp")
open(sk, "w").write('#include "Arduino.h"\n' + open(os.path.join(ROOT, "firmware/wokwi/sketch.ino")).read())
r = subprocess.run(["g++", "-std=c++17", "-fsyntax-only", "-Wall", "-Wno-unused-variable", "-Wno-format-truncation",
                    "-I", os.path.join(HERE, "mocks"), "-I", os.path.join(ROOT, "firmware/wokwi"), sk],
                   capture_output=True, text=True)
print("PASS sketch.ino compiles against stubs" if r.returncode == 0 else "FAIL sketch.ino:\n" + r.stderr)
fails += r.returncode != 0
print(f"\n{len(vectors) + 1 - fails}/{len(vectors) + 1} checks passed")
sys.exit(1 if fails else 0)
