#!/usr/bin/env python3
"""Build data tables and versioned XeLaTeX body without altering the shared style."""
import csv,subprocess,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(n):
    with (ROOT/'data'/n).open(newline='') as f:return list(csv.DictReader(f))
def esc(v):return str(v).replace('&',r'\&').replace('%',r'\%').replace('_',r'\_')
def table(name,headers,rows,align):
    # A table float using tabular is indivisible; H places it here or wholly on the next page.
    lines=[r'\begin{table}[H]',r'\centering',r'\label{table:'+name+':start}',r'\begin{tabular}{'+align+'}',r'\toprule',' & '.join(r'\textbf{'+esc(x)+'}' for x in headers)+r' \\',r'\midrule']
    lines+=[' & '.join(esc(x) for x in row)+r' \\' for row in rows]
    lines += [r'\bottomrule',r'\end{tabular}',r'\label{table:'+name+':end}',r'\end{table}']
    (ROOT/'report/tables'/f'{name}.tex').write_text('\n'.join(lines)+'\n')
def main():
    (ROOT/'report/tables').mkdir(exist_ok=True)
    (ROOT/'build/figures').mkdir(parents=True,exist_ok=True)
    table('topology',['Container','What it does','CPU quota'],[['Gateway / orchestrator','Receives tasks and selects workers','0.50 CPU'],['Edge worker','Executes tasks locally','0.25 CPU'],['Fog worker','Executes tasks and forwards Cloud traffic','0.50 CPU'],['Cloud worker','Executes tasks after traffic passes through Fog','1.00 CPU']],r'p{0.24\linewidth}p{0.54\linewidth}r')
    cells=read('scenario-results.csv');sessions=read('session-results.csv');nodes=read('node-results.csv')
    labels={'rr':'Round Robin','compute_ect':'Compute-ECT','network_ect':'Network-ECT'}
    def selected(arr,net,policy):
        rows=sorted((r for r in cells if r['arrival_pattern']==arr and r['network_condition']==net and r['scheduler']==policy),key=lambda r:r['slot'])
        assert [r['slot'] for r in rows]==['A01','A02','A03'];return rows
    def stats(arr,net,policy):
        rows=selected(arr,net,policy)
        return [f"{float(r['response_scheduled_ns_median'])/1e6:.1f}" for r in rows]+[f"{sum(int(r['on_time']) for r in rows)}/36"]
    for name,arr,net in [('example-a','steady','unshaped'),('example-b','burst','unshaped'),('example-c','burst','delay20')]:
        table(name,['Scheduler','Run 1 (ms)','Run 2 (ms)','Run 3 (ms)','On time'],[[labels[p],*stats(arr,net,p)] for p in labels],'lrrrr')
    rows=[]
    for arr in ['steady','burst']:
        for net in ['unshaped','delay20']:
            for p in labels:rows.append([arr.title(),'Normal' if net=='unshaped' else '+20 ms',labels[p],*stats(arr,net,p)])
    table('all-scenarios',['Arrival','Network','Scheduler','Run 1','Run 2','Run 3','On time'],rows,'lllrrrr')
    table('stages',['Stage','Per VM','What it checks'],[
        ['Calibration','72','Estimate worker and transfer times'],['Queue check','12','Confirm waiting behind busy workers'],['Warmup','720','Prepare every scenario equally'],['Main comparison','144','12 scenarios with 12 scored tasks each'],['Total real work','948','Includes preparation and scored work']],'lrl')
    table('sessions',['Session','Application','Network','Correct outputs','Scored on time'],[[r['slot'].replace('A0','Run '),'Complete',r['network'],r['worker_results'],r['on_time']+'/144'] for r in sessions],'lllrr')
    rows=[]
    for s in ['A01','A02','A03']:
        ns={r['node']:r for r in nodes if r['slot']==s}
        rows.append([s.replace('A0','Run '),ns['G']['all_source_decisions']+' / '+ns['G']['scored_source_decisions'],*[ns[w]['all_worker_outputs']+' ('+ns[w]['scored_worker_outputs']+')' for w in ['E','F','C']]])
    table('nodes',['Session','G all / scored','Edge','Fog','Cloud'],rows,'lrrrr')
    table('network',['Session','Forward delta (ms)','Reverse delta (ms)','Limited rate (Mbps)'],[[r['slot'].replace('A0','Run '),f"{float(r['application_forward_increment_ms']):.3f}",f"{float(r['application_reverse_increment_ms']):.3f}",f"{float(r['application_impaired_receive_mbps']):.3f}"] for r in sessions],'lrrr')
    import cairosvg
    shutil.copyfile(ROOT/'figures/topology.png',ROOT/'build/figures/topology.png')
    for name in ['median-latency','decision-overhead','task-timeline']:
        cairosvg.svg2pdf(url=str(ROOT/'figures'/f'{name}.svg'),write_to=str(ROOT/'build/figures'/f'{name}.pdf'))
    text=(ROOT/'report/scheduling-report.md').read_text().replace('../figures/','build/figures/').replace('.svg)', '.pdf){width=100%}').replace('.png)', '.png){width=100%}')
    body=subprocess.check_output(['pandoc','-f','markdown-smart','-t','latex'],input=text,text=True,cwd=ROOT)
    body=body.replace(r'\begin{figure}',r'\begin{figure}[H]')
    template=(ROOT/'latex/research-report.tex').read_text()
    metadata=r'\hypersetup{pdftitle={Scheduling tasks across different computing resources},pdfauthor={Gleb Mozhaiskii}}'+'\n'
    (ROOT/'report/scheduling-report.tex').write_text(template.replace('$body$',metadata+body))
    print('Built9indivisible tables,3vector charts,the original topology image and versioned LaTeX; shared style unchanged.')
if __name__=='__main__':main()
