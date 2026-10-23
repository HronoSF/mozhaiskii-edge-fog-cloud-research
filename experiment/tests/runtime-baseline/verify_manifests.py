"""Guest acquisition gate only; never changes packages or experiment thresholds."""
import argparse, hashlib, json
from pathlib import Path

def entries(text, separator):
    rows=[line.split(separator,1) for line in text.splitlines() if line]
    if not rows or any(len(row)!=2 or not all(row) for row in rows):raise ValueError('Malformed package manifest')
    if len({r[0] for r in rows})!=len(rows):raise ValueError('Duplicate package')
    return dict(rows)

def differences(expected, actual, separator):
    a,b=entries(expected,separator),entries(actual,separator)
    return {k:dict(expected=a.get(k),actual=b.get(k)) for k in sorted(a.keys()|b.keys()) if a.get(k)!=b.get(k)}

def main():
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['guest','endpoint']);a=p.parse_args()
    root=Path('/opt/ehu-madt');baseline=root/'runtime-baseline';checks={}
    for name,sep in ([('python-lock.txt','=='),('debian-packages.txt','\t')] if a.kind=='guest' else [('endpoint-packages.txt','\t')]):
        checks[name]=differences((baseline/name).read_text(),(root/name).read_text(),sep)
    report=dict(kind=a.kind,passed=not any(checks.values()),differences=checks)
    (baseline/(a.kind+'-check.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
