"""One real CPU slot, an input FIFO, and independent result/telemetry transport."""
import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from .core import Task, compute, MAX_TASKS
from . import wire


def clock_identity():
    def read(path):
        try:return Path(path).read_text().strip()
        except OSError:return None
    def link(path):
        try:return os.readlink(path)
        except OSError:return None
    return dict(boot=read('/proc/sys/kernel/random/boot_id'),
                time_namespace=link('/proc/self/ns/time'),offsets=read('/proc/self/timens_offsets'))


class Worker:
    def __init__(self,config):
        self.config=config;self.run_id=config['run_id'];self.worker=config['worker']
        self.epoch=uuid.uuid4().hex;self.entries={};self.seen={};self.last_seq=0;self.confirmed=0
        self.queue=asyncio.Queue(maxsize=config.get('credits',32));self.results=asyncio.Queue(maxsize=config.get('credits',32))
        self.stop=asyncio.Event();self.lock=asyncio.Lock();self.upload_connected=False
        self.censored_shutdown=False;self.errors=[];self.output=Path(config['output']);self.output.mkdir(parents=True,exist_ok=False)
        self.log=(self.output/'events.jsonl').open('w');self.report_seq=0

    def event(self,event,**fields):
        self.log.write(json.dumps(dict(event=event,at=time.monotonic_ns(),worker=self.worker,**fields))+'\n');self.log.flush()

    async def send(self,message):
        async with self.lock:
            size=await wire.write(self.event_writer,dict(run_id=self.run_id,worker=self.worker,**message))
            self.event('event_frame_sent',type=message['type'],wire_bytes=size)

    def confirm(self,sequence):
        if type(sequence) is not int or not self.confirmed<=sequence<=self.last_seq:
            if type(sequence) is int and sequence<=self.confirmed:return
            raise ValueError('Invalid result confirmation sequence')
        for task_id,row in list(self.entries.items()):
            if row['seq']<=sequence:
                if row['phase']!='returning':raise ValueError('Confirmation before execution end')
                del self.entries[task_id]
        self.confirmed=sequence

    async def upload(self,reader,writer):
        owner=False
        try:
            if self.upload_connected:raise ValueError('Second upload channel')
            self.upload_connected=True;owner=True
            hello=await wire.read(reader)
            if hello!={'type':'upload_hello','run_id':self.run_id,'worker':self.worker}:
                raise ValueError('Upload identity mismatch')
            await wire.write(writer,dict(type='upload_ready',epoch=self.epoch,run_id=self.run_id,worker=self.worker))
            while not self.stop.is_set():
                header=await wire.read(reader)
                if header.get('run_id')!=self.run_id or header.get('worker')!=self.worker or header.get('type')!='task':
                    raise ValueError('Task identity mismatch')
                task=Task(**header['task']);sequence=header['sequence']
                self.confirm(header['confirmed'])
                data=await reader.readexactly(task.size)
                digest=hashlib.sha256(data).hexdigest()
                if digest!=header['payload_hash']:raise ValueError('Input hash mismatch')
                fingerprint=(sequence,task,digest)
                if task.id in self.seen:
                    if self.seen[task.id]['fingerprint']!=fingerprint:raise ValueError('Conflicting repeated ID')
                    f=self.seen[task.id]['f']
                    self.event('duplicate_upload',id=task.id)
                else:
                    if len(self.seen)>=MAX_TASKS or sequence!=self.last_seq+1:
                        raise ValueError('Invalid sequence or task bound')
                    if len(self.entries)>=self.config.get('credits',32) or sum(r['reservation'] for r in self.entries.values())+task.reservation>self.config.get('memory',64*1_048_576):
                        raise ValueError('Worker credit/reservation violation')
                    f=time.monotonic_ns()
                    row=dict(id=task.id,seq=sequence,phase='worker_wait',f=f,reservation=task.reservation,payload_hash=digest)
                    self.entries[task.id]=row;self.seen[task.id]=dict(fingerprint=fingerprint,f=f)
                    self.last_seq=sequence
                    self.queue.put_nowait((task,data))
                    self.event('input_admitted',id=task.id,f=f,sequence=sequence,queued=sum(r['phase']=='worker_wait' for r in self.entries.values()))
                await wire.write(writer,dict(type='admission_ack',run_id=self.run_id,worker=self.worker,id=task.id,f=f,epoch=self.epoch))
                self.event('admission_ack_sent',id=task.id)
        except asyncio.IncompleteReadError:
            if not self.stop.is_set():self.errors.append('Unexpected upload EOF');self.stop.set()
        except Exception as error:
            self.errors.append(repr(error));self.event('upload_error',error=repr(error));self.stop.set()
        finally:
            if owner:self.upload_connected=False
            await wire.close(writer)

    async def execute(self):
        loop=asyncio.get_running_loop()
        while True:
            task,data=await self.queue.get()
            row=self.entries[task.id]
            def started(x):
                row.update(phase='executing',x=x)
                self.event('execution_started',id=task.id,x=x)
            def kernel():
                x=time.monotonic_ns();cpu=time.thread_time_ns()
                loop.call_soon_threadsafe(started,x)
                value=compute(task,data)
                return value,x,time.monotonic_ns(),time.thread_time_ns()-cpu
            value,x,y,cpu=await asyncio.to_thread(kernel)
            row.update(phase='returning',x=x,y=y)
            self.event('execution_ended',id=task.id,x=x,y=y,cpu_ns=cpu)
            self.results.put_nowait(dict(type='result',id=task.id,sequence=row['seq'],f=row['f'],x=x,y=y,
                                        cpu_ns=cpu,payload_hash=row['payload_hash'],value=base64.b64encode(value).decode()))
            self.queue.task_done()
            # CPU loop never waits for a result ACK or result-channel drain.

    async def return_results(self):
        while True:
            message=await self.results.get();await self.send(message);self.results.task_done()

    async def telemetry(self):
        deadline=asyncio.get_running_loop().time()
        while True:
            self.report_seq+=1
            items=[{k:v for k,v in r.items() if k in ('id','phase','f','x','y')} for r in self.entries.values()]
            await self.send(dict(type='telemetry',epoch=self.epoch,sequence=self.report_seq,
                                 sent=time.monotonic_ns(),online=True,items=items))
            deadline+=0.1
            await asyncio.sleep(max(0,deadline-asyncio.get_running_loop().time()))

    async def commands(self,reader):
        try:
            while True:
                message=await wire.read(reader)
                if message.get('run_id')!=self.run_id:raise ValueError('Control run mismatch')
                if message['type']=='result_ack':self.confirm(message['confirmed'])
                elif message['type']=='clock_probe':
                    received=time.monotonic_ns()
                    await self.send(dict(type='clock_reply',probe=message['probe'],received=received,sent=time.monotonic_ns()))
                elif message['type']=='barrier':
                    self.confirm(message['confirmed'])
                    await self.send(dict(type='barrier_reply',empty=not self.entries and self.queue.empty() and self.results.empty()))
                elif message['type']=='stop':
                    self.event('stop',remaining=len(self.entries),queued=self.queue.qsize())
                    self.censored_shutdown=bool(message.get('allow_unresolved',False))
                    if self.entries and not self.censored_shutdown:raise ValueError('Stop with unconfirmed work')
                    self.stop.set();return
                else:raise ValueError('Unknown control message')
        except asyncio.IncompleteReadError:
            self.errors.append('Unexpected event-channel EOF');self.stop.set()
        except Exception as error:
            self.errors.append(repr(error));self.event('control_error',error=repr(error));self.stop.set()

    async def run(self):
        server=await asyncio.start_server(self.upload,self.config.get('bind','0.0.0.0'),self.config['upload_port'])
        deadline=asyncio.get_running_loop().time()+60
        attempts=0
        while True:
            try:
                reader,self.event_writer=await asyncio.open_connection(self.config['source'],self.config['event_port']);break
            except ConnectionRefusedError:
                attempts+=1
                if asyncio.get_running_loop().time()>=deadline:raise
                await asyncio.sleep(0.1)
        self.event('event_channel_connected',startup_attempts=attempts+1)
        await self.send(dict(type='hello',epoch=self.epoch,clock=clock_identity(),pid=os.getpid()))
        jobs=[asyncio.create_task(f()) for f in (self.execute,self.return_results,self.telemetry)]
        jobs.append(asyncio.create_task(self.commands(reader)))
        def failed(task):
            if not task.cancelled() and task.exception():
                self.errors.append(repr(task.exception()));self.stop.set()
        for job in jobs:job.add_done_callback(failed)
        try:
            await asyncio.wait_for(self.stop.wait(),self.config.get('max_seconds',120))
        finally:
            self.stop.set();server.close();await server.wait_closed()
            for job in jobs:job.cancel()
            await asyncio.gather(*jobs,return_exceptions=True)
            await wire.close(self.event_writer)
            self.event('shutdown',errors=self.errors,remaining=len(self.entries));self.log.close()
            (self.output/'summary.json').write_text(json.dumps(dict(errors=self.errors,remaining=len(self.entries),censored_shutdown=self.censored_shutdown))+'\n')
        if self.errors:raise RuntimeError(self.errors)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);a=parser.parse_args()
    asyncio.run(Worker(json.loads(a.config.read_text())).run())

if __name__=='__main__':main()
