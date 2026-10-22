#!/usr/bin/env python3
"""Approved disposable-guest pilot, reusing the unchanged MADT VM lifecycle."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE=Path(__file__).resolve().parent
NETWORK=HERE.parent/'madt'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--assets-dir',type=Path)
    p.add_argument('--approved-disposable-guest',action='store_true',help='Only after actual user approval; a flag is not permission')
    a=p.parse_args()
    if not a.approved_disposable_guest:p.error('Obtain explicit user approval before VM/Docker/network operations')
    if a.output.exists():p.error('Output must be new')
    staging=Path(tempfile.mkdtemp(prefix='ehu-sched-input-',dir='/tmp'))
    provenance=dict(start=time.time_ns(),host_load_before=os.getloadavg(),input_host_runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    network_runner_sha256=hashlib.sha256((NETWORK/'run_docker28.py').read_bytes()).hexdigest())
    try:
        shutil.copytree(NETWORK,staging,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
        payload=staging/'tests/scheduling';payload.mkdir()
        for name in ('guest_pilot.py','run_pilot.py','PLAN.md'):shutil.copyfile(HERE/name,payload/name)
        shutil.copytree(HERE/'madt_scheduling',payload/'madt_scheduling',ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copyfile(NETWORK/'guest_repair_proof.sh',staging/'tests/original-network-proof.sh')
        wrapper='''#!/usr/bin/env bash
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
exec "$py" /tmp/ehu-inputs/tests/scheduling/guest_pilot.py --output /opt/ehu-madt/scheduling
'''
        (staging/'guest_repair_proof.sh').write_text(wrapper)
        provenance['original_guest_proof_sha256']=hashlib.sha256((NETWORK/'guest_repair_proof.sh').read_bytes()).hexdigest()
        provenance['wrapper_sha256']=hashlib.sha256(wrapper.encode()).hexdigest()
        provenance['git_head']=subprocess.check_output(['git','-C',str(HERE),'rev-parse','HEAD'],text=True).strip()
        provenance['git_status']=subprocess.check_output(['git','-C',str(HERE),'status','--porcelain'],text=True)
        spec=importlib.util.spec_from_file_location('existing_madt_runner',NETWORK/'run_docker28.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.HERE=staging # Expanded input bundle only; lifecycle code and frozen network proof unchanged.
        sys.argv=['run_docker28.py','--output',str(a.output.resolve()),'--stage','calibration']
        if a.assets_dir:sys.argv+=['--assets-dir',str(a.assets_dir.resolve())]
        return module.main()
    finally:
        shutil.rmtree(staging);provenance.update(end=time.time_ns(),staging_absent=not staging.exists(),host_load_after=os.getloadavg())
        if a.output.exists():(a.output/'scheduling-launch.json').write_text(json.dumps(provenance,indent=2)+'\n')

if __name__=='__main__':raise SystemExit(main())
