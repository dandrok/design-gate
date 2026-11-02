#!/usr/bin/env bash
# Claim checks for design-drift. Fails if any case fails.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
python3 "$here/run_tests.py"
status=$?
echo "gate_drift.py suite exit: $status"
exit $status
