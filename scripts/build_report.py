#!/usr/bin/env python3
"""Build data tables and versioned XeLaTeX body without altering the shared style."""
import csv,subprocess,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GENERATED=ROOT/'build/generated'
def read(n):
    with (ROOT/'data'/n).open(newline='') as f:return list(csv.DictReader(f))
def esc(v):return str(v).replace('&',r'\&').replace('%',r'\%').replace('_',r'\_')
def table(name,headers,rows,align,placements=None):
    # A table float using tabular is indivisible; H places it here or wholly on the next page.
    lines=[r'\begin{table}[H]',r'\centering',r'\label{table:'+name+':start}',r'\begin{tabular}{'+align+'}',r'\toprule',' & '.join(r'\textbf{'+esc(x)+'}' for x in headers)+r' \\',r'\midrule']
    lines+=[' & '.join(esc(x) for x in row)+r' \\' for row in rows]
    lines += [r'\bottomrule',r'\end{tabular}']
    if placements is not None:
        lines += [r'\par\smallskip',r'{\small Tasks assigned: Edge / Fog / Cloud (12 per run).}\par\smallskip',r'\begin{tabular}{lccc}',r'\toprule',r'\textbf{Scheduler} & \textbf{Run 1} & \textbf{Run 2} & \textbf{Run 3} \\',r'\midrule']
        lines += [' & '.join(esc(x) for x in row)+r' \\' for row in placements]
        lines += [r'\bottomrule',r'\end{tabular}']
    lines += [r'\label{table:'+name+':end}',r'\end{table}']
    (GENERATED/'report/tables'/f'{name}.tex').write_text('\n'.join(lines)+'\n')
def main():
    (GENERATED/'report/tables').mkdir(parents=True,exist_ok=True)
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
        placements=[[labels[p],*[' / '.join(r['placement_'+w] for w in ['E','F','C']) for r in selected(arr,net,p)]] for p in labels]
        table(name,['Scheduler','Run 1 (ms)','Run 2 (ms)','Run 3 (ms)','On time'],[[labels[p],*stats(arr,net,p)] for p in labels],'lrrrr',placements=placements)
    rows=[]
    for arr in ['steady','burst']:
        for net in ['unshaped','delay20']:
            for p in labels:rows.append([arr.title(),'Normal' if net=='unshaped' else '+20 ms',labels[p],*stats(arr,net,p)])
    table('all-scenarios',['Arrival','Network','Scheduler','Run 1','Run 2','Run 3','On time'],rows,'lllrrrr')
    table('stages',['Stage','Per VM','What it checks'],[
        ['Calibration','72','Estimate worker and transfer times'],['Queue check','12','Confirm waiting behind busy workers'],['Warmup','720','Prepare every scenario equally'],['Main comparison','144','12 scenarios with 12 scored tasks each'],['Total real work','948','Includes preparation and scored work']],'lrl')
    table('sessions',['Session','Application','Correct outputs','Scored on time'],[[r['slot'].replace('A0','Run '),'Complete',r['worker_results'],r['on_time']+'/144'] for r in sessions],'llrr')
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
    template=(ROOT/'latex/research-report.tex').read_text()
    def make_body(md, title, output):
        text=(ROOT/md).read_text().replace('../figures/','build/figures/').replace('.svg)', '.pdf){width=100%}').replace('.png)', '.png){width=100%}')
        body=subprocess.check_output(['pandoc','-f','markdown-smart','-t','latex'],input=text,text=True,cwd=ROOT)
        body=body.replace(r'\begin{figure}',r'\begin{figure}[H]')
        metadata=r'\hypersetup{pdftitle={'+title+r'},pdfauthor={Gleb Mozhaiskii}}'+'\n'
        path=GENERATED/'report'/output
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(template.replace('$body$',metadata+body))
    make_body('report/scheduling-report.md','Scheduling tasks across different computing resources','scheduling-report.tex')
    make_body('report/testbed-validation-note.md','Validation of an Edge-Fog-Cloud Scheduling Testbed','testbed-validation-note.tex')
    # The validation note's scenario summary combines the existing medians with
    # exact worker placements while retaining the original scenario ordering.
    cells=read('scenario-results.csv')
    scenario_rows=[]
    for arr in ['steady','burst']:
        for net in ['unshaped','delay20']:
            for policy in ['rr','compute_ect','network_ect']:
                runs=sorted((r for r in cells if r['arrival_pattern']==arr and r['network_condition']==net and r['scheduler']==policy),key=lambda r:r['slot'])
                assert [r['slot'] for r in runs]==['A01','A02','A03']
                run_cells=[]
                for r in runs:
                    latency=f"{float(r['response_scheduled_ns_median'])/1e6:.1f}"
                    counts=' / '.join(r['placement_'+w] for w in ['E','F','C'])
                    run_cells.append(r'\shortstack[r]{'+latency+r'\\'+counts+'}')
                scenario_rows.append([arr.title(),'Normal' if net=='unshaped' else '+20 ms',labels[policy],*run_cells,f"{sum(int(r['on_time']) for r in runs)}/36"])
    table('scenario-summary',['Arrival','Network','Scheduler','Run 1','Run 2','Run 3','On time'],scenario_rows,'lllrrrr')
    for name in ['report/scheduling-report.tex']+[f'report/tables/{p.name}' for p in (GENERATED/'report/tables').glob('*.tex') if p.name!='scenario-summary.tex']+[f'figures/{name}.svg' for name in ['median-latency','decision-overhead','task-timeline']]:
        if (GENERATED/name).read_bytes() != (ROOT/name).read_bytes():
            raise ValueError('Generated source differs from canonical source: '+name+'; inspect toolchain/content, do not overwrite the published report')
    if not (ROOT/'report/testbed-validation-note.md').exists():
        raise FileNotFoundError('report/testbed-validation-note.md is not available yet')
    if (GENERATED/'report/testbed-validation-note.tex').read_bytes() != (ROOT/'report/testbed-validation-note.tex').read_bytes():
        raise ValueError('Generated source differs from canonical source: report/testbed-validation-note.tex; copy the generated source after review')
    if (GENERATED/'report/tables/scenario-summary.tex').read_bytes() != (ROOT/'report/tables/scenario-summary.tex').read_bytes():
        raise ValueError('Generated source differs from canonical source: report/tables/scenario-summary.tex; copy the generated table after review')
    print('Verified original report inputs and generated the validation note body and scenario summary; shared style unchanged.')
if __name__=='__main__':main()
