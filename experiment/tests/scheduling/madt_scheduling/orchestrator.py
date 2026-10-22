"""Open-loop source and serialized placement; actual sockets/monotonic timestamps."""
import argparse
import asyncio
import base64
from collections import deque
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
from .core import (Task, Ledger, Profiles, Snapshot, WORKERS, CLASSES, POLICIES,
                   choose, eligible, payload, compute, timing_components)
from .worker import clock_identity
from . import wire

class Orchestrator:
    def __init__(self,config):
        self.config=config;self.run_id=config['run_id'];self.policy=config.get('policy','rr')
        if self.policy not in POLICIES:raise ValueError('Unknown policy')
        self.kind=config.get('kind','comparison')
        if self.kind not in ('comparison','calibration','queue-proof','local-test'):raise ValueError('Unknown run kind')
        self.tasks=tuple(Task(**t) for t in config['tasks'])
        if len({t.id for t in self.tasks})!=len(self.tasks) or not self.tasks:raise ValueError('Repeated/empty task IDs')
        if len(self.tasks)>(36 if self.kind=='calibration' else 12):raise ValueError('Tiny pilot task cap; full matrix is forbidden')
        repetitions=config.get('warmup_repetitions',5)
        if type(repetitions) is not int or repetitions not in (0,5) or (self.kind=='comparison' and repetitions!=5):
            raise ValueError('Comparison requires the common 60-job warmup')
        if any(a.release_ns>b.release_ns for a,b in zip(self.tasks,self.tasks[1:])):raise ValueError('Unordered releases')
        self.forced={int(k):v for k,v in config.get('forced',{}).items()}
        if self.kind=='comparison' and self.forced:raise ValueError('Forced comparison forbidden')
        if any(j not in WORKERS for j in self.forced.values()):raise ValueError('Unknown forced worker')
        self.ledger=Ledger(config.get('credits',32),config.get('memory',64*1_048_576))
        self.profiles=Profiles.from_dict(config['profiles']);self.cursor=0
        self.order=tuple(config.get('tie_order',WORKERS))
        if set(self.order)!=set(WORKERS) or len(self.order)!=3:raise ValueError('Tie order must permute workers')
        self.rows={};self.data={};self.input_hashes={};self.expected={};self.job_done={}
        self.global_fifo=deque();self.sender={j:asyncio.Queue(maxsize=self.ledger.k) for j in WORKERS}
        self.changed=asyncio.Event();self.connections={};self.telemetry_empty={};self.finished=False;self.stopping=False
        self.handlers=set();self.accepted_writers=set();self.pending_handshakes=set();self.errors=[];self.clock_probes={};self.barriers={};self.confirmed={j:0 for j in WORKERS}
        self.output=Path(config['output']);self.output.mkdir(parents=True,exist_ok=False)
        self.log=(self.output/'events.jsonl').open('w')
        self.warmup=tuple(Task(2**63+i,*CLASSES[c],seed=config.get('seed',0))
                          for i,(j,c,r) in enumerate((j,c,r) for j in WORKERS for c in range(4) for r in range(config.get('warmup_repetitions',5))))
        self.warmup_workers={t.id:WORKERS[i//(4*config.get('warmup_repetitions',5))] for i,t in enumerate(self.warmup)} if self.warmup else {}
        for task in (*self.warmup,*self.tasks):
            if task.id in self.data:raise ValueError('Warmup/scored ID collision')
            data=payload(task);self.data[task.id]=data;self.input_hashes[task.id]=hashlib.sha256(data).hexdigest();self.expected[task.id]=compute(task,data)
        self.clock=clock_identity()

    def event(self,event,**fields):
        self.log.write(json.dumps(dict(event=event,at=time.monotonic_ns(),**fields),allow_nan=False)+'\n');self.log.flush()

    async def control(self,worker,**message):
        return await wire.write(self.connections[worker],dict(run_id=self.run_id,**message))

    def error(self,error):
        self.errors.append(str(error));self.event('instrument_error',error=str(error));self.changed.set()

    async def connection(self,reader,writer):
        worker=None;handler=asyncio.current_task();self.handlers.add(handler)
        self.accepted_writers.add(writer);self.pending_handshakes.add(writer)
        try:
            hello=await asyncio.wait_for(wire.read(reader),5);worker=hello['worker']
            if hello.get('type')!='hello' or hello.get('run_id')!=self.run_id or worker not in WORKERS or worker in self.connections:
                raise ValueError('Invalid/duplicate event channel identity')
            self.connections[worker]=writer
            identity=hello['clock']
            if self.config.get('require_linux_clock',False):
                if not self.clock['boot'] or not self.clock['time_namespace'] or self.clock['offsets'] is None:
                    raise ValueError('Linux common-clock identity unavailable')
                if identity!=self.clock:raise ValueError('Different Linux boot/time namespace')
                for line in self.clock['offsets'].splitlines():
                    if any(int(v)!=0 for v in line.split()[1:]):raise ValueError('Nonzero time namespace offsets')
            elif identity!=self.clock:raise ValueError('Different local clock identity')
            self.pending_handshakes.discard(writer)
            self.event('worker_hello',worker=worker,hello=hello,source_clock=self.clock);self.changed.set()
            while True:
                message=await asyncio.wait_for(wire.read(reader),10);received=time.monotonic_ns()
                if message.get('run_id')!=self.run_id or message.get('worker')!=worker:raise ValueError('Event identity mismatch')
                kind=message['type']
                if kind=='telemetry':
                    if message['epoch']!=hello['epoch']:raise ValueError('Changed worker epoch')
                    accepted=self.ledger.telemetry(worker,message['epoch'],message['sequence'],message['sent'],received,message['online'],message['items'])
                    if accepted:self.telemetry_empty[worker]=not message['items']
                    self.event('telemetry_received',worker=worker,received=received,accepted=accepted,message=message)
                elif kind=='clock_reply':
                    probe=self.clock_probes[(worker,message['probe'])]
                    if not probe['start']<=message['received']<=message['sent']<=received:raise ValueError('Inconsistent cross-clock probe')
                    probe.update(reply=message,receipt=received);probe['done'].set()
                    self.event('clock_validated',worker=worker,start=probe['start'],reply=message,receipt=received)
                elif kind=='barrier_reply':
                    if not message['empty']:raise ValueError('Warmup did not drain worker')
                    self.barriers[worker].set()
                elif kind=='result':
                    self.event('result_received',worker=worker,received=received,message=message)
                    task_id=message['id'];row=self.rows.get(task_id)
                    if row is None or row.get('worker')!=worker:raise ValueError('Unknown result ID/worker')
                    if row['outcome']=='completed':
                        if self.expected[task_id]!=base64.b64decode(message['value'],validate=True) or any(message[k]!=row[k] for k in ('f','x','y','cpu_ns','sequence','payload_hash')):raise ValueError('Conflicting duplicate result')
                        self.event('duplicate_result',worker=worker,id=task_id)
                        await self.control(worker,type='result_ack',confirmed=self.confirmed[worker])
                    else:
                        if row['outcome']=='failed':raise ValueError('Result after permanent failure')
                        if message['sequence']!=self.confirmed[worker]+1:raise ValueError('Gap in per-worker result sequence')
                        valid=(base64.b64decode(message['value'],validate=True)==self.expected[task_id]
                               and message['payload_hash']==row['payload_hash'] and message['sequence']==row['sequence'])
                        row.update({k:message[k] for k in ('f','x','y','cpu_ns')});row['z']=time.monotonic_ns()
                        if not valid:
                            row['outcome']='failed';self.ledger.complete(worker,task_id,False)
                            raise ValueError('Incorrect task result')
                        try:
                            components=timing_components(row)
                            if type(message['cpu_ns']) is not int or message['cpu_ns']<0:raise ValueError('Invalid worker CPU duration')
                            self.ledger.complete(worker,task_id,True,f=message['f'],x=message['x'],y=message['y'],receipt=row['z'])
                        except ValueError:
                            row['outcome']='failed';self.ledger.complete(worker,task_id,False);raise
                        row['outcome']='completed';row['components_ns']=components
                        row['on_time']=row['z']<=row['a_star']+self.config.get('deadline_ns',1_000_000_000)
                        self.confirmed[worker]=message['sequence']
                        await self.control(worker,type='result_ack',confirmed=self.confirmed[worker])
                        self.event('validated_result',id=task_id,worker=worker,z=row['z'],message=message)
                        self.job_done[task_id].set()
                else:raise ValueError('Unknown event type')
                self.changed.set()
        except asyncio.IncompleteReadError:
            if not self.stopping:self.error('Unexpected worker event EOF: '+str(worker))
        except Exception as error:self.error(repr(error))
        finally:
            try:await asyncio.wait_for(wire.close(writer),1)
            finally:
                self.handlers.discard(handler);self.accepted_writers.discard(writer);self.pending_handshakes.discard(writer)

    async def until(self,predicate,seconds):
        deadline=asyncio.get_running_loop().time()+seconds
        while not predicate():
            if self.errors:raise RuntimeError(self.errors)
            self.changed.clear()
            if predicate():return
            await asyncio.wait_for(self.changed.wait(),max(0.001,deadline-asyncio.get_running_loop().time()))

    async def upload_loop(self,worker):
        reader,writer=await asyncio.open_connection(self.config['workers'][worker],self.config.get('upload_ports',{}).get(worker,self.config['upload_port']))
        try:
            await wire.write(writer,dict(type='upload_hello',run_id=self.run_id,worker=worker))
            hello=await wire.read(reader)
            if hello.get('run_id')!=self.run_id or hello.get('worker')!=worker or hello.get('epoch')!=self.ledger.workers[worker]['epoch']:
                raise ValueError('Upload handshake mismatch')
            while True:
                task=await self.sender[worker].get();row=self.rows[task.id]
                e=time.monotonic_ns();row['e']=e;self.ledger.uploading(task.id,e)
                count=await wire.write(writer,dict(type='task',run_id=self.run_id,worker=worker,task=asdict(task),
                    sequence=row['sequence'],confirmed=self.confirmed[worker],payload_hash=row['payload_hash']))
                writer.write(self.data[task.id]);await writer.drain()
                ack=await wire.read(reader);at=time.monotonic_ns()
                if ack.get('type')!='admission_ack' or ack.get('run_id')!=self.run_id or ack.get('worker')!=worker or ack.get('id')!=task.id or ack.get('epoch')!=hello['epoch']:
                    raise ValueError('Invalid admission ACK')
                if not e<=ack['f']<=at:raise ValueError('ACK causal clock mismatch')
                # Completion can precede ACK; neither phase nor credit is regressed.
                if 'f' in row and row['f']!=ack['f']:raise ValueError('Changed input timestamp')
                row['f']=ack['f'];row['ack_receipt']=at
                self.ledger.ack(worker,task.id,ack['f'],at)
                self.event('upload_ack',id=task.id,worker=worker,e=e,ack=ack,receipt=at,application_bytes=task.size,control_bytes=count)
                self.sender[worker].task_done();self.changed.set()
        finally:await wire.close(writer)

    async def dispatch(self):
        while True:
            await self.until(lambda:bool(self.global_fifo),3600)
            task=self.global_fifo[0];row=self.rows[task.id]
            fits=task.reservation<=self.ledger.memory
            if not fits:
                self.global_fifo.popleft();row['outcome']='rejected';self.ledger.jobs[task.id]['state']='rejected';self.job_done[task.id].set();self.changed.set();continue
            views=self.ledger.views();forced=row.get('forced')
            available=[v for v in views if eligible(v,task,self.ledger.k,self.ledger.memory) and (not forced or v.worker==forced)]
            if not available:
                self.changed.clear();await self.changed.wait();continue
            g=time.monotonic_ns();self.global_fifo.popleft();row['g']=g;self.ledger.begin(task.id)
            snapshot=Snapshot(task,views,self.profiles,self.order)
            b=time.monotonic_ns();cpu=time.thread_time_ns()
            if forced:worker,next_cursor,costs=forced,self.cursor,()
            else:worker,next_cursor,costs=choose(self.policy,snapshot,b,self.cursor,self.ledger.k,self.ledger.memory)
            cpu_delta=time.thread_time_ns()-cpu;c=time.monotonic_ns()
            if worker is None:raise ValueError('Eligibility changed inside serialized decision')
            sequence=self.ledger.commit(task.id,worker);self.cursor=next_cursor
            row.update(b=b,c=c,decision_cpu_ns=cpu_delta,worker=worker,sequence=sequence)
            row['d']=time.monotonic_ns();self.sender[worker].put_nowait(task)
            self.event('placement',id=task.id,snapshot=asdict(snapshot),snapshot_time=b,costs=costs,d=row['d'],worker=worker)
            self.changed.set()

    def release(self,task,a_star,phase,forced=None):
        a=time.monotonic_ns();self.ledger.admit(task);self.job_done[task.id]=asyncio.Event()
        row=dict(id=task.id,phase=phase,task=asdict(task),a_star=a_star,a=a,outcome='pending',
                 payload_hash=self.input_hashes[task.id],forced=forced)
        self.rows[task.id]=row
        if len(self.global_fifo)>=self.config.get('global_capacity',4096):
            row['outcome']='rejected';self.ledger.jobs[task.id]['state']='rejected';self.job_done[task.id].set()
        else:self.global_fifo.append(task)
        self.event('release',id=task.id,a=a,a_star=a_star,phase=phase,outcome=row['outcome']);self.changed.set()

    async def run(self):
        tasks=[];server=None;start=None
        try:
            server=await asyncio.start_server(self.connection,self.config.get('bind','0.0.0.0'),self.config['event_port'])
            (self.output/'ready').write_text('listening\n')
            await self.until(lambda:len(self.connections)==3 and all(v.online for v in self.ledger.views()),60)
            for worker in WORKERS:
                for i in range(5):
                    probe=dict(start=time.monotonic_ns(),done=asyncio.Event());self.clock_probes[(worker,i)]=probe
                    await self.control(worker,type='clock_probe',probe=i)
                    await asyncio.wait_for(probe['done'].wait(),5)
            tasks=[asyncio.create_task(self.dispatch())]+[asyncio.create_task(self.upload_loop(j)) for j in WORKERS]
            def failed(job):
                if not job.cancelled() and job.exception():self.error(repr(job.exception()))
            for job in tasks:job.add_done_callback(failed)
            for task in self.warmup:
                self.release(task,time.monotonic_ns(),'warmup',self.warmup_workers[task.id])
                await self.until(lambda:self.job_done[task.id].is_set(),30)
            await self.until(lambda:all(v.credits==0 and v.active_upload is None for v in self.ledger.views()),10)
            for worker in WORKERS:
                self.barriers[worker]=asyncio.Event()
                await self.control(worker,type='barrier',confirmed=self.confirmed[worker])
                await asyncio.wait_for(self.barriers[worker].wait(),5)
            self.cursor=0
            null_spans=[]
            null_call=lambda:None
            for _ in range(100):
                b=time.monotonic_ns();cpu=time.thread_time_ns();null_call()
                cpu_delta=time.thread_time_ns()-cpu;c=time.monotonic_ns()
                null_spans.append((c-b,cpu_delta))
            self.event('null_call_instrumentation',spans_elapsed_cpu_ns=null_spans,scope='no-op instrumentation, not scheduling competitor; never subtracted')
            start=time.monotonic_ns();self.event('scored_start',start=start)
            for task in self.tasks:
                await asyncio.sleep(max(0,(start+task.release_ns-time.monotonic_ns())/1e9))
                self.release(task,start+task.release_ns,'scored',self.forced.get(task.id))
                if self.kind=='calibration':await self.until(lambda:self.job_done[task.id].is_set(),30)
            horizon=self.config.get('horizon_ns',6_000_000_000)
            await asyncio.sleep(max(0,(start+horizon-time.monotonic_ns())/1e9))
            try:
                await self.until(lambda:all(self.job_done[t.id].is_set() for t in self.tasks),self.config.get('drain_seconds',60))
            except TimeoutError:
                self.event('drain_expired',remaining=[t.id for t in self.tasks if not self.job_done[t.id].is_set()])
            if all(self.job_done[t.id].is_set() for t in self.tasks):
                await self.until(lambda:all(v.active_upload is None for v in self.ledger.views()),10)
        except Exception as error:self.error(repr(error))
        finally:
            self.stopping=True
            for task in self.tasks:
                if task.id not in self.rows:
                    self.rows[task.id]=dict(id=task.id,phase='scored',task=asdict(task),a_star=None if start is None else start+task.release_ns,outcome='not_released',payload_hash=self.input_hashes[task.id])
            for row in self.rows.values():
                if row['outcome']=='pending':row['outcome']='unresolved'
            for worker in self.connections:
                try:
                    await self.control(worker,type='result_ack',confirmed=self.confirmed[worker])
                    await self.control(worker,type='stop',allow_unresolved=bool(self.errors) or any(r['outcome']=='unresolved' for r in self.rows.values()))
                except (OSError,ConnectionError):pass
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if server:server.close()
            for writer in self.pending_handshakes:self.error('Unfinished event handshake at shutdown')
            for writer in tuple(self.accepted_writers):writer.close()
            if self.handlers:
                _,pending=await asyncio.wait(tuple(self.handlers),timeout=1)
                for handler in pending:handler.cancel()
                if pending:await asyncio.gather(*pending,return_exceptions=True)
            if server:
                try:await asyncio.wait_for(server.wait_closed(),2)
                except TimeoutError:self.error('Event server close timed out')
            rows=list(self.rows.values());scored=[r for r in rows if r['phase']=='scored']
            counts={key:sum(r['outcome']==key for r in scored) for key in ('completed','rejected','failed','unresolved','not_released')}
            assert sum(counts.values())==len(self.tasks)
            summary=dict(status='INVALID' if self.errors else 'RUN_FINISHED',errors=self.errors,kind=self.kind,
                         policy=self.policy,offered=len(self.tasks),outcomes=counts,on_time=sum(r.get('on_time',False) for r in scored),
                         clock_scope='verified shared Linux boot/time namespace + 15 causal probes' if self.config.get('require_linux_clock') else 'local common-host assumption + 15 probes; not MADT',
                         start=start,finished=time.monotonic_ns(),profiles=self.config['profiles'])
            (self.output/'tasks.json').write_text(json.dumps(rows,indent=2)+'\n')
            (self.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
            self.event('shutdown',summary=summary);self.log.close()
        return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);a=parser.parse_args()
    result=asyncio.run(Orchestrator(json.loads(a.config.read_text())).run())
    if result['status']=='INVALID':raise SystemExit(1)

if __name__=='__main__':main()
