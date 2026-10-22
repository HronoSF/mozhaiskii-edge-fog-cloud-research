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

# A03 burst/unshaped Round Robin scored tasks, on the original common timeline.
tasks=[r for r in rows('scored-tasks.csv') if r['slot']=='A03' and r['arrival_pattern']=='burst' and r['network_condition']=='unshaped' and r['scheduler']=='rr']
assert len(tasks)==12
stages=[('release_lag_ns','#409A86'),('global_queue_ns','#409A86'),('observation_ns','#3E84B4'),('decision_wall_ns','#3E84B4'),('commit_ns','#3E84B4'),('sender_queue_ns','#B49A4E'),('input_delivery_ns','#B49A4E'),('worker_queue_ns','#B49A4E'),('execution_wall_ns','#6658AD'),('result_delivery_ns','#83B1D7')]
W,H=1600,810;left,right,limit=280,1510,6500;top=157; p=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Run 3 Round Robin burst unshaped: twelve measured tasks grouped by Edge, Fog, and Cloud on a common timeline."><rect width="100%" height="100%" fill="white"/>']
p.append('<text x="48" y="55" font-family="Arial,sans-serif" font-size="32" font-weight="700" fill="#17283D">Where did the tasks spend their time?</text>')
p.append('<text x="48" y="87" font-family="Arial,sans-serif" font-size="20" fill="#52677D">Run 3 · Round Robin · burst arrivals · unshaped network · 12 scored tasks</text>')
def at(ms):return left+(right-left)*ms/limit
for tick in range(0,6501,1000):
 x=at(tick);p.append(f'<path d="M{x:.2f} 133 V654" stroke="#D4DEE7" stroke-dasharray="4 6"/>');p.append(f'<text x="{x:.2f}" y="687" font-family="Arial,sans-serif" font-size="17" fill="#51677C" text-anchor="middle">{tick//1000} s</text>')
groups=[('E','EDGE','#F0F8F6','#157F83'),('F','FOG','#FCF7EF','#B17B35'),('C','CLOUD','#F5F4FB','#6B5A9F')]
ordered=[]
for wi,(worker,label,bg,accent) in enumerate(groups):
 y0=129+wi*179;p.append(f'<rect x="30" y="{y0}" width="1538" height="167" rx="10" fill="{bg}"/>');p.append(f'<text x="55" y="{y0+29}" font-family="Arial,sans-serif" font-size="23" font-weight="700" fill="{accent}">{label}</text>')
 rr=sorted((r for r in tasks if r['worker']==worker),key=lambda q:int(q['task_id']));assert len(rr)==4
 for j,r in enumerate(rr):
  ordered.append(r);y=y0+43+j*31;p.append(f'<text x="154" y="{y+17}" font-family="Arial,sans-serif" font-size="18" fill="#33465A">Task {r["task_id"]}</text>')
  planned=int(r['planned_release_offset_ns'])/1e6;cur=planned
  total=0
  for col,color in stages:
   dur=int(r[col])/1e6; x=at(cur); x2=at(cur+dur); total+=int(r[col])
   if dur>0:p.append(f'<rect x="{x:.4f}" y="{y}" width="{x2-x:.4f}" height="19" fill="{color}"/>')
   cur+=dur
  response=int(r['verified_response_offset_ns'])-int(r['planned_release_offset_ns']);assert total==response,(r['task_id'],total,response)
  deadline=at(planned+1000);p.append(f'<path d="M{deadline:.2f} {y-4} V{y+24}" stroke="#B94537" stroke-width="1.5" stroke-dasharray="3 3"/>')
  if r['on_time']=='False':
   p.append(f'<circle cx="{at(cur):.2f}" cy="{y+9.5}" r="7" fill="#B94537" stroke="white" stroke-width="2"/>')
legend=[('#409A86','Gateway / release wait'),('#3E84B4','Observation, decision, commit'),('#B49A4E','Sender, input, worker queue'),('#6658AD','Execution'),('#83B1D7','Result return')]
positions=[52,330,700,1115,1295]
for (color,label),x in zip(legend,positions):p.append(f'<rect x="{x}" y="718" width="24" height="16" rx="3" fill="{color}"/><text x="{x+34}" y="733" font-family="Arial,sans-serif" font-size="17" fill="#33465A">{label}</text>')
p.append('<text x="50" y="777" font-family="Arial,sans-serif" font-size="18" fill="#51677C">Bars start at planned arrival; dashed red ticks mark each task deadline. Very short measured stages may not resolve at this scale.</text>')
p.append(f'<text x="1550" y="795" font-family="Arial,sans-serif" font-size="15" text-anchor="end" fill="#B94537">Task 6 / E: 1002.318 ms response vs 1000 ms deadline (miss)</text>')
p.append('</svg>');(R/'figures/task-timeline.svg').write_text('\n'.join(p)+'\n')
print('Rendered median latency, decision overhead, and task timeline from public CSVs.')
