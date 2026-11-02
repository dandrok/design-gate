#!/usr/bin/env bash
# Repo runner: every skill's own suite, one total. Fails if any suite fails.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
fail=0
ran=0
for suite in "$root"/skills/*/tests/run.sh; do
  [ -x "$suite" ] || continue
  ran=$((ran+1))
  name=$(basename "$(dirname "$(dirname "$suite")")")
  echo "=== $name"
  "$suite" || fail=$((fail+1))
done
echo
if [ "$ran" -eq 0 ]; then
  echo "no suites found — refusing to report success"
  exit 1
fi
echo "$((ran-fail))/$ran skill suites passed"
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
