#!/usr/bin/env bash
set -euo pipefail
stage=$1
py=/opt/ehu-madt/venv/bin/python
image_id=$(cat /opt/ehu-madt/endpoint-id.txt)
control_rc=0
"$py" /tmp/ehu-inputs/guest_experiment.py --source /opt/ehu-madt/madt --output /opt/ehu-madt/unpatched-control --image "$image_id" --stage calibration > /opt/ehu-madt/control-console.txt 2>&1 || control_rc=$?
"$py" - "$control_rc" <<'PY'
import json,sys
from pathlib import Path
p=Path('/opt/ehu-madt/unpatched-control')
s=json.loads((p/'summary.json').read_text())
assert int(sys.argv[1])!=0 and s['status']=='FAILED',s
assert s['failure']['error']=="RuntimeError('expected shaping qdisc readback')",s
assert 'UNIQUE constraint failed: if_index.peer_ifindex' in (p/'events.jsonl').read_text()
assert s['measurement_phases']==1 and not s['cleanup_errors'],s
print('Original namespace-index failure reproduced')
PY
"$py" /tmp/ehu-inputs/compat/apply_patch.py --output /opt/ehu-madt/patch-provenance
"$py" /tmp/ehu-inputs/tests/test_tcconfig_repair.py > /opt/ehu-madt/unit-regressions.txt 2>&1
cat /opt/ehu-madt/unit-regressions.txt
"$py" /tmp/ehu-inputs/verify_mapping.py --image "$image_id" --output /opt/ehu-madt/mapping-regressions
if test "$stage" = timing; then
  "$py" /tmp/ehu-inputs/guest_timing_diagnostic.py --image "$image_id" --output /opt/ehu-madt/timing-diagnostic
  exit
fi
"$py" /tmp/ehu-inputs/tests/application-correctness/entry.py health --source /opt/ehu-madt/madt --output /opt/ehu-madt/patched-calibration --image "$image_id" --stage calibration
if test "$stage" = full; then
  "$py" /tmp/ehu-inputs/guest_experiment.py --source /opt/ehu-madt/madt --output /opt/ehu-madt/patched-full --image "$image_id" --stage full
fi
