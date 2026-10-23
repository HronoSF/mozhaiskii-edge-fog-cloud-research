"""Synthetic fixtures ONLY: invented clocks/network/results, never VM evidence."""
import base64
import copy
from dataclasses import asdict
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_verifier', ROOT/'scripts/verify_session.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def qualification(prefix, gates, low_rate=False):
    paths = [('edge', '10.123.0.3'), ('cloud', '10.123.0.10'), ('edge', '10.123.0.12')]
    measurements = []
    for kind in ['delay', 'rate']:
        for phase in ['baseline', 'impaired', 'restored']:
            pings = []
            for i, (source, destination) in enumerate(paths):
                rtt = 21 if kind == 'delay' and phase == 'impaired' and i < 2 else 1
                pings.append(dict(source=source, destination=destination, exit_code=0,
                                  received=20, transmitted=20, rtt_ms=[rtt]*20, median_ms=rtt))
            row = dict(phase=f'{prefix}-{kind}-00-{phase}', pings=pings,
                       path_packet_deltas={'cloud_host_veth': {'rx': 20, 'tx': 20}, 'fog_wan': {'rx': 20, 'tx': 20}})
            if kind == 'rate':
                rate = (6 if low_rate else 9) if phase == 'impaired' else 30
                row.update(receive_mbps=rate, iperf=dict(raw={'exit_code': 0}, receive_bytes=1000,
                           receive_mbps=rate, json={'end': {'sum_received': {'bytes': 1000, 'bits_per_second': rate*1e6}}}))
            measurements.append(row)
    checks = []
    def check(description, passed, **details):
        checks.append(dict(description=description, passed=passed, **details))
    for kind in ['delay', 'rate']:
        for direction in [0, 1]:
            check('RTT restoration within frozen tolerance', True, kind=kind, baseline_ms=1, restored_ms=1)
            if kind == 'delay':
                check('delay RTT increment within frozen bounds', True, direction=direction, increment_ms=20, bounds_ms=[15, 25])
        check('access-segment control unaffected', True, values_ms=[1, 1, 1])
        if kind == 'rate':
            check('baseline above requested cap', True, mbps=30)
            check('rate-only throughput within frozen bounds', not low_rate, mbps=6 if low_rate else 9)
            check('throughput restores', True, baseline_mbps=30, restored_mbps=30)
    aggregate = 'calibration passes without threshold changes' if prefix == 'calibration' else 'application network calibration unchanged criteria'
    for description in ['expected shaping qdisc readback','numerical netem delay readback in seconds',
                        'numerical HTB rate readback','shaping removed'] + (
                        ['TCP works in both directions before cut','cut path fails in both directions',
                         'path cut leaves control reachable','cut path blocks real TCP without received data',
                         'reverse TCP restored after cut'] if prefix == 'calibration' else
                        ['gateway routes through fog','gateway to cloud alive','gateway cut/control','gateway restored']):
        check(description, True)
    check(aggregate, not low_rate)
    if prefix == 'calibration':
        last = copy.deepcopy(measurements[-1]);last['phase'] = 'path-cut-restored';measurements.append(last)
    # Independently assert the generated fixture satisfies the frozen gate schema.
    gates.assess(measurements, checks, aggregate, finished=prefix == 'calibration')
    return measurements, checks


def build_members(slow=False):
    _, core, pilot, gates = verifier.contracts()
    members = {}
    def save(name, value): members[name] = encoded(value)
    def lines(name, rows): members[name] = b''.join(encoded(row) for row in rows)
    plan = pilot.make_plan()
    save('scheduling/plan.json', plan)
    def cell(name, config):
        config = dict(config, run_id='SYNTHETIC', seed=0, tie_order=list(core.WORKERS), require_linux_clock=True,
                      event_port=41001, upload_port=41000, drain_seconds=60)
        save('scheduling/'+name+'/declared-source-config.json', config)
        jobs = verifier.expected_jobs(config, core)
        rows, events, worker_events = [], [], {w: [] for w in core.WORKERS}
        seq = dict.fromkeys(core.WORKERS, 0);free = dict.fromkeys(core.WORKERS, 0)
        origin = 10_000_000_000
        for index, (task_id, (task, phase, forced)) in enumerate(jobs.items()):
            worker = forced or core.WORKERS[index % 3];seq[worker] += 1
            planned = origin + task['release_ns'] if phase == 'scored' else origin - 1_000_000_000 + index*100000
            row = dict(id=task_id, task=task, phase=phase, forced=forced, outcome='completed',
                       worker=worker, sequence=seq[worker], a_star=planned, a=planned+1000,
                       g=planned+2000, b=planned+3000, c=planned+4000, d=planned+5000, e=planned+6000,
                       f=planned+7000+seq[worker]*2000, cpu_ns=100000, decision_cpu_ns=500)
            row['x'] = max(row['f']+1000, free[worker])
            duration = 2_000_000_000 if slow and name == 'cell-00' and task_id == 11 else 1_000_000
            row['y'] = row['x'] + duration;free[worker] = row['y']
            row['z'] = row['y']+1000;row['on_time'] = row['z'] <= planned+1_000_000_000
            row['ack_receipt'] = row['f']+500
            row['components_ns'] = list(core.timing_components(row))
            h, value = verifier.reference(task_id, task['iterations'], task['size'], task['seed'])
            row['payload_hash'] = h
            msg = {k: row[k] for k in ['id','worker','sequence','payload_hash','f','x','y','cpu_ns']}
            msg.update(run_id='SYNTHETIC',value=base64.b64encode(value).decode())
            events.append(dict(event='release',id=task_id,a_star=row['a_star'],a=row['a'],phase=phase))
            events.append(dict(event='placement',id=task_id,worker=worker,snapshot_time=row['b'],d=row['d']))
            events.append(dict(event='validated_result', id=task_id, worker=worker, z=row['z'], message=msg))
            worker_events[worker].extend([dict(event='input_admitted',worker=worker,id=task_id,f=row['f'],sequence=row['sequence']),
                                          dict(event='execution_ended',worker=worker,id=task_id,x=row['x'],y=row['y'],cpu_ns=row['cpu_ns'])])
            rows.append(row)
        clock=dict(boot='SYNTHETIC-BOOT-NOT-A-VM',time_namespace='time:[synthetic]',offsets='monotonic 0 0\nboottime 0 0')
        events.append(dict(event='scored_start',start=origin))
        for w in core.WORKERS:
            events.append(dict(event='worker_hello',worker=w,source_clock=clock,hello={'clock':clock}))
            for i in range(5):events.append(dict(event='clock_validated',worker=w,start=1,receipt=4,reply=dict(probe=i,received=2,sent=3)))
        counts={k:sum(r['phase']=='scored' and r['outcome']==k for r in rows) for k in verifier.OUTCOMES}
        summary=dict(status='RUN_FINISHED',errors=[],kind=config['kind'],policy=config['policy'],offered=len(config['tasks']),
                     outcomes=counts,on_time=sum(r['phase']=='scored' and r['on_time'] for r in rows),start=origin,profiles=config['profiles'])
        base='scheduling/'+name+'/'
        save(base+'source/tasks.json',rows);save(base+'source/summary.json',summary);lines(base+'source/events.jsonl',events)
        save(base+'exec-status.json',{'statuses':{w:dict(Running=False,ExitCode=0) for w in (*core.WORKERS,'source')}})
        for w in core.WORKERS:
            save(base+w+'/summary.json',dict(errors=[],remaining=0,censored_shutdown=False))
            lines(base+w+'/events.jsonl',worker_events[w])
        return rows,summary
    calibrations={}
    for index, network in enumerate(['unshaped','delay20']):
        tasks=[asdict(core.Task(2**62+index*100+i,w,b)) for i,(_,w,b,_) in enumerate((j,w,b,r) for j in core.WORKERS for w,b in core.CLASSES for r in range(3))]
        cfg=dict(kind='calibration',policy='rr',tasks=tasks,forced={str(t['id']):core.WORKERS[i//12] for i,t in enumerate(tasks)},
                 warmup_repetitions=0,horizon_ns=0,profiles=pilot.blank_profiles())
        calibrations[network],_=cell('calibration-'+network,cfg)
    profiles=pilot.freeze_profiles(calibrations)
    save('scheduling/frozen-profiles.json',profiles)
    save('scheduling/freeze.json',dict(profiles_sha256=verifier.digest(members['scheduling/frozen-profiles.json']),plan_sha256=verifier.digest(members['scheduling/plan.json'])))
    cell('queue-proof',dict(kind='queue-proof',policy='rr',tasks=[asdict(core.Task(i,800000,1048576)) for i in range(12)],
                          forced={str(i):core.WORKERS[i//4] for i in range(12)},warmup_repetitions=0,horizon_ns=0,profiles=profiles['unshaped']))
    cells=[]
    for i,c in enumerate(plan['cells']):
        _,summary=cell(f'cell-{i:02d}',dict(kind='comparison',policy=c['policy'],tasks=plan['traces'][c['scenario']],forced={},
                                         warmup_repetitions=5,horizon_ns=6_000_000_000,profiles=profiles[c['network']]))
        cells.append(dict(c,status='COMPLETED',analysis=dict(instrument_checks='PASSED',offered=12,outcomes=summary['outcomes'],on_time=summary['on_time'])))
    save('scheduling/state.json',dict(status='CORRECTNESS_PILOT_COMPLETED',cells=cells))
    for prefix,kind in [('patched-calibration/','calibration'),('scheduling/network/','application-qualification')]:
        measures,checks=qualification(kind,gates)
        save(prefix+'measurements.json',measures)
        lines(prefix+'events.jsonl',[dict(action='acceptance_check',**c) for c in checks])
        save(prefix+'ledger.json',{'cleanup_errors':[]})
        save(prefix+'docker-inventory-before.json',{'containers':[],'networks':['SYNTHETIC-DEFAULT']})
        after=prefix+'docker-inventory-after.json' if kind=='calibration' else 'scheduling/docker-inventory-after.json'
        save(after,{'containers':[],'networks':['SYNTHETIC-DEFAULT']})
        if kind=='calibration':save(prefix+'summary.json',dict(failure=None,cleanup_errors=[],checks=checks))
    for name in ['python-lock.txt','debian-packages.txt','endpoint-packages.txt']:
        members[name]=(ROOT/'experiment/tests/runtime-baseline'/name).read_bytes()
    resources={w:{'cpu.max':f'{q} 100000\n','memory.max':str(256*1048576)} for w,q in [('G',50000),('E',25000),('F',50000),('C',100000)]}
    for n in ['initial-resources.json']+[f'cell-{i:02d}-{when}-resources.json' for i in range(12) for when in ['before','after']]:save('scheduling/'+n,resources)
    return members


def write_fixture(output, members):
    """Create schema-valid invented evidence, not a historical-data projection."""
    output.mkdir()
    pins=json.loads((ROOT/'experiment/INPUTS.sha256.json').read_text())
    for name in pins:
        target=output/'inputs'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'experiment'/name,target)
    (output/'input-sha256.json').write_bytes(encoded(pins))
    ledger=dict(state='deleted',created_by_this_task=True,vm_start_attempted=True,startup_complete=True,
                instance_directory_absent=True,recorded_hostagent_pid_absent=True,management_port_closed=True,hostagent_pid=123,management_port=4567)
    (output/'vm-ledger.json').write_bytes(encoded(ledger))
    with tarfile.open(output/'guest-evidence.tar.gz','w:gz') as tar:
        for name,data in members.items():
            info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
    host=dict(status='PASSED',stage='calibration',proof_returncode=0,supervisor_returncode=0,temporary_work_directory_absent=True,
              input_sha256=pins,vm_ledger=ledger,guest_evidence_sha256=verifier.digest((output/'guest-evidence.tar.gz').read_bytes()))
    (output/'host-summary.json').write_bytes(encoded(host))
