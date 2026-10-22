#!/usr/bin/env python3
"""Export fixed reviewed measurement tables; no collection or host identifiers."""
import argparse,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(root,name):
    with (root/name).open(newline='') as f:return list(csv.DictReader(f,delimiter='\t'))
def write(name,rows):
    with (ROOT/'data'/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True,help='Directory containing the reviewed tables/ and derived/ TSVs');a=p.parse_args()
    cells=read(a.source,'tables/cells.tsv');assert len(cells)==36
    contexts={(r['slot'],r['cell']):r for r in cells};assert len(contexts)==36
    public=[]
    for r in cells:
        d={'slot':r['slot'],'cell':r['cell'],'arrival_pattern':r['planned_scenario'],'network_condition':r['planned_network'],'scheduler':r['planned_policy']}
        d.update({k:v for k,v in r.items() if k not in ('slot','cell','slot_state','planned_scenario','planned_network','planned_policy','source','policy','original_cell_status','source_status','task_rows_observed')})
        public.append(d)
    write('scenario-results.csv',public)
    tasks=[r for r in read(a.source,'tables/offered-tasks.tsv') if r['phase']=='scored'];assert len(tasks)==432
    origins={key:min(int(r['a_star']) for r in tasks if (r['slot'],r['cell'])==key) for key in contexts}
    out=[]
    timing=['response_scheduled_ns','response_release_ns','release_lag_ns','global_queue_ns','observation_ns','decision_wall_ns','decision_cpu_ns','commit_ns','sender_queue_ns','input_delivery_ns','worker_queue_ns','execution_wall_ns','cpu_ns','result_delivery_ns']
    for r in tasks:
        key=(r['slot'],r['cell']);c=contexts[key];origin=origins[key]
        d=dict(slot=r['slot'],cell=r['cell'],arrival_pattern=c['planned_scenario'],network_condition=c['planned_network'],scheduler=c['planned_policy'],task_id=r['id'],worker=r['worker'],outcome=r['outcome'],on_time=r['on_time'],deadline_ns=1000000000)
        for name,column in [('planned_release_offset_ns','a_star'),('actual_release_offset_ns','a'),('verified_response_offset_ns','z')]:d[name]=int(r[column])-origin
        d.update({k:r[k] for k in timing})
        components=['release_lag_ns','global_queue_ns','observation_ns','decision_wall_ns','commit_ns','sender_queue_ns','input_delivery_ns','worker_queue_ns','execution_wall_ns','result_delivery_ns']
        assert sum(int(r[k]) for k in components)==int(r['response_scheduled_ns'])
        assert d['verified_response_offset_ns']-d['planned_release_offset_ns']==int(r['response_scheduled_ns'])
        out.append(d)
    assert sum(r['on_time']=='True' for r in out)==431
    write('scored-tasks.csv',out)
    write('node-results.csv',read(a.source,'derived/all-nodes.tsv'))
    workers=read(a.source,'derived/all-worker-completions.tsv')
    write('worker-completions.csv',[{k:v for k,v in r.items() if k not in ('source_member','worker_member')} for r in workers])
    sessions=read(a.source,'derived/session-results.tsv');net=read(a.source,'derived/network-cycles.tsv');out=[]
    for r in sessions:
        d={k:v for k,v in r.items() if k not in ('boot_id','preservation_sha256','execution_sha','export_sha256','export_members')}
        for phase in ['health','application']:
            delay=next(x for x in net if x['slot']==r['slot'] and x['qualification']==phase and x['kind']=='delay')
            rate=next(x for x in net if x['slot']==r['slot'] and x['qualification']==phase and x['kind']=='rate')
            for field in ['forward_increment_ms','reverse_increment_ms']:d[phase+'_'+field]=delay[field]
            d[phase+'_impaired_receive_mbps']=rate['impaired_receive_mbps']
        out.append(d)
    write('session-results.csv',out)
    print('Exported36cells/432scored/2844worker outputs/3sessions; timestamps are cell-relative, all sequential components exact.')
if __name__=='__main__':main()
