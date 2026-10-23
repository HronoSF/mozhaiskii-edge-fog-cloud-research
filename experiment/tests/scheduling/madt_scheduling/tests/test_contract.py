import asyncio
from dataclasses import FrozenInstanceError
import hashlib
import unittest
from madt_scheduling.core import (Task, Profiles, Ledger, Pending, View, Snapshot,
                                  WORKERS, CLASSES, payload, compute, trace, choose,
                                  predict, eligible, timing_components)
from madt_scheduling import wire


def profiles(service=None,transport=None):
    return Profiles.from_dict(dict(service={j:{f'{w}:{b}':(service or {}).get(j,10) for w,b in CLASSES} for j in WORKERS},
        transport={j:{str(b):(transport or {}).get((j,b),(0,0,0)) for b in (65536,1048576)} for j in WORKERS}))


def ready(ledger):
    for j in WORKERS:ledger.telemetry(j,j+'-epoch',0,0,0,True,[])

class Contract(unittest.TestCase):
    def test_payload_and_full_result_vector(self):
        t=Task(7,200000,65536,seed=1)
        self.assertEqual(hashlib.sha256(b'ehu-input-v1|1|7').hexdigest(),'4441baae6053247daf4450ebd3d7351526cae9f3a0ddf1bb471bd37e7d51a77d')
        self.assertEqual(compute(t,payload(t))[:32].hex(),'2c86646aa7a8388ae6e6b866cce2ffb031d08f9c03211f220e870fb5d7d309af')
        self.assertEqual(len(payload(t)),65536)
        self.assertEqual(len(compute(t,payload(t))),256)
        self.assertEqual(compute(t,payload(t))[32:40],(7).to_bytes(8,'big'))
        self.assertEqual(compute(t,payload(t))[40:],bytes(216))
        self.assertNotEqual(compute(t,payload(t)),compute(t,payload(t)[:-1]+b'!'))

    def test_trace_balance_and_common_sequences(self):
        for n in (4,12,100,4096):
            for seed in (0,1,9):
                steady=trace(n,120000000000,seed,'steady');burst=trace(n,120000000000,seed,'burst')
                self.assertEqual([(t.id,t.key,t.seed) for t in steady],[(t.id,t.key,t.seed) for t in burst])
                self.assertEqual(len(burst),n)
                self.assertEqual([sum((t.iterations,t.size)==c for t in burst) for c in CLASSES],[n//4]*4)
                self.assertEqual([t.release_ns for t in burst],sorted(t.release_ns for t in burst))
                self.assertLess(burst[-1].release_ns,120000000000)
        self.assertEqual([t.release_ns for t in trace(4,120,0,'burst')],[0,40,60,80])

    def test_invalid_tasks_and_profiles(self):
        for args in [(-1,200000,65536),(1,1,65536),(1,200000,5)]:
            with self.assertRaises(ValueError):Task(*args)
        with self.assertRaises(ValueError):trace(5)
        with self.assertRaises(ValueError):trace(4,scenario='winner')
        with self.assertRaises(ValueError):Profiles.from_dict(dict(service={j:{f'{w}:{b}':-1 for w,b in CLASSES} for j in WORKERS}))

    def test_finite_credits_and_reservation_not_cpu(self):
        ledger=Ledger(k=1);ready(ledger);a=Task(1,*CLASSES[0]);b=Task(2,*CLASSES[0])
        ledger.admit(a);ledger.admit(b);ledger.commit(1,'E')
        v=ledger.views()[0];self.assertEqual(v.credits,1);self.assertEqual(v.reserved,a.reservation)
        self.assertFalse(eligible(v,b,k=1))
        self.assertEqual(predict(v,b,profiles(),0,False),20)
        with self.assertRaises(ValueError):ledger.commit(2,'E')
        with self.assertRaises(ValueError):ledger.commit(1,'F')
        ledger.uploading(1,0)
        self.assertTrue(ledger.complete('E',1,True,f=1,x=2,y=3,receipt=4));self.assertFalse(ledger.complete('E',1,True))
        self.assertEqual(ledger.views()[0].credits,0)
        ledger.commit(2,'E')
        full=View('E',True,(),None,31,63*1048576,None,None)
        self.assertFalse(eligible(full,Task(3,800000,1048576)))

    def test_unknown_duplicate_and_failed_ids(self):
        ledger=Ledger();ready(ledger);task=Task(1,*CLASSES[0]);ledger.admit(task)
        with self.assertRaises(ValueError):ledger.admit(task)
        ledger.commit(1,'E')
        for j,i in [('C',1),('E',5)]:
            with self.assertRaises(ValueError):ledger.complete(j,i,True)
        self.assertFalse(ledger.complete('E',1,False));self.assertEqual(ledger.views()[0].credits,1)
        self.assertFalse(ledger.complete('E',1,True))
        self.assertEqual(ledger.jobs[1]['state'],'failed')

    def test_overrun_stale_missing_and_epoch(self):
        l=Ledger();ready(l);a=Task(1,*CLASSES[0]);b=Task(2,*CLASSES[0]);l.admit(a);l.commit(1,'E');l.uploading(1,0)
        l.telemetry('E','E-epoch',2,1,2,True,[dict(id=1,phase='executing',f=0,x=0)])
        self.assertFalse(l.telemetry('E','E-epoch',1,0,3,True,[]))
        self.assertEqual(predict(l.views()[0],b,profiles(),12,False),22) # running10 expired; candidate full10
        l.telemetry('E','E-epoch',3,3,4,True,[])
        self.assertEqual(l.views()[0].pending[0].phase,'executing') # absence is not completion
        self.assertEqual(l.views()[0].credits,1)
        with self.assertRaises(ValueError):l.telemetry('E','different',4,4,5,True,[])

    def test_impossible_unsent_and_preupload_telemetry(self):
        ledger=Ledger();ready(ledger)
        for i in (0,1):
            ledger.admit(Task(i,*CLASSES[0]));ledger.commit(i,'E')
        ledger.uploading(0,100)
        for task_id,f,x in ((1,110,120),(0,10,20)):
            with self.assertRaises(ValueError):
                ledger.telemetry('E','E-epoch',1,150,200,True,
                    [dict(id=task_id,phase='executing',f=f,x=x)])

    def test_telemetry_milestones_are_immutable(self):
        ledger=Ledger();ready(ledger);ledger.admit(Task(0,*CLASSES[0]));ledger.commit(0,'E');ledger.uploading(0,0)
        ledger.telemetry('E','E-epoch',1,4,5,True,[dict(id=0,phase='returning',f=1,x=2,y=3)])
        for f,y in ((2,3),(1,4)):
            with self.assertRaises(ValueError):
                ledger.telemetry('E','E-epoch',2,6,7,True,[dict(id=0,phase='returning',f=f,x=2,y=y)])

    def test_ack_and_result_reconcile_received_telemetry(self):
        ledger=Ledger();ready(ledger);ledger.admit(Task(0,*CLASSES[0]));ledger.commit(0,'E');ledger.uploading(0,0)
        ledger.telemetry('E','E-epoch',1,4,5,True,[dict(id=0,phase='returning',f=1,x=2,y=3)])
        with self.assertRaises(ValueError):ledger.ack('E',0,2,6)
        with self.assertRaises(ValueError):ledger.complete('E',0,True,f=1,x=2,y=4,receipt=6)
        self.assertEqual(ledger.views()[0].credits,1)
        ledger.complete('E',0,True,f=1,x=2,y=3,receipt=6)
        ledger.ack('E',0,1,7)
        self.assertEqual(ledger.views()[0].credits,0)

    def test_result_before_ack_keeps_upload_slot_and_no_regression(self):
        l=Ledger();ready(l);a=Task(1,*CLASSES[0]);l.admit(a);l.commit(1,'E');l.uploading(1,0)
        l.complete('E',1,True,f=1,x=2,y=3,receipt=4)
        self.assertEqual(l.views()[0].active_upload,1);self.assertEqual(l.views()[0].credits,0)
        l.ack('E',1,1,5)
        self.assertEqual(l.jobs[1]['phase'],'completed');self.assertIsNone(l.views()[0].active_upload)
        self.assertEqual(l.views()[0].pending,())

    def test_admission_newer_than_empty_report(self):
        l=Ledger();ready(l);a=Task(1,*CLASSES[0]);l.admit(a);l.commit(1,'E');l.uploading(1,0);l.ack('E',1,0,0)
        l.telemetry('E','E-epoch',1,1,2,True,[])
        self.assertEqual(l.views()[0].pending[0].phase,'worker_wait')
        self.assertEqual(predict(l.views()[0],Task(2,*CLASSES[0]),profiles(),3,False),23)

    def test_inflight_separates_input_and_ack_without_double_charge(self):
        a=Task(1,*CLASSES[0]);b=Task(2,200000,1048576)
        p=profiles(service={'E':2},transport={('E',65536):(10,5,0),('E',1048576):(3,0,0)})
        v=View('E',True,(Pending(a,1,'uploading',e=0),),1,1,a.reservation,None,None)
        self.assertEqual(predict(v,b,p,12,True),20)
        self.assertEqual(predict(v,b,p,12,False),16)
        v=View('E',True,(Pending(a,1,'executing',e=0,x=11),),1,1,a.reservation,None,None)
        self.assertEqual(predict(v,b,profiles(service={'E':10},transport={('E',65536):(10,5,0),('E',1048576):(3,0,0)}),12),31)

    def test_ready_backlog_and_busy_overlap(self):
        a=Task(1,*CLASSES[0]);b=Task(2,*CLASSES[0])
        v=View('E',True,(Pending(a,1,'worker_wait'),),None,1,a.reservation,None,None)
        self.assertEqual(predict(v,b,profiles(),12,False),32)
        v=View('E',True,(Pending(a,1,'executing',x=10),),None,1,a.reservation,None,None)
        p=profiles(transport={('E',65536):(8,0,1)})
        self.assertEqual(predict(v,b,p,10),31) # upload overlaps busy [10,20]

    def test_rr_ties_and_no_eligibility(self):
        l=Ledger(k=1);ready(l);task=Task(1,*CLASSES[0]);s=Snapshot(task,l.views(),profiles(),('F','C','E'))
        for policy in ('rr','compute_ect','network_ect'):
            self.assertEqual(choose(policy,s,0,k=1)[0],'F')
        with self.assertRaises(FrozenInstanceError):s.task=Task(2,*CLASSES[0])
        for i,j in enumerate(WORKERS):
            t=Task(i+2,*CLASSES[0]);l.admit(t);l.commit(t.id,j)
        self.assertEqual(choose('rr',Snapshot(task,l.views(),profiles()),0,k=1),(None,0,()))

    def test_network_and_queue_adversaries(self):
        task=Task(9,*CLASSES[0]);l=Ledger();ready(l)
        p=profiles(service={'E':20,'F':30,'C':1},transport={('C',65536):(100,0,30)})
        s=Snapshot(task,l.views(),p)
        self.assertEqual(choose('compute_ect',s,0)[0],'C')
        self.assertEqual(choose('network_ect',s,0)[0],'E')
        a=Task(1,*CLASSES[0]);l.admit(a);l.commit(1,'F')
        s=Snapshot(task,l.views(),profiles(service={'E':20,'F':2,'C':100}))
        self.assertEqual(choose('compute_ect',s,0)[0],'F') # longer queue, shorter predicted finish

    def test_exact_telescope(self):
        r=dict(zip(('a','g','b','c','d','e','f','x','y','z'),(0,0,1,3,4,5,15,25,45,50)))
        self.assertEqual(timing_components(r),(0,1,2,1,1,10,10,20,5))
        r['x']=14
        with self.assertRaises(ValueError):timing_components(r)

class Framing(unittest.IsolatedAsyncioTestCase):
    async def test_truncated_oversized_nonobject(self):
        for data in (b'\0\0\0\x02{}',b'\0\x03\0\0',b'\0\0\0\x02[]',b'\0\0\0\x05{}'):
            r=asyncio.StreamReader();r.feed_data(data);r.feed_eof()
            if data==b'\0\0\0\x02{}':self.assertEqual(await wire.read(r),{})
            else:
                with self.assertRaises((ValueError,asyncio.IncompleteReadError)):await wire.read(r)


class GlobalFIFO(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        from pathlib import Path
        from dataclasses import asdict
        from madt_scheduling.orchestrator import Orchestrator
        self.temp=tempfile.TemporaryDirectory(prefix='ehu-offline-contract-')
        cfg=dict(run_id='offline',output=str(Path(self.temp.name)/'source'),kind='local-test',
                 tasks=[asdict(t) for t in trace(4)],profiles=dict(
                 service={j:{f'{w}:{b}':10 for w,b in CLASSES} for j in WORKERS},
                 transport={j:{str(b):[0,0,0] for b in (65536,1048576)} for j in WORKERS}),
                 warmup_repetitions=0,credits=1,global_capacity=2)
        self.app=Orchestrator(cfg);ready(self.app.ledger)

    async def asyncTearDown(self):
        self.app.log.close();self.temp.cleanup()

    async def test_head_waits_without_decision_or_cursor_advance(self):
        a,b=self.app.tasks[:2]
        self.app.release(a,0,'scored','E');self.app.release(b,0,'scored','E')
        dispatcher=asyncio.create_task(self.app.dispatch())
        try:
            await self.app.until(lambda:self.app.rows[a.id].get('worker')=='E',2)
            await asyncio.sleep(0)
            self.assertNotIn('g',self.app.rows[b.id]);self.assertEqual(list(self.app.global_fifo),[b]);self.assertEqual(self.app.cursor,0)
            sent=self.app.sender['E'].get_nowait();self.assertEqual(sent.id,a.id)
            self.app.ledger.uploading(a.id,0);self.app.ledger.ack('E',a.id,0,0);self.app.ledger.complete('E',a.id,True,f=0,x=0,y=0,receipt=0)
            self.app.changed.set()
            await self.app.until(lambda:self.app.rows[b.id].get('worker')=='E',2)
            self.assertFalse(self.app.global_fifo)
        finally:
            dispatcher.cancel();await asyncio.gather(dispatcher,return_exceptions=True)

    async def test_bounded_global_admission_and_impossible_head(self):
        a,b,c=self.app.tasks[:3]
        self.app.release(a,0,'scored');self.app.release(b,0,'scored');self.app.release(c,0,'scored')
        self.assertEqual(self.app.rows[c.id]['outcome'],'rejected')
        self.assertEqual(len(self.app.global_fifo),2)
        self.app.ledger.memory=1
        dispatcher=asyncio.create_task(self.app.dispatch())
        try:
            await self.app.until(lambda:not self.app.global_fifo,2)
            self.assertTrue(all(self.app.rows[t.id]['outcome']=='rejected' for t in (a,b)))
            self.assertTrue(all(v.credits==0 for v in self.app.ledger.views()))
        finally:
            dispatcher.cancel();await asyncio.gather(dispatcher,return_exceptions=True)

if __name__=='__main__':unittest.main()
