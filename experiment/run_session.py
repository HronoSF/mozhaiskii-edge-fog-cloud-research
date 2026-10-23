#!/usr/bin/env python3
"""Run the pinned MADT repair proof from macOS; export evidence and delete its VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.request import urlopen

HERE=Path(__file__).resolve().parent
ASSETS={
 'lima.tar.gz':('https://github.com/lima-vm/lima/releases/download/v2.2.1/lima-2.2.1-Darwin-arm64.tar.gz','9e9eacce88f37e185c346bad73aa6136f738d8cdf8c3bb23cd42b071824bc66e'),
 'ubuntu-arm64.img':('https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-arm64.img','1d6bffe64b848468ac97f821d369a4846d983de1800ccf6b5ec8853e85cefc55')}


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def interrupted(signum,frame):raise KeyboardInterrupt(f'Signal {signum}')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True,help='New evidence directory; never overwritten')
    ap.add_argument('--assets-dir',type=Path,help='Optional already downloaded assets; still hash checked')
    ap.add_argument('--stage',choices=['calibration','full','timing'],default='full')
    args=ap.parse_args()
    if platform.system()!='Darwin' or platform.machine()!='arm64':
        raise RuntimeError('This entrypoint supports macOS ARM64 only')
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    root=Path(tempfile.mkdtemp(prefix='ehu-madt-repair-run-',dir='/tmp')).resolve()
    (root/'.owned-by-madt-runner').write_text(str(output))
    state={'status':'FAILED','start_ns':time.time_ns(),'work_directory':str(root),'stage':args.stage}
    proc=None
    ready=False
    extracted=False
    stream=None
    reader=None
    events=queue.Queue()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,interrupted)

    def consume():
        try:
            for line in proc.stdout:
                stream.write(line);stream.flush()
                try:value=json.loads(line)
                except json.JSONDecodeError:value=line.strip()
                events.put(value)
        finally:events.put(None)

    def receive(predicate,timeout):
        deadline=time.monotonic()+timeout
        while True:
            value=events.get(timeout=max(.01,deadline-time.monotonic()))
            if value is None:raise RuntimeError('VM supervisor closed its output')
            if predicate(value):return value
            if time.monotonic()>deadline:raise TimeoutError('Supervisor response deadline')

    def command(item,*,allow_failure=False):
        proc.stdin.write(json.dumps(item)+'\n');proc.stdin.flush()
        response=receive(lambda r:isinstance(r,dict) and 'returncode' in r,int(item.get('timeout',300))+60)
        if response['returncode'] and not allow_failure:
            raise RuntimeError('Guest action failed: '+json.dumps(response))
        return response

    try:
        assets=args.assets_dir.resolve() if args.assets_dir else root/'downloads'
        assets.mkdir(parents=True,exist_ok=True)
        for name,(url,expected) in ASSETS.items():
            path=assets/name
            if not path.exists():
                print('Downloading '+name,flush=True)
                with urlopen(url,timeout=90) as source,path.open('wb') as target:
                    while block:=source.read(1024*1024):target.write(block)
            if sha(path)!=expected:raise RuntimeError('Asset hash mismatch: '+name)
        dist=root/'lima-dist';dist.mkdir()
        with tarfile.open(assets/'lima.tar.gz') as archive:archive.extractall(dist,filter='data')
        config=dict(vmType='vz',arch='aarch64',cpus=4,memory='4GiB',disk='20GiB',
            images=[dict(location=str(assets/'ubuntu-arm64.img'),arch='aarch64',digest='sha256:'+ASSETS['ubuntu-arm64.img'][1])],
            mounts=[],containerd=dict(system=False,user=False),propagateProxyEnv=False,
            ssh=dict(loadDotSSHPubKeys=False,forwardAgent=False,forwardX11=False,overVsock=False),
            portForwards=[dict(guestIP='0.0.0.0',proto='any',ignore=True)],
            vmOpts=dict(vz=dict(rosetta=dict(enabled=False,binfmt=False))))
        (root/'vm.yaml').write_text(json.dumps(config,indent=2)+'\n')
        shutil.copy2(root/'vm.yaml',output/'vm.yaml')
        inputs=root/'ehu-inputs';inputs.mkdir()
        names=['vm_session.py','bootstrap-docker28.sh','endpoint.Dockerfile','guest_experiment.py',
               'guest_repair_proof.sh','guest_export.py','verify_mapping.py','build_endpoint.sh','guest_timing_diagnostic.py']
        for name in names:shutil.copy2(HERE/name,inputs/name)
        shutil.copytree(HERE/'compat',inputs/'compat',ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(HERE/'tests',inputs/'tests',ignore=shutil.ignore_patterns('__pycache__'))
        manifest={str(p.relative_to(inputs)):sha(p) for p in inputs.rglob('*') if p.is_file()}
        state['input_sha256']=manifest
        (output/'input-sha256.json').write_text(json.dumps(manifest,indent=2)+'\n')
        shutil.copytree(inputs,output/'inputs')
        with tarfile.open(root/'inputs.tar.gz','w:gz') as archive:archive.add(inputs,arcname='ehu-inputs')
        if len(str(root/'lima-home/ehu-madt-20261019/ssh.sock.1234567890123456').encode())>=104:
            raise RuntimeError('Working path exceeds the macOS Unix socket limit')
        env=dict(os.environ,EHU_MADT_RUN_ROOT=str(root),EHU_LIMA_BINARY=str(dist/'bin/limactl'))
        stream=(output/'supervisor-output.jsonl').open('w')
        proc=subprocess.Popen([sys.executable,str(inputs/'vm_session.py')],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=(output/'supervisor-stderr.txt').open('w'),text=True,env=env)
        reader=threading.Thread(target=consume,daemon=True);reader.start()
        receive(lambda r:isinstance(r,str) and r.startswith('VM_READY'),720)
        ready=True
        print('Guest ready: Docker28 preparation',flush=True)
        command(dict(action='copy',source=str(root/'inputs.tar.gz'),destination='ehu-madt-20261019:/tmp/ehu-inputs.tar.gz'))
        command(dict(action='guest',args=['sudo','tar','-xzf','/tmp/ehu-inputs.tar.gz','-C','/tmp'],timeout=30))
        extracted=True
        command(dict(action='guest',args=['sudo','bash','/tmp/ehu-inputs/bootstrap-docker28.sh'],timeout=900))
        command(dict(action='guest',args=['sudo','bash','-c','cp /tmp/ehu-inputs/endpoint.Dockerfile /tmp/endpoint.Dockerfile && DOCKER_BUILDKIT=0 bash /tmp/ehu-inputs/build_endpoint.sh'],timeout=300))
        print('Running unpatched control, regression cases and patched '+args.stage,flush=True)
        result=command(dict(action='guest',args=['sudo','bash','/tmp/ehu-inputs/guest_repair_proof.sh',args.stage],timeout=1200),allow_failure=True)
        state['proof_returncode']=result['returncode']
        state['status']=('DIAGNOSTIC_COMPLETED' if args.stage=='timing' else 'PASSED') if result['returncode']==0 else 'FAILED'
    except BaseException as error:
        state['error']=repr(error)
        print('Run failed: '+repr(error),file=sys.stderr,flush=True)
    finally:
        if proc is not None:
            try:
                if extracted and ready and proc.poll() is None:
                    command(dict(action='guest',args=['sudo','python3','/tmp/ehu-inputs/guest_export.py'],timeout=90))
                    command(dict(action='copy',source='ehu-madt-20261019:/tmp/ehu-repair-evidence.tar.gz',destination=str(output/'guest-evidence.tar.gz')))
                    state['guest_evidence_sha256']=sha(output/'guest-evidence.tar.gz')
            except BaseException as error:
                state['export_error']=repr(error);state['status']='FAILED'
            finally:
                try:
                    if proc.poll() is None:
                        proc.stdin.write('{"action":"close"}\n');proc.stdin.flush()
                        proc.stdin.close()
                    proc.wait(timeout=195)
                except BaseException as error:
                    state['close_error']=repr(error);state['status']='FAILED'
                    if proc.poll() is None:
                        proc.terminate()
                        try:proc.wait(timeout=195)
                        except subprocess.TimeoutExpired:state['cleanup_requires_attention']=True
                state['supervisor_returncode']=proc.poll()
                if proc.poll()!=0:state['status']='FAILED'
                if reader:reader.join(timeout=5)
                if stream:stream.close()
        ledger=root/'vm-ledger.json'
        if ledger.exists():
            state['vm_ledger']=json.loads(ledger.read_text())
            shutil.copy2(ledger,output/'vm-ledger.json')
        if (root/'logs').exists():shutil.copytree(root/'logs',output/'host-logs')
        clean=(not proc) or (proc.poll() is not None and state.get('vm_ledger',{}).get('state') in ['deleted','not_created'])
        clean=clean and not (root/'lima-home/ehu-madt-20261019').exists()
        if clean:
            assert root.name.startswith('ehu-madt-repair-run-') and (root/'.owned-by-madt-runner').read_text()==str(output)
            shutil.rmtree(root)
            state['temporary_work_directory_absent']=not root.exists()
        else:
            state['status']='FAILED';state['cleanup_requires_attention']=True
        state['end_ns']=time.time_ns()
        (output/'host-summary.json').write_text(json.dumps(state,indent=2)+'\n')
        print(json.dumps({k:state[k] for k in ['status','proof_returncode','temporary_work_directory_absent','error','cleanup_requires_attention'] if k in state}),flush=True)
    return 0 if state['status'] in ['PASSED','DIAGNOSTIC_COMPLETED'] else 1


if __name__=='__main__':raise SystemExit(main())
