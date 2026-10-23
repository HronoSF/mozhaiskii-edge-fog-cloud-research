#!/usr/bin/env python3
"""Guest-only application adapter over unchanged MADT experiment primitives."""
import argparse
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import sys
import tarfile
import time
import traceback
import uuid

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from madt_scheduling.core import Task, WORKERS, CLASSES, trace
from madt_scheduling.analyze import inspect


def make_plan():
    cells=[dict(policy=p,scenario=s,network=n) for p in ('rr','compute_ect','network_ect')
           for s in ('steady','burst') for n in ('unshaped','delay20')]
    cells.sort(key=lambda c:(hashlib.sha256(('ehu-pilot-order-v1|'+c['policy']+'|'+c['scenario']+'|'+c['network']).encode()).hexdigest(),json.dumps(c,sort_keys=True)))
    return dict(version=1,seed=0,n=12,horizon_ns=6_000_000_000,drain_seconds=60,
                calibration_repeats=3,warmup_repetitions=5,tie_order=list(WORKERS),cells=cells,
                traces={s:[asdict(t) for t in trace(12,6_000_000_000,0,s)] for s in ('steady','burst')})


def save(path,value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')


def blank_profiles():
    return dict(service={j:{f'{w}:{b}':1 for w,b in CLASSES} for j in WORKERS},
                transport={j:{str(b):[0,0,0] for b in (65536,1048576)} for j in WORKERS})


def mean(values):
    if not values or any(v<0 for v in values):raise ValueError('Invalid calibration values')
    return (sum(values)+len(values)-1)//len(values)


def freeze_profiles(calibrations):
    service={j:{} for j in WORKERS};transports={n:{j:{} for j in WORKERS} for n in calibrations}
    for j in WORKERS:
        for w,b in CLASSES:
            rows=[r for r in calibrations['unshaped'] if r['worker']==j and (r['task']['iterations'],r['task']['size'])==(w,b)]
            if len(rows)!=3:raise ValueError('Missing service calibration samples')
            service[j][f'{w}:{b}']=mean([r['y']-r['x'] for r in rows])
        for network,all_rows in calibrations.items():
            for b in (65536,1048576):
                rows=[r for r in all_rows if r['worker']==j and r['task']['size']==b]
                if len(rows)!=6:raise ValueError('Missing size-conditioned calibration')
                transports[network][j][str(b)]=[mean([r['f']-r['e'] for r in rows]),
                    mean([r['ack_receipt']-r['f'] for r in rows]),mean([r['z']-r['y'] for r in rows])]
    return {n:dict(service=service,transport=t) for n,t in transports.items()}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--plan-only',action='store_true');parser.add_argument('--health-failed',action='store_true')
    a=parser.parse_args();out=a.output;plan=make_plan()
    if a.plan_only:
        out.mkdir(parents=True,exist_ok=False);save(out/'plan.json',plan)
        save(out/'state.json',dict(status='NOT_STARTED',cells=[dict(**c,status='NOT_EXECUTED') for c in plan['cells']]))
        return 0
    if a.health_failed:
        state=json.loads((out/'state.json').read_text());state['status']='BLOCKED_PRIOR_HEALTH';save(out/'state.json',state);return 0
    if json.loads((out/'plan.json').read_text())!=plan or json.loads((out/'state.json').read_text())['status']!='NOT_STARTED':
        raise RuntimeError('Plan changed or this attempt already started')
    sys.path.insert(0,'/tmp/ehu-inputs')
    from guest_experiment import Experiment, LABEL
    from types import SimpleNamespace

    class AppExperiment(Experiment):
        def instrument_resource_creation(self):
            super().instrument_resource_creation()
            from docker.models.containers import ContainerCollection
            original=ContainerCollection.create
            quotas={'edge':25000,'fog':50000,'cloud':100000,'control':50000}
            def create(collection,*args,**kwargs):
                name=kwargs.get('name');role=next((r for r,n in self.names.items() if n==name),None)
                if role is None:raise RuntimeError('Unexpected application container')
                kwargs.pop('nano_cpus',None);kwargs.update(cpu_period=100000,cpu_quota=quotas[role])
                return original(collection,*args,**kwargs)
            ContainerCollection.create=create

    state=json.loads((out/'state.json').read_text());state['status']='STARTED';save(out/'state.json',state)
    args=SimpleNamespace(output=out/'network',source=Path('/opt/ehu-madt/madt'),
                         image=Path('/opt/ehu-madt/endpoint-id.txt').read_text().strip(),stage='calibration')
    # Importing Experiment bypasses its CLI main() environment initialization.
    os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH','')
    exp=AppExperiment(args);failure=None;profiles=None
    def stage(value):
        state['stage']=value;save(out/'state.json',state)
    def resources(tag):
        script="import json,pathlib;print(json.dumps({n:pathlib.Path('/sys/fs/cgroup/'+n).read_text() for n in ['cpu.max','cpu.stat','memory.max','memory.current','memory.peak']}))"
        data={j:json.loads(exp.exec(node,['python3','-c',script])['stdout']) for j,node in zip(WORKERS,('edge','fog','cloud'))}
        data['G']=json.loads(exp.exec('control',['python3','-c',script])['stdout'])
        save(out/(tag+'-resources.json'),data);return data
    def configure(network):
        current=json.loads(exp.ev.command(['tc','-j','qdisc','show','dev',exp.cloud_veth]).stdout)
        if any(q.get('kind') in ('htb','tbf','netem') for q in current):exp.restore()
        if network=='delay20':exp.shape('delay')
        elif network!='unshaped':raise ValueError('Unknown network condition')
        exp.snapshot('application-'+network)
    def install():
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w') as tar:
            tar.add(HERE/'madt_scheduling',arcname='madt_scheduling',filter=lambda t:None if '__pycache__' in t.name else t)
        archive=stream.getvalue()
        save(out/'application-input-hashes.json',{str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((HERE/'madt_scheduling').rglob('*.py'))})
        for node,c in exp.containers.items():
            exp.exec(node,['mkdir','-p','/opt/ehu-scheduling'])
            if not c.put_archive('/opt/ehu-scheduling',archive):raise RuntimeError('Application copy failed')
    def execute_cell(name,kind,network,tasks,forced,policy='rr',warmup=0,horizon=0):
        cell=out/name;cell.mkdir(parents=True,exist_ok=False);token=uuid.uuid4().hex
        base='/tmp/ehu-pilot-'+token
        config=dict(run_id=token,kind=kind,policy=policy,seed=0,tasks=[asdict(t) for t in tasks],forced=forced,
                    profiles=profiles[network] if profiles else blank_profiles(),workers=dict(zip(WORKERS,[exp.addresses['edge'],exp.addresses['fog_access'],exp.addresses['cloud']])),
                    upload_port=41000,event_port=41001,warmup_repetitions=warmup,horizon_ns=horizon,
                    drain_seconds=60,require_linux_clock=True,output=base+'/source',tie_order=list(WORKERS))
        save(cell/'declared-source-config.json',config)
        executions={}
        for role,node in [('source','control'),('E','edge'),('F','fog'),('C','cloud')]:
            cfg=config if role=='source' else dict(run_id=token,worker=role,source=exp.addresses['control'],
                event_port=41001,upload_port=41000,output=base+'/'+role,max_seconds=120)
            stream=io.BytesIO();blob=(json.dumps(cfg)+'\n').encode()
            with tarfile.open(fileobj=stream,mode='w') as tar:
                item=tarfile.TarInfo(role+'-config.json');item.size=len(blob);tar.addfile(item,io.BytesIO(blob))
            exp.exec(node,['mkdir',base]);exp.containers[node].put_archive(base,stream.getvalue())
            module='orchestrator' if role=='source' else 'worker'
            command=f'exec env PYTHONPATH=/opt/ehu-scheduling PYTHONDONTWRITEBYTECODE=1 python3 -m madt_scheduling.{module} --config {base}/{role}-config.json > {base}/{role}-console.txt 2>&1'
            created=exp.client.api.exec_create(exp.containers[node].id,['sh','-c',command])
            executions[role]=dict(node=node,exec_id=created['Id'],command=command)
            exp.client.api.exec_start(created['Id'],detach=True)
        deadline=time.monotonic()+150
        try:
            while True:
                observed={r:exp.client.api.exec_inspect(e['exec_id']) for r,e in executions.items()}
                if all(not e['Running'] for e in observed.values()):break
                if time.monotonic()>deadline:raise TimeoutError('Application cell exceeded 150s; no retry')
                time.sleep(.2)
        finally:
            statuses={r:exp.client.api.exec_inspect(e['exec_id']) for r,e in executions.items()}
            save(cell/'exec-status.json',dict(executions=executions,statuses=statuses))
            for role,execution in executions.items():
                try:
                    bits,stat=exp.containers[execution['node']].get_archive(base)
                    data=b''.join(bits)
                    # Unique token directory; Docker tar names and paths are data-filtered.
                    with tarfile.open(fileobj=io.BytesIO(data)) as tar:tar.extractall(cell,filter='data')
                    extracted=cell/Path(base).name
                    for p in list(extracted.iterdir()):
                        target=cell/p.name
                        if target.exists():raise RuntimeError('Archive output collision')
                        p.rename(target)
                    extracted.rmdir()
                except Exception as error:save(cell/(role+'-export-error.json'),dict(error=repr(error)))
        if any(e['Running'] or e['ExitCode']!=0 for e in statuses.values()):raise RuntimeError('Application process failed; see cell exits/console')
        result=inspect(cell);save(cell/'analysis.json',result)
        if result['instrument_checks']!='PASSED':raise RuntimeError('Application invariant failed')
        if result['outcomes']['completed']!=len(tasks):raise RuntimeError('Tiny correctness pilot incomplete; all outcomes retained')
        return json.loads((cell/'source/tasks.json').read_text()),result

    try:
        stage('application-network-qualification');exp.preflight();exp.start()
        exp.cycles('application-qualification',1)
        exp.require('application network calibration unchanged criteria',all(c['passed'] for c in exp.checks))
        # Actual gateway path, not merely old edge-role route labels.
        route=json.loads(exp.exec('control',['ip','-j','route','get',exp.addresses['cloud']])['stdout'])
        exp.require('gateway routes through fog',route[0].get('gateway')==exp.addresses['fog_access'],route=route)
        exp.require('gateway to cloud alive',exp.ping('control',exp.addresses['cloud'],5)['received']==5)
        exp.exec('fog',['ip','link','set','dev',exp.fog_wan_if,'down'])
        try:
            cut=exp.ping('control',exp.addresses['cloud'],3,4);control=exp.ping('control',exp.addresses['edge'],5)
            exp.require('gateway cut/control',cut['received']==0 and control['received']==5,cut=cut,control=control)
        finally:exp.exec('fog',['ip','link','set','dev',exp.fog_wan_if,'up'])
        exp.require('gateway restored',exp.ping('control',exp.addresses['cloud'],5)['received']==5)
        initial=resources('initial')
        for j,quota in [('E',25000),('F',50000),('C',100000),('G',50000)]:
            exp.require('exact application quota',initial[j]['cpu.max'].strip()==f'{quota} 100000',worker=j,actual=initial[j])
            exp.require('exact memory cap',int(initial[j]['memory.max'])==256*1048576,worker=j)
        install();calibrations={}
        for index,network in enumerate(('unshaped','delay20')):
            configure(network);stage('calibration-'+network)
            task_list=tuple(Task(2**62+index*100+i,w,b) for i,(j,w,b,r) in enumerate((j,w,b,r) for j in WORKERS for w,b in CLASSES for r in range(3)))
            forced={str(t.id):WORKERS[i//12] for i,t in enumerate(task_list)}
            rows,_=execute_cell('calibration-'+network,'calibration',network,task_list,forced)
            calibrations[network]=[r for r in rows if r['phase']=='scored']
        profiles=freeze_profiles(calibrations);save(out/'frozen-profiles.json',profiles)
        save(out/'freeze.json',dict(at=time.monotonic_ns(),profiles_sha256=hashlib.sha256((out/'frozen-profiles.json').read_bytes()).hexdigest(),
                                   plan_sha256=hashlib.sha256((out/'plan.json').read_bytes()).hexdigest(),samples='all calibration samples, no evaluation refitting'))
        stage('queue-proof');configure('unshaped')
        queue_tasks=tuple(Task(i,800000,1048576) for i in range(12))
        _,proof=execute_cell('queue-proof','queue-proof','unshaped',queue_tasks,{str(i):WORKERS[i//4] for i in range(12)})
        exp.require('actual local queue while upload continues',any(proof['actual_local_queue_while_uploading'].values()),proof=proof)
        for index,cell in enumerate(plan['cells']):
            state['cells'][index]['status']='STARTED';stage('comparison-'+str(index));configure(cell['network'])
            resources(f'cell-{index:02d}-before');exp.snapshot(f'cell-{index:02d}-before')
            _,result=execute_cell(f'cell-{index:02d}','comparison',cell['network'],
                tuple(Task(**t) for t in plan['traces'][cell['scenario']]),{},cell['policy'],5,plan['horizon_ns'])
            resources(f'cell-{index:02d}-after');exp.snapshot(f'cell-{index:02d}-after')
            state['cells'][index].update(status='COMPLETED',analysis=result);save(out/'state.json',state)
        state['status']='CORRECTNESS_PILOT_COMPLETED'
    except BaseException as error:
        failure=dict(error=repr(error),traceback=traceback.format_exc());state['status']='FAILED_OR_BLOCKED';state['failure']=failure
        for cell in state['cells']:
            if cell['status']=='STARTED':cell['status']='FAILED'
        print(failure['traceback'],file=sys.stderr)
    finally:
        try:
            exp.cleanup_resources()
            if exp.collections:
                cc,nc,oldcc,oldnc=exp.collections;cc.create,nc.create=oldcc,oldnc
            if exp.socket:exp.socket.close()
            if exp.context:exp.context.term()
            if exp.client:
                before=json.loads((exp.ev.output/'docker-inventory-before.json').read_text())
                after=dict(containers=[c.id for c in exp.client.containers.list(all=True)],networks=[n.id for n in exp.client.networks.list()])
                save(out/'docker-inventory-after.json',after)
                if any(set(before[k])!=set(after[k]) for k in before):raise RuntimeError('Guest inventory not restored')
                exp.client.close()
            if exp.ledger['cleanup_errors']:raise RuntimeError(exp.ledger['cleanup_errors'])
        except BaseException as error:
            state['cleanup_error']=repr(error);state['status']='FAILED_OR_BLOCKED'
        save(out/'state.json',state);exp.ev.events.close()
    return 0 if state['status']=='CORRECTNESS_PILOT_COMPLETED' else 1

if __name__=='__main__':raise SystemExit(main())
