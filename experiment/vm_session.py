#!/usr/bin/env python3
"""Single-use Lima VM with fatal guest timeouts and independent scoped cleanup.

Use EHU_MADT_RUN_ROOT for a task-owned directory containing vm.yaml, and
EHU_LIMA_BINARY for a portable limactl. Host sharing is configured off in vm.yaml.
Only exact guest commands/copies from JSON stdin are accepted. Logs preserve
failures; stop and delete remain independent if logging or stdout fails.
"""
import errno
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(os.environ.get('EHU_MADT_RUN_ROOT', '/tmp/ehu-madt-phaseb-20261019')).resolve()
LIMA = Path(os.environ.get('EHU_LIMA_BINARY', str(ROOT/'lima-dist/bin/limactl'))).resolve()
INSTANCE = 'ehu-madt-20261019'
ENV = dict(os.environ, LIMA_HOME=str(ROOT/'lima-home'))
LOGS = ROOT/'logs'
LEDGER = ROOT/'vm-ledger.json'
counter = 0


def emit(value):
    try:
        print(json.dumps(value) if not isinstance(value, str) else value, flush=True)
    except (BrokenPipeError, OSError):
        # A closed terminal/pipe cannot prevent VM removal.
        sys.stdout = open(os.devnull, 'w')


def record(event, optional=False):
    try:
        with (LOGS/'host-events.jsonl').open('a') as f:
            f.write(json.dumps(dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                monotonic_ns=time.monotonic_ns(),**event))+'\n')
    except OSError:
        if not optional:
            raise


def run(args, timeout=900, cleanup=False):
    global counter
    counter += 1
    path = LOGS/f'{counter:03d}.txt'
    args = [str(x) for x in args]
    record({'phase':'begin','args':args,'output':str(path)},optional=cleanup)
    try:
        out = path.open('wb')
    except OSError:
        if not cleanup:
            raise
        out = open(os.devnull,'wb')
    timed_out = False
    with out:
        try:
            rc = subprocess.run(args,env=ENV,stdout=out,stderr=subprocess.STDOUT,
                                timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            rc,timed_out = 124,True
    record({'phase':'end','returncode':rc,'output':str(path)},optional=cleanup)
    try:
        tail = path.read_text(errors='replace')[-2500:]
    except OSError:
        tail = 'Output unavailable; cleanup command was still attempted'
    emit({'returncode':rc,'log':str(path),'tail':tail})
    if timed_out and not cleanup:
        # Killing local SSH cannot prove the guest command stopped. Delete guest.
        raise TimeoutError('Command timed out; refusing further guest commands')
    return rc


def interrupt(signum,frame):
    raise KeyboardInterrupt(f'signal {signum}')


def write_ledger(ledger,optional=False):
    try:
        LEDGER.write_text(json.dumps(ledger,indent=2)+'\n')
    except OSError:
        if not optional:
            raise


def capture_identity(home,ledger):
    directory=home/INSTANCE
    pidfile=directory/'ha.pid'
    if pidfile.exists():
        pid=int(pidfile.read_text().strip())
        if pid<=0:
            raise ValueError('Invalid host-agent PID')
        ledger['hostagent_pid']=pid
    sshconfig=directory/'ssh.config'
    if sshconfig.exists():
        match=re.search(r'^\s*Port\s+(\d+)\s*$',sshconfig.read_text(),re.M)
        if match:
            port=int(match[1])
            if not 1<=port<=65535:
                raise ValueError('Invalid management port')
            ledger['management_port']=port


def verify_absent(home,ledger):
    directory_absent=not (home/INSTANCE).exists()
    pid=ledger.get('hostagent_pid')
    pid_absent=None
    if pid:
        try:
            os.kill(pid,0)
            pid_absent=False
        except OSError as e:
            if e.errno==errno.ESRCH:
                pid_absent=True
            elif e.errno==errno.EPERM:
                pid_absent=False
    port=ledger.get('management_port')
    port_closed=None
    if port:
        try:
            with socket.socket() as s:
                s.settimeout(0.5)
                result=s.connect_ex(('127.0.0.1',port))
            if result==errno.ECONNREFUSED:
                port_closed=True
            elif result==0:
                port_closed=False
        except OSError:
            # Timeout, permission and other socket errors cannot prove closure.
            pass
    return {'instance_directory_absent':directory_absent,
            'recorded_hostagent_pid_absent':pid_absent,
            'management_port_closed':port_closed}


def cleanup(home,ledger):
    for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT):
        signal.signal(sig,signal.SIG_IGN)
    record({'phase':'cleanup_begin','instance':INSTANCE},optional=True)
    try:
        capture_identity(home,ledger)
    except Exception as e:
        ledger.setdefault('cleanup_diagnostics',[]).append('identity: '+repr(e))
    # Each operation survives failure in any previous command/log/print.
    for args in ([LIMA,'stop','--tty=false',INSTANCE],
                 [LIMA,'delete','--tty=false','--force',INSTANCE]):
        if not (home/INSTANCE).exists():
            break
        try:
            run(args,90,cleanup=True)
        except BaseException as e:
            ledger.setdefault('cleanup_diagnostics',[]).append(repr(e))
    for _ in range(20):
        verification=verify_absent(home,ledger)
        if all(v is True for v in verification.values()):
            break
        if not ledger['vm_start_attempted'] and verification['instance_directory_absent']:
            break
        time.sleep(0.2)
    ledger.update(verification)
    if not ledger['vm_start_attempted'] and verification['instance_directory_absent']:
        # Validation failed before a start was dispatched; this is not proof
        # of terminating a running guest, and PID/port checks remain unknown.
        ledger['state']='not_created'
    elif all(v is True for v in verification.values()):
        ledger['state']='deleted'
    elif any(v is False for v in verification.values()):
        ledger['state']='cleanup_failed'
    else:
        ledger['state']='cleanup_inconclusive'
    write_ledger(ledger,optional=True)
    record({'phase':'cleanup_end',**ledger},optional=True)
    emit({'cleanup':ledger})
    if ledger['state'] not in ('deleted','not_created'):
        raise RuntimeError('VM cleanup incomplete or inconclusive; inspect exact ledger identities')


def main():
    LOGS.mkdir(exist_ok=True)
    home=Path(ENV['LIMA_HOME'])
    home.mkdir(exist_ok=True,mode=0o700)
    if (home/INSTANCE).exists():
        raise RuntimeError('Refusing to reuse an existing instance')
    ledger={'instance':INSTANCE,'lima_home':str(home),'vm_config':str(ROOT/'vm.yaml'),
            'created_by_this_task':True,'state':'planned',
            'vm_start_attempted':False,'startup_complete':False}
    write_ledger(ledger)
    for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT):
        signal.signal(sig,interrupt)
    try:
        if run([LIMA,'validate',ROOT/'vm.yaml'],30):
            raise RuntimeError('Configuration validation failed')
        ledger['state']='starting'
        # Write ahead of dispatch: if interrupted, assume startup may have run.
        ledger['vm_start_attempted']=True
        write_ledger(ledger)
        if run([LIMA,'start','--tty=false','--timeout=10m','--name='+INSTANCE,ROOT/'vm.yaml'],660):
            raise RuntimeError('VM startup failed; retained logs')
        ledger['startup_complete']=True
        capture_identity(home,ledger)
        if not all(ledger.get(k) for k in ('hostagent_pid','management_port')):
            raise RuntimeError('Startup completed without verifiable host-agent/port identities')
        ledger['state']='running'
        write_ledger(ledger)
        run([LIMA,'list','--json'],30)
        emit('VM_READY: guest(args,timeout), copy(source,destination), close')
        while True:
            if not select.select([sys.stdin],[],[],900)[0]:
                raise TimeoutError('15-minute idle lease expired')
            line=sys.stdin.readline()
            if not line:
                break
            command=json.loads(line)
            if command['action']=='close':
                break
            if command['action']=='guest':
                run([LIMA,'shell','--workdir=/tmp',INSTANCE,'--',*command['args']],
                    min(int(command.get('timeout',900)),1200))
            elif command['action']=='copy':
                run([LIMA,'copy',command['source'],command['destination']],300)
            else:
                raise ValueError('Unknown action')
    finally:
        cleanup(home,ledger)


if __name__=='__main__':
    main()
