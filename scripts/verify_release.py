#!/usr/bin/env python3
"""Check publication integrity and task/session conservation without a VM."""
import csv,hashlib,json,statistics
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def read(n):
    with (R/'data'/n).open(newline='') as f:return list(csv.DictReader(f))
def require(ok,why):
    if not ok:raise ValueError(why)
def main():
    manifest=json.loads((R/'experiment/INPUTS.sha256.json').read_text())
    require(len(manifest)==38,'effective input count')
    for n,h in manifest.items():require(hashlib.sha256((R/'experiment'/n).read_bytes()).hexdigest()==h,'changed measured source: '+n)
    cells=read('scenario-results.csv');tasks=read('scored-tasks.csv');sessions=read('session-results.csv');workers=read('worker-completions.csv');nodes=read('node-results.csv')
    require((len(cells),len(tasks),len(sessions),len(workers),len(nodes))==(36,432,3,2844,12),'cohort conservation')
    require({r['slot'] for r in sessions}=={'A01','A02','A03'},'slot identities')
    components=['release_lag_ns','global_queue_ns','observation_ns','decision_wall_ns','commit_ns','sender_queue_ns','input_delivery_ns','worker_queue_ns','execution_wall_ns','result_delivery_ns']
    for c in cells:
        subset=[r for r in tasks if (r['slot'],r['cell'])==(c['slot'],c['cell'])]
        require(len(subset)==12 and len({r['task_id'] for r in subset})==12,'scored cell identity/count')
        require(statistics.median(int(r['response_scheduled_ns']) for r in subset)==float(c['response_scheduled_ns_median']),'task-derived cell median')
        require(sum(r['on_time']=='True' for r in subset)==int(c['on_time']),'cell SLO count')
        for w in ['E','F','C']:require(sum(r['worker']==w for r in subset)==int(c['placement_'+w]),'cell placement')
    for r in tasks:
        response=int(r['response_scheduled_ns']);require(sum(int(r[k]) for k in components)==response,'timing telescope')
        require(int(r['verified_response_offset_ns'])-int(r['planned_release_offset_ns'])==response,'planned response clock')
        require(int(r['actual_release_offset_ns'])-int(r['planned_release_offset_ns'])==int(r['release_lag_ns']),'release lag clock')
        require((r['on_time']=='True')==(response<=int(r['deadline_ns'])),'planned arrival SLO')
    late=[r for r in tasks if r['on_time']=='False']
    require(len(late)==1 and (late[0]['slot'],late[0]['cell'],late[0]['task_id'],int(late[0]['response_scheduled_ns']))==('A03','6','6',1002317940),'sole adverse case')
    for s in sessions:
        slot=s['slot'];require(sum(r['slot']==slot for r in workers)==948,'all-worker session conservation')
        require(sum(r['slot']==slot for r in tasks)==144,'scored session conservation')
        require(s['application']=='COMPLETE' and s['network']=='IN_SPEC' and s['strict_final']=='True','recorded final classifications')
    for n in nodes:
        if n['node']=='G':continue
        require(sum(r['slot']==n['slot'] and r['worker']==n['node'] for r in workers)==int(n['all_worker_outputs']),'all-node output count')
    for p in (R/'report/tables').glob('*.tex'):
        s=p.read_text();require(r'\begin{table}[H]' in s and r'\begin{tabular}' in s and 'longtable' not in s,'indivisible table source')
    f=R/'MANIFEST.sha256'
    if f.exists():
        for line in f.read_text().splitlines():
            h,n=line.split('  ',1);require(hashlib.sha256((R/n).read_bytes()).hexdigest()==h,'release hash: '+n)
    print('Verified38input pins,3sessions,36cells,432scored tasks,2844worker outputs,all-node totals,timing identities,SLO miss and indivisible table sources; no VM started.')
if __name__=='__main__':main()
