#!/usr/bin/env python3
"""Bounded, offline checks of one public runner output. Never starts a VM."""
import argparse
import base64
import collections
from dataclasses import asdict
from functools import lru_cache
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ('E', 'F', 'C')
OUTCOMES = ('completed', 'rejected', 'failed', 'unresolved', 'not_released')
MAX_BYTES = 256 * 1024 * 1024
MAX_FILE = 32 * 1024 * 1024


class Missing(ValueError):
    """Evidence is unavailable; this cannot establish a pass."""


def require(value, message):
    if not value:
        raise ValueError(message)


def decode(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite JSON constant: ' + value)
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def integer(value):
    require(type(value) is int and value >= 0, 'Expected a nonnegative integer')
    return value


def read_file(path):
    if not path.is_file():
        raise Missing('Missing file: ' + path.name)
    require(not path.is_symlink() and path.stat().st_size <= MAX_FILE,
            'Unsafe or oversized file: ' + path.name)
    return path.read_bytes()


class Archive:
    """Read regular members only, with no extraction or execution of archive code."""
    def __init__(self, path):
        if not path.is_file():
            raise Missing('Missing guest-evidence.tar.gz')
        require(not path.is_symlink() and path.stat().st_size <= MAX_BYTES,
                'Unsafe or oversized evidence archive')
        with path.open('rb') as source:
            self.sha256 = hashlib.file_digest(source, 'sha256').hexdigest()
        # Read through the gzip trailer: tar end markers alone do not check its CRC.
        size = 0
        with gzip.open(path, 'rb') as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                require(size <= MAX_BYTES, 'Evidence exceeds 256 MiB expanded limit')
        self.tar = tarfile.open(path, 'r:gz')
        self.files = {}
        names = set()
        try:
            for member in self.tar:
                name = member.name
                pure = PurePosixPath(name)
                require(name and not pure.is_absolute() and '..' not in pure.parts
                        and str(pure) == name.rstrip('/') and name not in names,
                        'Unsafe or duplicate tar member: ' + name)
                names.add(name)
                require(len(names) <= 10000 and (member.isdir() or member.isfile()),
                        'Unsupported tar member or member limit exceeded')
                if member.isfile():
                    require(member.size <= MAX_FILE, 'Oversized tar member: ' + name)
                    self.files[name] = member
        except BaseException:
            self.close()
            raise

    def close(self):
        self.tar.close()

    def data(self, name):
        if name not in self.files:
            raise Missing('Missing archive member: ' + name)
        return self.tar.extractfile(self.files[name]).read()

    def json(self, name):
        return decode(self.data(name))

    def lines(self, name):
        return [decode(line) for line in self.data(name).splitlines() if line.strip()]


def contracts():
    """Only import the local pinned public contracts, never a run's captured code."""
    pins = decode(read_file(ROOT / 'experiment/INPUTS.sha256.json'))
    for name, expected in pins.items():
        require(digest(read_file(ROOT / 'experiment' / name)) == expected,
                'Changed local pinned runtime input: ' + name)
    sys.path.insert(0, str(ROOT / 'experiment/tests/scheduling'))
    from madt_scheduling import core
    modules = []
    for name, relative in [('pilot', 'tests/scheduling/guest_pilot.py'),
                           ('gates', 'tests/application-correctness/gates.py')]:
        spec = importlib.util.spec_from_file_location('public_verify_' + name, ROOT / 'experiment' / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return pins, core, *modules


@lru_cache(maxsize=512)
def reference(task_id, iterations, size, seed):
    from madt_scheduling.core import Task, compute, payload
    task = Task(task_id, iterations, size, seed=seed)
    data = payload(task)
    return digest(data), compute(task, data)


def expected_jobs(config, core):
    scored = [(core.Task(**t), 'scored', config['forced'].get(str(t['id']))) for t in config['tasks']]
    repeats = config['warmup_repetitions']
    warmup = [(core.Task(2**63 + i, *core.CLASSES[c], seed=0), 'warmup', worker)
              for i, (worker, c, _) in enumerate((w, c, r) for w in WORKERS for c in range(4) for r in range(repeats))]
    return {t.id: (asdict(t), phase, worker) for t, phase, worker in warmup + scored}


def check_cell(archive, name, expected, core, profiles):
    prefix = 'scheduling/' + name + '/'
    cfg = archive.json(prefix + 'declared-source-config.json')
    for key, value in expected.items():
        require(cfg[key] == value, name + ': changed configuration field ' + key)
    require(cfg.get('deadline_ns', 1_000_000_000) == 1_000_000_000,
            name + ': changed planned-arrival deadline')
    require(cfg.get('credits', 32) == 32 and cfg.get('memory', 64*1048576) == 64*1048576
            and cfg['upload_port'] == 41000 and cfg['event_port'] == 41001, name + ': changed finite limits or ports')
    core.Profiles.from_dict(cfg['profiles'])
    require(type(cfg['seed']) is int, name + ': seed must be an integer')
    require(cfg['profiles'] == profiles and cfg['require_linux_clock'] is True
            and cfg['tie_order'] == list(WORKERS) and cfg['seed'] == 0,
            name + ': profiles, clock or tie order changed')
    jobs = expected_jobs(cfg, core)
    rows = archive.json(prefix + 'source/tasks.json')
    require(len(rows) == len(jobs) and len({r['id'] for r in rows}) == len(rows)
            and {r['id'] for r in rows} == set(jobs), name + ': missing, duplicate or extra task IDs')
    summary = archive.json(prefix + 'source/summary.json')
    require(summary['status'] == 'RUN_FINISHED' and summary['errors'] == []
            and summary['kind'] == cfg['kind'] and summary['policy'] == cfg['policy']
            and summary['profiles'] == profiles, name + ': source did not finish cleanly')
    exits = archive.json(prefix + 'exec-status.json')
    require(set(exits['statuses']) == set(WORKERS) | {'source'}, name + ': missing process status')
    require(all(e['Running'] is False and type(e['ExitCode']) is int and e['ExitCode'] == 0
                for e in exits['statuses'].values()), name + ': process failure')
    events = archive.lines(prefix + 'source/events.jsonl')
    require(not any(e['event'] == 'instrument_error' for e in events), name + ': explicit source instrument error')
    shutdowns = [e for e in events if e['event'] == 'shutdown']
    require(len(shutdowns) == 1 and events[-1]['event'] == 'shutdown'
            and shutdowns[0]['summary'] == summary, name + ': source shutdown/summary contradiction')
    validated = [e for e in events if e['event'] == 'validated_result']
    require(len(validated) == len(rows) and len({e['id'] for e in validated}) == len(rows),
            name + ': missing or duplicate source completion')
    results = {e['id']: e for e in validated}
    starts = [e for e in events if e['event'] == 'scored_start']
    require(len(starts) == 1 and starts[0]['start'] == summary['start'], name + ': scored origin mismatch')
    # Clock assertions are checked against saved identities and causal probe stamps.
    hellos = [e for e in events if e['event'] == 'worker_hello']
    probes = [e for e in events if e['event'] == 'clock_validated']
    require(collections.Counter(e['worker'] for e in hellos) == collections.Counter(WORKERS), name + ': missing clock identity')
    require(all(e['source_clock'] == hellos[0]['source_clock'] for e in hellos), name + ': workers use different source clocks')
    for event in hellos:
        hello = event['hello']
        require(hello['type'] == 'hello' and hello['run_id'] == cfg['run_id']
                and hello['worker'] == event['worker'] and isinstance(hello['epoch'], str) and hello['epoch']
                and integer(hello['pid']) > 0, name + ': invalid worker hello identity')
        identity = event['source_clock']
        require(identity == event['hello']['clock'] and identity['boot'] and identity['time_namespace']
                and identity['offsets'] is not None, name + ': inconsistent clock identity')
        offsets = [line.split() for line in identity['offsets'].splitlines()]
        require(len(offsets) == 2 and {line[0] for line in offsets} == {'monotonic', 'boottime'}
                and all(len(line) == 3 and int(line[1]) == int(line[2]) == 0 for line in offsets),
                name + ': missing or nonzero clock offsets')
    require(len(probes) == 15 and {(e['worker'], e['reply']['probe']) for e in probes}
            == {(w, i) for w in WORKERS for i in range(5)}, name + ': incomplete clock probes')
    for e in probes:
        require(e['reply']['type'] == 'clock_reply' and e['reply']['run_id'] == cfg['run_id']
                and e['reply']['worker'] == e['worker'], name + ': invalid clock reply identity')
        stamps = [integer(e['start']), integer(e['reply']['received']), integer(e['reply']['sent']), integer(e['receipt'])]
        require(stamps == sorted(stamps), name + ': impossible clock probe')
    epochs = {e['worker']: e['hello']['epoch'] for e in hellos}
    for e in events:
        if e['event'] in ['telemetry_received', 'result_received', 'validated_result']:
            message = e['message']
            require(e['worker'] in WORKERS and message['run_id'] == cfg['run_id']
                    and message['worker'] == e['worker'], name + ': source message identity mismatch')
            expected_type = 'telemetry' if e['event'] == 'telemetry_received' else 'result'
            require(message['type'] == expected_type, name + ': source message type mismatch')
            if expected_type == 'telemetry':
                require(message['epoch'] == epochs[e['worker']], name + ': worker epoch changed')
    releases = [e for e in events if e['event'] == 'release']
    placements = [e for e in events if e['event'] == 'placement']
    for observed in [releases, placements]:
        require(len(observed) == len(rows) and {integer(e['id']) for e in observed} == set(jobs),
                name + ': missing/duplicate release or placement event')
    releases = {e['id']: e for e in releases};placements = {e['id']: e for e in placements}
    for row in rows:
        integer(row['id'])
        task, phase, forced = jobs[row['id']]
        core.Task(**row['task'])
        require(row['task'] == task and row['phase'] == phase and row['forced'] == forced,
                name + ': task/workload identity changed')
        require(row['outcome'] == 'completed' and row['worker'] in WORKERS,
                name + ': noncompleted offered task')
        require(releases[row['id']]['a_star'] == row['a_star'] and releases[row['id']]['a'] == row['a']
                and releases[row['id']]['phase'] == phase and placements[row['id']]['worker'] == row['worker']
                and placements[row['id']]['snapshot_time'] == row['b'] and placements[row['id']]['d'] == row['d'],
                name + ': release/placement source evidence changed')
        if forced:
            require(row['worker'] == forced, name + ': forced worker mismatch')
        for key in ['a_star', 'a', 'g', 'b', 'c', 'd', 'e', 'f', 'x', 'y', 'z', 'cpu_ns', 'decision_cpu_ns', 'sequence']:
            integer(row[key])
        require(row['a_star'] <= row['a'], name + ': release before planned arrival')
        if phase == 'scored':
            require(row['a_star'] == summary['start'] + task['release_ns'], name + ': changed planned arrival')
        require(list(core.timing_components(row)) == row['components_ns'], name + ': invalid timing decomposition')
        require(type(row['on_time']) is bool and row['on_time'] == (row['z'] <= row['a_star'] + 1_000_000_000),
                name + ': changed planned-arrival SLO')
        result = results[row['id']]
        message = result['message']
        require(result['worker'] == row['worker'] and result['z'] == row['z']
                and message['id'] == row['id'] and message['worker'] == row['worker']
                and message['run_id'] == cfg['run_id'], name + ': result source/worker identity mismatch')
        require(all(message[k] == row[k] for k in ['sequence', 'payload_hash', 'f', 'x', 'y', 'cpu_ns']),
                name + ': result/source record disagreement')
        payload_hash, value = reference(task['id'], task['iterations'], task['size'], task['seed'])
        require(row['payload_hash'] == payload_hash and base64.b64decode(message['value'], validate=True) == value,
                name + ': incorrect deterministic task result')
    for worker in WORKERS:
        ws = archive.json(prefix + worker + '/summary.json')
        require(ws['errors'] == [] and ws['remaining'] == 0 and ws.get('censored_shutdown') is False,
                name + ': worker failed or censored')
        we = archive.lines(prefix + worker + '/events.jsonl')
        require(not any(e['event'] in ['upload_error', 'control_error'] for e in we), name + ': explicit worker error')
        shutdowns = [e for e in we if e['event'] == 'shutdown']
        require(len(shutdowns) == 1 and we[-1]['event'] == 'shutdown'
                and shutdowns[0]['errors'] == ws['errors'] and shutdowns[0]['remaining'] == ws['remaining']
                and all(e['worker'] == worker for e in we), name + ': worker shutdown/summary or identity contradiction')
        assigned = sorted((r for r in rows if r['worker'] == worker), key=lambda r: r['sequence'])
        require([r['sequence'] for r in assigned] == list(range(1, len(assigned) + 1)), name + ': commitment sequence gap')
        for kind in ['input_admitted', 'execution_ended']:
            observed = [e for e in we if e['event'] == kind]
            require([e['id'] for e in observed] == [r['id'] for r in assigned], name + ': worker missing/duplicate/non-FIFO ' + kind)
            for e, r in zip(observed, assigned):
                require(e['worker'] == worker, name + ': worker event identity changed')
                keys = ['f', 'sequence'] if kind == 'input_admitted' else ['x', 'y', 'cpu_ns']
                require(all(e[k] == r[k] for k in keys), name + ': worker/source timestamps disagree')
        for a, b in zip(assigned, assigned[1:]):
            require(a['y'] <= b['x'], name + ': overlapping single-slot execution')
    scored = [r for r in rows if r['phase'] == 'scored']
    counts = {outcome: sum(r['outcome'] == outcome for r in scored) for outcome in OUTCOMES}
    on_time = sum(r['on_time'] for r in scored)
    require(summary['offered'] == len(scored) and summary['outcomes'] == counts
            and summary['on_time'] == on_time, name + ': offered/outcome/SLO accounting mismatch')
    return {'cell': name, 'total_outputs': len(rows), 'scored': len(scored), 'on_time': on_time,
            'outcomes': counts}, rows


def application(archive, core, pilot):
    plan = archive.json('scheduling/plan.json')
    require(plan == pilot.make_plan(), 'Changed original 12-cell plan or task stream')
    state = archive.json('scheduling/state.json')
    require(state['status'] == 'CORRECTNESS_PILOT_COMPLETED' and not state.get('failure')
            and not state.get('cleanup_error'), 'Application failed, incomplete or cleanup failed')
    require(len(state['cells']) == 12, 'Missing comparison cells')
    for declared, observed in zip(plan['cells'], state['cells']):
        require(all(observed[k] == v for k, v in declared.items()) and observed['status'] == 'COMPLETED',
                'Comparison cell missing, changed or incomplete')
    frozen = archive.json('scheduling/frozen-profiles.json')
    freeze = archive.json('scheduling/freeze.json')
    require(freeze['profiles_sha256'] == digest(archive.data('scheduling/frozen-profiles.json'))
            and freeze['plan_sha256'] == digest(archive.data('scheduling/plan.json')), 'Profile/plan freeze hash mismatch')
    calibrations = {}
    cells = []
    for index, network in enumerate(('unshaped', 'delay20')):
        tasks = [asdict(core.Task(2**62 + index * 100 + i, w, b))
                 for i, (_, w, b, _) in enumerate((j, w, b, r) for j in WORKERS for w, b in core.CLASSES for r in range(3))]
        expected = dict(kind='calibration', policy='rr', tasks=tasks,
                        forced={str(t['id']): WORKERS[i // 12] for i, t in enumerate(tasks)},
                        warmup_repetitions=0, horizon_ns=0, drain_seconds=60)
        result, rows = check_cell(archive, 'calibration-' + network, expected, core, pilot.blank_profiles())
        calibrations[network] = rows
        cells.append(result)
    require(pilot.freeze_profiles(calibrations) == frozen, 'Calibration-derived profiles disagree; no evaluation refitting permitted')
    expected = dict(kind='queue-proof', policy='rr', tasks=[asdict(core.Task(i, 800000, 1048576)) for i in range(12)],
                    forced={str(i): WORKERS[i // 4] for i in range(12)}, warmup_repetitions=0, horizon_ns=0, drain_seconds=60)
    result, queue = check_cell(archive, 'queue-proof', expected, core, frozen['unshaped'])
    require(any(a['worker'] == b['worker'] and a['id'] != b['id'] and a['x'] <= b['f'] < a['y'] and b['e'] < a['y']
                for a in queue for b in queue), 'Missing actual queue-overlap proof')
    cells.append(result)
    for i, cell in enumerate(plan['cells']):
        expected = dict(kind='comparison', policy=cell['policy'], tasks=plan['traces'][cell['scenario']], forced={},
                        warmup_repetitions=5, horizon_ns=6_000_000_000, drain_seconds=60)
        result, _ = check_cell(archive, f'cell-{i:02d}', expected, core, frozen[cell['network']])
        saved = state['cells'][i]['analysis']
        require(saved['instrument_checks'] == 'PASSED' and saved['offered'] == result['scored']
                and saved['outcomes'] == result['outcomes'] and saved['on_time'] == result['on_time'],
                'Stored per-cell analysis disagrees with raw tasks')
        cells.append(result)
    return dict(cells=cells, worker_outputs=sum(c['total_outputs'] for c in cells),
                comparison_offered=sum(c['scored'] for c in cells[3:]),
                comparison_on_time=sum(c['on_time'] for c in cells[3:]),
                scope='Task outputs, original workload/deadline, accounting and FIFO/timing consistency; not causal scheduler replay')


def network(archive, gates):
    results = {}
    for label, prefix, aggregate in [('health', 'patched-calibration/', 'calibration passes without threshold changes'),
                                     ('application', 'scheduling/network/', 'application network calibration unchanged criteria')]:
        measurements = archive.json(prefix + 'measurements.json')
        events = archive.lines(prefix + 'events.jsonl')
        checks = [{k: v for k, v in e.items() if k not in ['action', 'monotonic_ns', 'wall_time_ns']}
                  for e in events if e['action'] == 'acceptance_check']
        if label == 'health':
            summary = archive.json(prefix + 'summary.json')
            require(summary['failure'] is None and summary['cleanup_errors'] == []
                    and summary['checks'] == checks, 'Health checks/summary disagree or failed')
        required = {'expected shaping qdisc readback', 'numerical netem delay readback in seconds',
                    'numerical HTB rate readback', 'shaping removed'}
        required |= ({'TCP works in both directions before cut', 'cut path fails in both directions',
                      'path cut leaves control reachable', 'cut path blocks real TCP without received data',
                      'reverse TCP restored after cut'} if label == 'health' else
                     {'gateway routes through fog', 'gateway to cloud alive', 'gateway cut/control', 'gateway restored'})
        require(required <= {c['description'] for c in checks}, 'Missing recorded actuation or partition/recovery checks')
        for m in measurements:
            require(set(m['path_packet_deltas']) == {'cloud_host_veth', 'fog_wan'}, 'Missing path counter readback')
            for deltas in m['path_packet_deltas'].values():
                require(set(deltas) == {'rx', 'tx'} and all(type(v) is int and v > 0 for v in deltas.values()), 'No positive bidirectional path counters')
            if 'iperf' in m:
                transfer = m['iperf'];raw = transfer['json']['end']['sum_received']
                require(raw['bytes'] == transfer['receive_bytes'] and raw['bits_per_second'] / 1e6 == m['receive_mbps'],
                        'iperf raw/cooked rate disagreement')
        result = gates.assess(measurements, checks, aggregate, finished=label == 'health')
        receipts = [e for e in events if e['action'] == 'application_correctness_gate']
        require(len(receipts) == 1, 'Missing or duplicate application-correctness gate receipt')
        keys = ['rule', 'application_eligible', 'original_aggregate', 'original_qualification_passed',
                'network_fidelity', 'failed_numerical_checks']
        require(all(receipts[0][k] == result[k] for k in keys), 'Recorded gate contradicts recomputed qualification')
        if label == 'health':
            expected_status = 'PASSED' if result['original_qualification_passed'] else 'FAILED_ACCEPTANCE'
            require(summary['status'] == expected_status, 'Health terminal status contradicts qualification')
            completion = archive.json(prefix + 'application-gate-completion.json')
            require(all(completion[k] == result[k] for k in keys)
                    and completion['original_status'] == expected_status
                    and type(completion['entry_returncode']) is int and completion['entry_returncode'] == 0,
                    'Health completion receipt contradicts qualification')
        results[label] = result
    # Keep the qualifications separate: a numerical deviation does not erase correct application results.
    fidelity = 'IN_SPEC' if all(r['network_fidelity'] == 'IN_SPEC' for r in results.values()) else 'OUT_OF_SPEC'
    return {'_status': 'PASS' if fidelity == 'IN_SPEC' else 'FAIL',
            'qualifications': results, 'network_fidelity': fidelity,
            'scope': 'Original numerical checks recomputed from saved samples; other acquisition predicates are recorded checks, not a full route/qdisc audit'}


def environment(archive):
    for name, separator in [('python-lock.txt', '=='), ('debian-packages.txt', '\t'),
                            ('endpoint-packages.txt', '\t')]:
        def entries(data):
            rows = [line.split(separator, 1) for line in data.decode().splitlines() if line]
            require(all(len(row) == 2 and all(row) for row in rows)
                    and len({row[0] for row in rows}) == len(rows), 'Invalid package manifest: ' + name)
            return dict(rows)
        expected = entries(read_file(ROOT / 'experiment/tests/runtime-baseline' / name))
        require(entries(archive.data(name)) == expected, 'Runtime dependency drift: ' + name)
    for name in ['initial-resources.json'] + [f'cell-{i:02d}-{when}-resources.json' for i in range(12) for when in ['before', 'after']]:
        resources = archive.json('scheduling/' + name)
        require(set(resources) == set(WORKERS) | {'G'}, 'Missing node resource readback')
        for worker, quota in [('G', 50000), ('E', 25000), ('F', 50000), ('C', 100000)]:
            require(resources[worker]['cpu.max'].strip() == f'{quota} 100000'
                    and int(resources[worker]['memory.max']) == 256*1048576, 'Changed CPU/memory readback: ' + worker)
    return {'scope': 'Saved package manifests and all four-node CPU/memory readbacks; not independent host attestation'}


def cleanup(output, host, archive):
    if not host:
        raise Missing('Missing host summary for cleanup consistency')
    ledger = decode(read_file(output / 'vm-ledger.json'))
    require(ledger == host['vm_ledger'], 'Host/standalone VM ledgers disagree')
    require(not host.get('cleanup_requires_attention') and not host.get('close_error')
            and host['temporary_work_directory_absent'] is True, 'Host cleanup failed or needs attention')
    for key in ['created_by_this_task', 'vm_start_attempted', 'startup_complete', 'instance_directory_absent',
                'recorded_hostagent_pid_absent', 'management_port_closed']:
        require(ledger.get(key) is True, 'VM cleanup missing or false: ' + key)
    require(ledger['state'] == 'deleted' and type(ledger['hostagent_pid']) is int and ledger['hostagent_pid'] > 0
            and type(ledger['management_port']) is int and 1 <= ledger['management_port'] <= 65535,
            'VM deletion/identity not recorded')
    for before, after, ledger_name in [('patched-calibration/docker-inventory-before.json', 'patched-calibration/docker-inventory-after.json', 'patched-calibration/ledger.json'),
                                       ('scheduling/network/docker-inventory-before.json', 'scheduling/docker-inventory-after.json', 'scheduling/network/ledger.json')]:
        a, b = archive.json(before), archive.json(after)
        require(set(a) == set(b) == {'containers', 'networks'}
                and all(set(a[k]) == set(b[k]) for k in a), 'Guest container/network inventory not restored')
        require(archive.json(ledger_name)['cleanup_errors'] == [], 'Guest resource cleanup errors')
    return {'scope': 'Consistency of saved VM and container cleanup records only',
            'independent_live_host_teardown': 'UNVERIFIED'}


def verify(output):
    report = {'schema_version': 1, 'overall': 'UNVERIFIED', 'checks': {},
              'performance_eligibility': {'status': 'UNVERIFIED', 'reason': 'Requires independent full protocol/evidence/preservation and actual-teardown audit; this public checker does not grant publication eligibility.'}}
    archive = None
    host = None
    loaded = None
    def check(name, function):
        try:
            details = function()
            status = details.pop('_status', 'PASS') if isinstance(details, dict) else 'PASS'
            report['checks'][name] = {'status': status, 'details': details or {}}
        except Missing as error:
            report['checks'][name] = {'status': 'UNVERIFIED', 'reason': str(error)}
        except (ValueError, KeyError, TypeError, AttributeError, IndexError, OSError, EOFError, tarfile.TarError) as error:
            report['checks'][name] = {'status': 'FAIL', 'reason': type(error).__name__ + ': ' + str(error)}
    def provenance():
        nonlocal loaded, host
        loaded = contracts()
        pins = loaded[0]
        host = decode(read_file(output / 'host-summary.json'))
        manifest = decode(read_file(output / 'input-sha256.json'))
        omitted = decode(read_file(ROOT / 'experiment/SOURCE.json'))['omitted_non_runtime_context_files']
        require(manifest in (pins, pins | omitted) and host['input_sha256'] == manifest,
                'Captured input manifest differs from the published subset or original 38-file capture')
        for name, expected in manifest.items():
            require(digest(read_file(output / 'inputs' / name)) == expected, 'Captured input bytes changed: ' + name)
        require(host['stage'] == 'calibration', 'Unsupported runner stage')
        return {'pinned_inputs': len(pins), 'captured_inputs': len(manifest), 'host_runner_authenticity': 'UNVERIFIED: runner source is not captured inside its output'}
    check('source_provenance', provenance)
    def export():
        nonlocal archive
        archive = Archive(output / 'guest-evidence.tar.gz')
        if host is None:
            raise Missing('Host summary unavailable for export-hash binding')
        require(not host.get('export_error') and host.get('guest_evidence_sha256') == archive.sha256, 'Export hash mismatch or recorded export failure')
        return {'sha256': archive.sha256, 'regular_files': len(archive.files), 'gzip_crc': 'PASS',
                'scope': 'Content integrity against recorded hash; not an external authenticity signature'}
    check('export_integrity', export)
    if archive is not None and loaded is not None:
        _, core, pilot, gates = loaded
        check('application', lambda: application(archive, core, pilot))
        check('network_fidelity', lambda: network(archive, gates))
        check('recorded_cleanup', lambda: cleanup(output, host or {}, archive))
    else:
        for name in ['application', 'network_fidelity', 'recorded_cleanup']:
            report['checks'][name] = {'status': 'UNVERIFIED', 'reason': 'Readable archive and pinned local contracts required'}
    if archive is not None:
        check('environment', lambda: environment(archive))
    else:
        report['checks']['environment'] = {'status': 'UNVERIFIED', 'reason': 'Readable archive required'}
    def completion():
        if host is None:
            raise Missing('Missing host summary')
        require(host['status'] == 'PASSED' and type(host['proof_returncode']) is int and host['proof_returncode'] == 0
                and type(host['supervisor_returncode']) is int and host['supervisor_returncode'] == 0
                and not host.get('error'), 'Wrapper failed or incomplete')
    check('wrapper_completion', completion)
    if archive is not None:
        archive.close()
    statuses = [v['status'] for v in report['checks'].values()]
    report['overall'] = 'FAIL' if 'FAIL' in statuses else 'UNVERIFIED' if 'UNVERIFIED' in statuses else 'PASS'
    if report['overall'] == 'FAIL':
        report['performance_eligibility'] = {'status': 'FAIL', 'reason': 'At least one required public check failed; no strict performance eligibility.'}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='Original new-results/session-* output directory, not the guest tar alone')
    parser.add_argument('--json', type=Path, help='Write a new machine-readable result file (never overwrite)')
    args = parser.parse_args()
    if args.json and args.json.exists():
        parser.error('--json destination already exists; refusing overwrite')
    report = verify(args.output)
    if args.json:
        with args.json.open('x') as f:
            json.dump(report, f, indent=2, allow_nan=False)
            f.write('\n')
    print('Public offline checks: ' + report['overall'])
    for name, result in report['checks'].items():
        print(f"  {result['status']:10} {name}: {result.get('reason', result.get('details', {}).get('network_fidelity', 'bounded checks completed'))}")
    app = report['checks']['application']
    if app['status'] == 'PASS':
        d = app['details'];print(f"  {d['worker_outputs']} correct outputs; {d['comparison_on_time']}/{d['comparison_offered']} scored tasks on time")
    print('Scientific performance eligibility: ' + report['performance_eligibility']['status'])
    print('Live host teardown / full independent audit: UNVERIFIED')
    return {'PASS': 0, 'FAIL': 1, 'UNVERIFIED': 2}[report['overall']]


if __name__ == '__main__':
    raise SystemExit(main())
