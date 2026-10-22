#!/usr/bin/env bash
set -euo pipefail
test "$1" = calibration
py=/opt/ehu-madt/venv/bin/python
export PYTHONPATH=/tmp/ehu-inputs/tests/scheduling:/tmp/ehu-inputs
"$py" /tmp/ehu-inputs/tests/scheduling/guest_pilot.py --output /opt/ehu-madt/scheduling --plan-only
health_rc=0
bash /tmp/ehu-inputs/tests/original-network-proof.sh calibration || health_rc=$?
if test "$health_rc" -ne 0; then
  "$py" /tmp/ehu-inputs/tests/scheduling/guest_pilot.py --output /opt/ehu-madt/scheduling --health-failed
  exit "$health_rc"
fi
exec "$py" /tmp/ehu-inputs/tests/application-correctness/entry.py application --output /opt/ehu-madt/scheduling
