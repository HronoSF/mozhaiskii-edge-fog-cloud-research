"""Explicit staged shell recipe and captured source identities; no guest operations."""
import hashlib
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE = REPO/'emulation/scheduling/reproducibility'
EXTRA = ('gates.py', 'entry.py', 'run.py', 'layout.py')
APP_WRAPPER = '''#!/usr/bin/env bash
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
'''


def health_wrapper(source):
    old = '"$py" /tmp/ehu-inputs/guest_experiment.py --source /opt/ehu-madt/madt --output /opt/ehu-madt/patched-calibration'
    new = '"$py" /tmp/ehu-inputs/tests/application-correctness/entry.py health --source /opt/ehu-madt/madt --output /opt/ehu-madt/patched-calibration'
    if source.count(old) != 1:
        raise ValueError('Original patched-health invocation changed')
    return source.replace(old, new)


def expected_inputs():
    ref = REPO/'reports/evidence/madt-scheduling-reproducibility-2026-10-22/S03/input-sha256.json'
    recipe = json.loads(ref.read_bytes())
    sha = lambda data: hashlib.sha256(data).hexdigest()
    recipe['guest_repair_proof.sh'] = sha(APP_WRAPPER.encode())
    recipe['tests/original-network-proof.sh'] = sha(health_wrapper((REPO/'emulation/madt/guest_repair_proof.sh').read_text()).encode())
    for name in EXTRA:
        recipe['tests/application-correctness/'+name] = sha((HERE/name).read_bytes())
    return recipe
