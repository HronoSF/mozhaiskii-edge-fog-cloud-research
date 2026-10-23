"""Unprivileged localhost wiring check. NOT a MADT/network treatment experiment."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import time
import uuid
from .core import CLASSES, WORKERS, Task, trace


def run(output,policy='rr',queue_proof=False):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    # Distinct ephemeral ports; a bind race fails visibly rather than retrying cells.
    sockets=[]
    for i in range(4):
        s=socket.socket();s.bind(('127.0.0.1',0));sockets.append(s)
    ports=[s.getsockname()[1] for s in sockets]
    for s in sockets:s.close()
    tasks=trace(4,200_000_000,0,'burst')
    forced={}
    if queue_proof:
        tasks=tuple(Task(i,800000,1048576) for i in range(12))
        forced={str(i):WORKERS[i//4] for i in range(12)}
    profiles=dict(service={j:{f'{w}:{b}':10_000_000 for w,b in CLASSES} for j in WORKERS},
                  transport={j:{str(b):[0,0,0] for b in (65536,1048576)} for j in WORKERS})
    run_id=uuid.uuid4().hex
    config=dict(run_id=run_id,output=str(output/'source'),kind='local-test',policy=policy,
                tasks=[asdict(t) for t in tasks],forced=forced,profiles=profiles,
                workers={j:'127.0.0.1' for j in WORKERS},bind='127.0.0.1',upload_port=ports[1],
                upload_ports=dict(zip(WORKERS,ports[1:])),event_port=ports[0],warmup_repetitions=0,
                horizon_ns=200_000_000,drain_seconds=15,require_linux_clock=False,
                profile_origin='invented wiring estimates; not scientific calibration')
    (output/'source-config.json').write_text(json.dumps(config,indent=2)+'\n')
    shutil.copytree(Path(__file__).resolve().parent,output/'inputs/madt_scheduling',ignore=shutil.ignore_patterns('__pycache__'))
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(output/'inputs'));processes=[];logs=[]
    try:
        log=(output/'source-console.txt').open('w');logs.append(log)
        source=subprocess.Popen([sys.executable,'-m','madt_scheduling.orchestrator','--config',str(output/'source-config.json')],stdout=log,stderr=subprocess.STDOUT,env=env)
        processes.append(source);deadline=time.monotonic()+30
        while not (output/'source/ready').exists():
            if source.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Source startup failed')
            time.sleep(.02)
        for j,port in zip(WORKERS,ports[1:]):
            cfg=dict(run_id=run_id,worker=j,source='127.0.0.1',bind='127.0.0.1',event_port=ports[0],
                     upload_port=port,output=str(output/j),max_seconds=30)
            path=output/(j+'-config.json');path.write_text(json.dumps(cfg)+'\n')
            log=(output/(j+'-console.txt')).open('w');logs.append(log)
            processes.append(subprocess.Popen([sys.executable,'-m','madt_scheduling.worker','--config',str(path)],stdout=log,stderr=subprocess.STDOUT,env=env))
        source.wait(timeout=30)
        for p in processes[1:]:p.wait(timeout=10)
        codes=[p.returncode for p in processes]
        (output/'process-results.json').write_text(json.dumps(dict(exit_codes=codes,scope='real localhost processes, no quotas, synthetic profiles, no MADT'))+'\n')
        if any(codes):raise RuntimeError('Local processes failed: '+str(codes))
        return json.loads((output/'source/summary.json').read_text())
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        for log in logs:log.close()
        (output/'process-results-final.json').write_text(json.dumps(dict(children=[dict(pid=p.pid,exit_code=p.poll()) for p in processes]))+'\n')
        (output/'cleanup.json').write_text(json.dumps(dict(all_children_reaped=all(p.poll() is not None for p in processes)))+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--policy',choices=('rr','compute_ect','network_ect'),default='rr');p.add_argument('--queue-proof',action='store_true')
    a=p.parse_args();print(json.dumps(run(a.output,a.policy,a.queue_proof),indent=2))

if __name__=='__main__':main()
