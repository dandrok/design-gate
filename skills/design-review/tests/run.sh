#!/usr/bin/env bash
# Gate suite for design-review. Fails if any case fails.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
python3 "$here/run_tests.py"
status=$?
echo "gate_review.py suite exit: $status"
exit $status
