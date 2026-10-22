"""Guest-only entry over original modules; no VM/privileged operations on import."""
import importlib.util
import json
from pathlib import Path
import sys
from gates import assess, install


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    mode, *arguments = sys.argv[1:]
    if mode not in ('health', 'application'):
        raise ValueError('Unknown entry mode')
    if mode == 'health':
        if arguments.count('--output') != 1:
            raise ValueError('Exactly one health output required')
        out = Path(arguments[arguments.index('--output')+1])
        if (out/'application-gate-completion.json').exists():
            raise FileExistsError('Health already completed; no second invocation')
    original = Path('/tmp/ehu-inputs')
    sys.path.insert(0, str(original))
    network = load('guest_experiment', original/'guest_experiment.py')
    install(network.Experiment)
    if mode == 'application':
        pilot = load('original_guest_pilot', original/'tests/scheduling/guest_pilot.py')
        sys.argv = ['guest_pilot.py', *arguments]
        return pilot.main()
    sys.argv = ['guest_experiment.py', *arguments]
    try:
        network.main()
    except SystemExit as end:
        rc = end.code
    else:
        raise RuntimeError('Original health CLI did not exit')
    summary = json.loads((out/'summary.json').read_text())
    measurements = json.loads((out/'measurements.json').read_text())
    if (type(rc) is not int or summary['failure'] is not None
            or summary['cleanup_errors'] or summary['status'] not in ('PASSED', 'FAILED_ACCEPTANCE')):
        raise RuntimeError('Health did not finish with safe original cleanup')
    receipt = assess(measurements, summary['checks'],
                     'calibration passes without threshold changes', finished=True)
    expected = 0 if receipt['original_qualification_passed'] else 1
    if rc != expected or summary['status'] != ('PASSED' if expected == 0 else 'FAILED_ACCEPTANCE'):
        raise RuntimeError('Original health status/exit disagreement')
    receipt.update(original_cli_returncode=rc, original_status=summary['status'],
                   entry_returncode=0, scope='Application eligibility only; original numerical failures retained')
    with (out/'application-gate-completion.json').open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True); stream.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
