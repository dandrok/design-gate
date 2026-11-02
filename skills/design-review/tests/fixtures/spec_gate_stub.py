#!/usr/bin/env python3
"""Test double for spec-writer's validate-spec.py.

Same contract as the real gate: argv[1] is a spec path, exit 0 = valid,
exit 1 = violations, message on stdout. Using a double keeps this suite runnable
without spec-writer installed; it proves the wiring, not the spec rules -- those
are spec-writer's own suite.
"""

import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
if "GATE_FAIL" in text:
    print("spec gate (stub): GATE_FAIL marker present")
    sys.exit(1)
sys.exit(0)
