#!/usr/bin/env python3
"""Render publication SVGs from the checked-in public CSV files only."""
import csv
from pathlib import Path
from xml.sax.saxutils import escape
R=Path(__file__).resolve().parents[1]
COL={'rr':'#466A9A','compute_ect':'#C28A37','network_ect':'#258579'}
LABEL={'rr':'Round Robin','compute_ect':'Compute-ECT','network_ect':'Network-ECT'}
def rows(p):
 with (R/'data'/p).open(newline='') as f:return list(csv.DictReader(f))
def start(w,h,title):return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="white"/><text x="40" y="38" font-family="Georgia,serif" font-size="24" fill="#222">{escape(title)}</text>']
def txt(x,y,s,size=16,anchor='start',color='#222'):return f'<text x="{x}" y="{y}" font-family="Georgia,serif" font-size="{size}" text-anchor="{anchor}" fill="{color}">{escape(str(s))}</text>'
def save(n,p): (R/'figures'/n).write_text('\n'.join(p+['</svg>'])+'\n')

cells=rows('scenario-results.csv')
assert len(cells)==36
contexts=[('steady','unshaped','Steady / normal'),('steady','delay20','Steady / +20 ms'),('burst','unshaped','Burst / normal'),('burst','delay20','Burst / +20 ms')]
policies=['rr','compute_ect','network_ect']
def marker(x,y,k,color):
 if k==0:return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{color}"/>'
 if k==1:return f'<rect x="{x-5:.2f}" y="{y-5:.2f}" width="10" height="10" fill="{color}"/>'
 return f'<path d="M{x:.2f},{y-6:.2f} L{x-6:.2f},{y+5:.2f} L{x+6:.2f},{y+5:.2f} Z" fill="{color}"/>'
def compact_chart(filename,title,metric,divisor,maxv,step,axis_label):
 W,H=1300,755;left,right,top=350,1190,122
 p=start(W,H,title)
 for k,slot in enumerate(['A01','A02','A03']):
  x=450+k*235;p.append(marker(x,73,k,'#444'));p.append(txt(x+18,79,slot.replace('A0','Run '),19))
 for tick in range(0,maxv+1,step):
  x=left+(right-left)*tick/maxv;p.append(f'<line x1="{x}" y1="105" x2="{x}" y2="650" stroke="#d7dade"/>');p.append(txt(x,676,tick,18,'middle'))
 for i,(arr,net,label) in enumerate(contexts):
  for j,policy in enumerate(policies):
   rr=sorted([r for r in cells if r['arrival_pattern']==arr and r['network_condition']==net and r['scheduler']==policy],key=lambda r:r['slot'])
   assert [r['slot'] for r in rr]==['A01','A02','A03']
   vals=[float(r[metric])/divisor for r in rr];y=top+(i*3+j)*43+i*9+15
   p.append(txt(left-12,y+6,label+' - '+LABEL[policy],18,'end'))
   p.append(f'<line x1="{left+(right-left)*min(vals)/maxv:.2f}" y1="{y}" x2="{left+(right-left)*max(vals)/maxv:.2f}" y2="{y}" stroke="{COL[policy]}" stroke-width="2"/>')
   for k,v in enumerate(vals):p.append(marker(left+(right-left)*v/maxv,y+(k-1)*10,k,COL[policy]))
  if i<3:
   yy=top+(i+1)*3*43+i*9-5;p.append(f'<line x1="{left}" y1="{yy}" x2="{right}" y2="{yy}" stroke="#a4a9b0"/>')
 p.append(txt((left+right)/2,718,axis_label,21,'middle'));save(filename,p)
compact_chart('median-latency.svg','Task response times across three fresh VM runs','response_scheduled_ns_median',1e6,300,50,'Task response time (ms)')
compact_chart('decision-overhead.svg','Time spent making the scheduling decision','decision_wall_ns_median',1000,180,30,'Scheduling decision time (microseconds)')

# The reference report uses two plain serif panels, not a dashboard illustration.
tasks=[r for r in rows('scored-tasks.csv') if r['slot']=='A03' and r['arrival_pattern']=='burst' and r['network_condition']=='unshaped' and r['scheduler']=='rr']
assert len(tasks)==12
ordered=[r for worker in ('E','F','C') for r in sorted((t for t in tasks if t['worker']==worker),key=lambda t:int(t['task_id']))]
W,H=1300,1000;left,right=180,1200
p=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Run 3 Round Robin burst tasks: planned releases and execution intervals above; measured response-time stages below."><rect width="100%" height="100%" fill="white"/>']
def ttext(x,y,value,size=19,anchor='start',color='#333'):
 return f'<text x="{x}" y="{y}" font-family="Times New Roman,serif" font-size="{size}" text-anchor="{anchor}" fill="{color}">{escape(str(value))}</text>'
def line(x1,y1,x2,y2,color='#d7dade',dash=''):
 return f'<line x1="{x1:.5f}" y1="{y1:.5f}" x2="{x2:.5f}" y2="{y2:.5f}" stroke="{color}" stroke-width="1"'+(f' stroke-dasharray="{dash}"' if dash else '')+'/>'
def topx(ms):return left+(right-left)*ms/6000
p.append(ttext((left+right)/2,35,'a. Planned releases (circles) and execution intervals (bars)',24,'middle'))
for tick in range(7):
 x=topx(tick*1000);p.append(line(x,65,x,260));p.append(ttext(x,287,f'{tick} s',18,'middle'))
colors={'E':'#1e7c83','F':'#b07837','C':'#6355a4'}
for j,worker in enumerate(('E','F','C')):
 y=90+j*70;p.append(line(left,y+22,right,y+22));p.append(ttext(left-14,y+20,{'E':'EDGE','F':'FOG','C':'CLOUD'}[worker],20,'end'))
 for r in [q for q in ordered if q['worker']==worker]:
  planned=int(r['planned_release_offset_ns'])/1e6
  preceding=sum(int(r[k]) for k in ['release_lag_ns','global_queue_ns','observation_ns','decision_wall_ns','commit_ns','sender_queue_ns','input_delivery_ns','worker_queue_ns'])/1e6
  execution_start=planned+preceding;execution_end=execution_start+int(r['execution_wall_ns'])/1e6
  assert execution_end<=6000
  p.append(f'<circle cx="{topx(planned):.5f}" cy="{y+10}" r="4" fill="white" stroke="{colors[worker]}"/>')
  p.append(f'<rect x="{topx(execution_start):.5f}" y="{y}" width="{topx(execution_end)-topx(execution_start):.5f}" height="20" fill="{colors[worker]}"/>')
  p.append(ttext(topx(execution_start),y-5,r['task_id'],16))
p.append(ttext((left+right)/2,320,'Time since the first scheduled task',20,'middle'))
p.append(ttext((left+right)/2,367,'b. The same tasks: elapsed response time by measured stage',24,'middle'))
limit=1100
def lowx(ms):return left+(right-left)*ms/limit
for tick in range(0,1101,200):
 x=lowx(tick);p.append(line(x,390,x,888));p.append(ttext(x,915,tick,18,'middle'))
groups=[(['release_lag_ns','global_queue_ns','observation_ns','decision_wall_ns','commit_ns','sender_queue_ns'],'Gateway / sender','#9aa5af'),(['input_delivery_ns'],'Input transfer','#3a83b7'),(['worker_queue_ns'],'Worker queue','#d6a24b'),(['execution_wall_ns'],'Execution','#6757a8'),(['result_delivery_ns'],'Result return','#2d9487')]
for i,r in enumerate(ordered):
 y=405+i*38+(i//4)*13
 p.append(ttext(left-12,y+17,f"{r['worker']} - task {r['task_id']}",19,'end'))
 cur=0;total=0
 for fields,label,color in groups:
  ns=sum(int(r[k]) for k in fields);duration=ns/1e6
  if ns:p.append(f'<rect x="{lowx(cur):.5f}" y="{y}" width="{lowx(cur+duration)-lowx(cur):.5f}" height="23" fill="{color}"/>')
  total+=ns;cur+=duration
 assert total==int(r['response_scheduled_ns'])==int(r['verified_response_offset_ns'])-int(r['planned_release_offset_ns'])
 p.append(ttext(lowx(cur)+7,y+17,f'{cur:.3f}' if r['on_time']=='False' else f'{cur:.1f}',17,color='#b53f36' if r['on_time']=='False' else '#666'))
 if r['on_time']=='False':
  p.append(f'<rect x="{left}" y="{y-2}" width="{lowx(cur)-left:.5f}" height="27" fill="none" stroke="#b53f36" stroke-width="1.7"/>')
  p.append(ttext(right+10,y+17,'LATE',18,color='#b53f36'))
 if i in (3,7):p.append(line(left-15,y+33,right,y+33,'#b8bec7'))
p.append(line(lowx(1000),390,lowx(1000),888,'#b53f36','5 4'))
p.append(ttext((left+right)/2,945,'Task response time (ms); dashed line = 1 s deadline',21,'middle'))
for (fields,label,color),x in zip(groups,[180,420,660,875,1050]):
 p.append(f'<rect x="{x}" y="974" width="23" height="12" fill="{color}"/>');p.append(ttext(x+30,986,label,18))
p.append('</svg>');(R/'figures/task-timeline.svg').write_text('\n'.join(p)+'\n')
print('Rendered all three-run medians and the reference-style two-panel task timeline from unchanged CSVs.')
