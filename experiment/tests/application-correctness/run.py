#!/usr/bin/env python3
"""One prospective A slot; unchanged VM/runtime/measurement sources, two split gates."""
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
from layout import APP_WRAPPER, EXTRA, health_wrapper
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE = HERE.parent/'reproducibility'
STUDY = REPO/'reports/evidence/madt-application-reproducibility-2026-10-22'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    if sys.flags.optimize or os.environ.get('PYTHONOPTIMIZE') not in (None, '', '0'):
        raise RuntimeError('Optimized Python prohibited')
    freeze = json.loads((HERE/'FREEZE.json').read_bytes())
    for name, digest in freeze['files'].items():
        if sha(REPO/name) != digest:
            raise RuntimeError('Prospective A freeze changed: '+name)
    spec = importlib.util.spec_from_file_location('original_S_baseline', BASE/'run_replay.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.verify()
    return freeze


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--slot', choices=('A01', 'A02', 'A03'), required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--approved-disposable-guest', action='store_true')
    a = p.parse_args()
    if not a.approved_disposable_guest:
        p.error('Explicit scoped human approval required; flag is not permission')
    verify()
    from approval import execution_authority
    authority=execution_authority(REPO,STUDY,HERE/'FREEZE.json')
    attempt = json.loads((STUDY/'records'/a.slot/'attempt.json').read_bytes())
    if attempt.get('collector_pid') != os.getppid() or attempt.get('invoked') is not True:
        raise RuntimeError('Matching one-shot collector required')
    if any((STUDY/'records'/a.slot/name).exists() for name in ('runner-result.json', 'decision.json')):
        raise RuntimeError('Consumed session')
    if a.output.resolve() != (STUDY/a.slot).resolve() or a.output.exists():
        raise RuntimeError('Exact new output required')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True):
        raise RuntimeError('Clean execution checkout required')
    staging = Path(tempfile.mkdtemp(prefix='ehu-app-repro-', dir='/tmp'))
    launch = dict(start_ns=time.time_ns(), slot=a.slot, registry_sha256=sha(STUDY/'registry.json'),
                  freeze_sha256=sha(HERE/'FREEZE.json'), overlay_root=str(staging),
                  git_head=authority['head'],
                  git_status='', wrapper_sha256=hashlib.sha256(APP_WRAPPER.encode()).hexdigest(),
                  input_host_runner_sha256=sha(Path(__file__)),
                  original_guest_proof_sha256=sha(REPO/'emulation/madt/guest_repair_proof.sh'),
                  network_runner_sha256=sha(REPO/'emulation/madt/run_docker28.py'))
    try:
        shutil.copytree(REPO/'emulation/madt', staging, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('bootstrap-docker28.sh', 'endpoint.Dockerfile', 'build_endpoint.sh'):
            shutil.copyfile(BASE/name, staging/name)
        shutil.copytree(BASE/'runtime', staging/'tests/runtime-baseline')
        payload = staging/'tests/scheduling'; payload.mkdir()
        for name in ('guest_pilot.py', 'run_pilot.py', 'PLAN.md'):
            shutil.copyfile(HERE.parent/name, payload/name)
        shutil.copytree(HERE.parent/'madt_scheduling', payload/'madt_scheduling',
                        ignore=shutil.ignore_patterns('__pycache__'))
        extra = staging/'tests/application-correctness'; extra.mkdir()
        for name in EXTRA:
            shutil.copyfile(HERE/name, extra/name)
        (staging/'tests/original-network-proof.sh').write_text(health_wrapper((REPO/'emulation/madt/guest_repair_proof.sh').read_text()))
        (staging/'guest_repair_proof.sh').write_text(APP_WRAPPER)
        spec = importlib.util.spec_from_file_location('unchanged_owned_network_runner', REPO/'emulation/madt/run_docker28.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.HERE = staging
        sys.argv = ['run_docker28.py', '--output', str(a.output.resolve()), '--stage', 'calibration']
        verify()
        final_authority=execution_authority(REPO,STUDY,HERE/'FREEZE.json')
        if final_authority['head']!=authority['head'] or subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
            raise RuntimeError('Execution HEAD/source changed during staging')
        return module.main()
    finally:
        shutil.rmtree(staging)
        launch.update(end_ns=time.time_ns(), overlay_absent=not staging.exists(), staging_absent=not staging.exists())
        if a.output.exists():
            (a.output/'scheduling-launch.json').write_text(json.dumps(launch, indent=2, sort_keys=True)+'\n')
            (a.output/'application-replay-launch.json').write_text(json.dumps(launch, indent=2, sort_keys=True)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
