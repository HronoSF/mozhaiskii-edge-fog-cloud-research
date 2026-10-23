"""Recompute per-ID correctness from saved source records and worker events."""
import argparse
import json
from pathlib import Path
from .core import WORKERS,timing_components


def inspect(directory):
    directory=Path(directory);rows=json.loads((directory/'source/tasks.json').read_text())
    summary=json.loads((directory/'source/summary.json').read_text());errors=[];queue_overlap={};counts={}
    if len({r['id'] for r in rows})!=len(rows):errors.append('Repeated source IDs')
    for j in WORKERS:
        worker_summary=json.loads((directory/j/'summary.json').read_text())
        if worker_summary['errors'] or (worker_summary['remaining'] and not worker_summary.get('censored_shutdown')):errors.append(f'{j}: worker not clean: {worker_summary}')
        events=[json.loads(line) for line in (directory/j/'events.jsonl').read_text().splitlines()]
        admissions=[e for e in events if e['event']=='input_admitted'];ends=[e for e in events if e['event']=='execution_ended']
        if len({r['id'] for r in admissions})!=len(admissions):errors.append(f'{j}: duplicate admission')
        assigned={r['id']:r for r in rows if r.get('worker')==j}
        admission_ids=[r['id'] for r in admissions]
        ended_ids=[r['id'] for r in ends]
        if len(set(ended_ids))!=len(ended_ids):errors.append(f'{j}: duplicate execution')
        if any(i not in assigned for i in admission_ids):errors.append(f'{j}: unassigned raw admission')
        if any(i not in admission_ids for i in ended_ids):errors.append(f'{j}: execution without admission')
        sequences=[r['sequence'] for r in admissions]
        if sequences!=list(range(1,len(admissions)+1)):errors.append(f'{j}: non-FIFO admission sequence')
        for admission in admissions:
            row=assigned.get(admission['id'])
            if row is not None and row.get('sequence')!=admission['sequence']:
                errors.append(f'{j}: changed commitment sequence')
        ordered=sorted(ends,key=lambda r:r['x']);queue_overlap[j]=[]
        # Censored work may leave only an executed prefix, never a skipped FIFO head.
        if [r['id'] for r in ordered]!=admission_ids[:len(ordered)]:errors.append(f'{j}: non-FIFO execution')
        for a,b in zip(ordered,ordered[1:]):
            if b['x']<a['y']:errors.append(f'{j}: overlapping CPU execution')
        for row in rows:
            if row.get('worker')==j and row['outcome']=='completed':
                matching=[e for e in ends if e['id']==row['id']]
                admitted=[e for e in admissions if e['id']==row['id']]
                if len(matching)!=1 or len(admitted)!=1:errors.append(f'{j}: missing/duplicate raw worker task {row["id"]}');continue
                if any(row[k]!=matching[0][k] for k in ('x','y','cpu_ns')) or row['f']!=admitted[0]['f']:errors.append('Changed timestamp/CPU evidence')
                timing_components(row)
                if row['components_ns']!=list(timing_components(row)):errors.append('Invalid additive components')
                for previous in ordered:
                    if previous['id']!=row['id'] and previous['x']<=row['f']<previous['y'] and row['e']<previous['y']:
                        queue_overlap[j].append(dict(queued=row['id'],running=previous['id'],f=row['f'],previous_y=previous['y'],wait_ns=row['x']-row['f']))
    scored=[r for r in rows if r['phase']=='scored']
    for key in ('completed','rejected','failed','unresolved','not_released'):counts[key]=sum(r['outcome']==key for r in scored)
    if counts!=summary['outcomes'] or sum(counts.values())!=summary['offered']:errors.append('Outcome conservation mismatch')
    if summary['errors']:errors.extend(summary['errors'])
    return dict(instrument_checks='PASSED' if not errors else 'FAILED',errors=errors,scope='correctness, not performance superiority',
                policy=summary['policy'],kind=summary['kind'],offered=summary['offered'],outcomes=counts,
                on_time=summary['on_time'],actual_local_queue_while_uploading=queue_overlap,
                completed_latencies_ns=[r['z']-r['a_star'] for r in scored if r['outcome']=='completed'])


def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();r=inspect(a.directory)
    print(json.dumps(r,indent=2));raise SystemExit(0 if r['instrument_checks']=='PASSED' else 1)

if __name__=='__main__':main()
