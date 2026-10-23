#!/usr/bin/env python3
"""Characterize timing without changing the frozen acceptance experiment."""
import argparse
import json
import os
from pathlib import Path
import random
import signal
import statistics
import sys
import time
import traceback
from types import SimpleNamespace
import guest_experiment as original


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    # Match the original CLI: absolute venv Python does not activate tcset.
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    schedule=['madt']*5+['direct_netem']*5
    random.Random(20261019).shuffle(schedule)
    config={'stage':'TIMING_DIAGNOSTIC','seed':20261019,'order':schedule,
        'delay_ms':20,'repetitions_per_mode':5,'ping_count':20,
        'purpose':'Layer isolation; not frozen acceptance or a successful full-trial claim'}
    original.signal.signal(signal.SIGALRM,lambda *a:(_ for _ in ()).throw(TimeoutError('Timing diagnostic deadline')))
    signal.alarm(700)
    e=original.Experiment(SimpleNamespace(output=args.output,source=Path('/opt/ehu-madt/madt'),image=args.image,stage='diagnostic'))
    e.ev.save('diagnostic-plan-before-data.json',config)
    result={'status':'FAILED','plan':config,'cycles':[]}
    try:
        e.preflight();e.start()
        environment={}
        for name,path in {
            'clocksource':'/sys/devices/system/clocksource/clocksource0/current_clocksource',
            'cpu_pressure':'/proc/pressure/cpu','timer_migration':'/proc/sys/kernel/timer_migration',
            'kernel_config':'/boot/config-'+e.ev.command(['uname','-r']).stdout.strip()}.items():
            file=Path(path)
            if file.exists():environment[name]=file.read_text()
        sleep=[]
        for _ in range(100):
            start=time.monotonic_ns();time.sleep(.020)
            sleep.append((time.monotonic_ns()-start)/1e6)
        environment['monotonic_clock']=vars(time.get_clock_info('monotonic'))
        environment['requested_20ms_sleep_actual_ms']=sleep
        e.ev.save('timing-environment.json',environment)
        for index,mode in enumerate(schedule):
            prefix=f'diagnostic-{index:02d}-{mode}'
            before=e.phase(prefix+'-baseline')
            if mode=='madt':e.shape('delay')
            else:
                e.ev.command(['tc','qdisc','add','dev',e.cloud_veth,'root','netem','delay','20ms'])
                rule=e.snapshot(prefix+'-direct-rule')
                netems=[q for q in rule['host_tc']['qdisc'] if q.get('kind')=='netem']
                e.require('direct diagnostic rule reads back20ms',len(netems)==1 and
                    abs(netems[0]['options']['delay']['delay']-.020)<1e-6)
            try:impaired=e.phase(prefix+'-impaired')
            finally:e.restore()
            after=e.phase(prefix+'-restored')
            row={'mode':mode,'index':index,
                'increment_ms':[impaired['pings'][i]['median_ms']-before['pings'][i]['median_ms'] for i in [0,1]],
                'impaired_medians_ms':[q['median_ms'] for q in impaired['pings']],
                'restore_delta_ms':[after['pings'][i]['median_ms']-before['pings'][i]['median_ms'] for i in [0,1]]}
            result['cycles'].append(row);e.ev.save('diagnostic-results.json',result)
        result['status']='DIAGNOSTIC_COMPLETED' if all(c['passed'] for c in e.checks) else 'FAILED'
    except BaseException as error:
        result['failure']={'error':repr(error),'traceback':traceback.format_exc()}
    finally:
        signal.alarm(0)
        try:e.cleanup_resources()
        except BaseException as error:result['cleanup_failure']=repr(error);result['status']='FAILED'
        if e.collections:
            cc,nc,old_cc,old_nc=e.collections;cc.create,nc.create=old_cc,old_nc
        if e.socket:e.socket.close()
        if e.context:e.context.term()
        if e.client:
            after={'containers':[c.id for c in e.client.containers.list(all=True)],
                   'networks':[n.id for n in e.client.networks.list()]}
            e.ev.save('docker-inventory-after.json',after)
            before_file=e.ev.output/'docker-inventory-before.json'
            if before_file.exists():
                before=json.loads(before_file.read_text())
                result['inventory_restored']=all(set(after[k])==set(before[k]) for k in before)
                if not result['inventory_restored']:result['status']='FAILED'
            e.client.close()
        if e.ledger['cleanup_errors']:result['status']='FAILED'
        result['cleanup_errors']=e.ledger['cleanup_errors']
        e.ev.save('diagnostic-results.json',result);e.ev.events.close()
    print(json.dumps(result))
    return 0 if result['status']=='DIAGNOSTIC_COMPLETED' else 1


if __name__=='__main__':raise SystemExit(main())
