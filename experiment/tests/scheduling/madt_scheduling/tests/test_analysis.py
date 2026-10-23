"""Offline raw-event corruption checks; no worker/network behavior is replaced."""
import json
from pathlib import Path
import tempfile
import unittest
from madt_scheduling.analyze import inspect
from madt_scheduling.core import WORKERS, timing_components


class RawEvidence(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ehu-analysis-contract-')
        self.root=Path(self.temp.name)
        self.rows=[]
        for task_id,f,x,y in ((1,10,20,30),(2,25,30,40)):
            row=dict(id=task_id,phase='scored',worker='E',sequence=task_id,
                     outcome='completed',a_star=0,a=0,g=1,b=2,c=3,d=4,e=5,
                     f=f,x=x,y=y,z=y+2,cpu_ns=5,on_time=True)
            row['components_ns']=list(timing_components(row));self.rows.append(row)
        self.events={j:[] for j in WORKERS}
        for row in self.rows:
            self.events['E'].append(dict(event='input_admitted',id=row['id'],f=row['f'],sequence=row['sequence']))
        for row in self.rows:
            self.events['E'].append(dict(event='execution_ended',id=row['id'],x=row['x'],y=row['y'],cpu_ns=row['cpu_ns']))

    def tearDown(self):
        self.temp.cleanup()

    def analyze(self):
        (self.root/'source').mkdir(exist_ok=True)
        (self.root/'source/tasks.json').write_text(json.dumps(self.rows))
        outcomes={k:sum(r['outcome']==k for r in self.rows) for k in ('completed','rejected','failed','unresolved','not_released')}
        (self.root/'source/summary.json').write_text(json.dumps(dict(outcomes=outcomes,offered=2,errors=[],policy='rr',kind='local-test',on_time=2)))
        for j in WORKERS:
            (self.root/j).mkdir(exist_ok=True)
            (self.root/j/'summary.json').write_text(json.dumps(dict(errors=[],remaining=0)))
            (self.root/j/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in self.events[j]))
        return inspect(self.root)

    def test_valid_fifo_and_queue_overlap(self):
        result=self.analyze()
        self.assertEqual(result['instrument_checks'],'PASSED')
        self.assertEqual(len(result['actual_local_queue_while_uploading']['E']),1)

    def test_reordered_execution_is_detected(self):
        # Internally consistent per-task timestamps, single CPU, but violated FIFO.
        self.rows[1].update(f=11,x=20,y=30,z=32)
        self.rows[0].update(x=30,y=40,z=42)
        for row in self.rows:row['components_ns']=list(timing_components(row))
        self.events['E']=[dict(event='input_admitted',id=r['id'],f=r['f'],sequence=r['sequence']) for r in self.rows]
        self.events['E'] += [dict(event='execution_ended',id=r['id'],x=r['x'],y=r['y'],cpu_ns=r['cpu_ns']) for r in reversed(self.rows)]
        self.assertEqual(self.analyze()['instrument_checks'],'FAILED')

    def test_extra_unassigned_admission_and_execution_are_detected(self):
        self.events['C']=[dict(event='input_admitted',id=99,f=5,sequence=1),
                          dict(event='execution_ended',id=99,x=6,y=7,cpu_ns=1)]
        self.assertEqual(self.analyze()['instrument_checks'],'FAILED')
