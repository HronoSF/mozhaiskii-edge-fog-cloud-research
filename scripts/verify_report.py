#!/usr/bin/env python3
"""Compare a rebuilt report's content/layout invariants with the frozen PDF."""
import argparse
import hashlib
from pathlib import Path
import re
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT/'report/UPV-EHU_Scheduling_Report_A01-A03.pdf'


def require(value, message):
    if not value:raise ValueError(message)


def fonts(resources):
    for font in resources.get('/Font', {}).values():
        f = font.get_object()
        for item in f.get('/DescendantFonts', [f]):
            descriptor = item.get_object().get('/FontDescriptor')
            require(descriptor is not None, 'Missing font descriptor')
            descriptor = descriptor.get_object()
            require(any(k in descriptor for k in ['/FontFile','/FontFile2','/FontFile3']), 'Unembedded font')
    for form in resources.get('/XObject', {}).values():
        r = form.get_object().get('/Resources')
        if r:fonts(r)


def uris(reader):
    return sorted(a.get_object()['/A']['/URI'] for p in reader.pages for a in p.get('/Annots', [])
                  if a.get_object().get('/A', {}).get('/URI'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    args=parser.parse_args()
    old,new=PdfReader(CANONICAL),PdfReader(args.pdf)
    require(len(new.pages)==len(old.pages)==9, 'Report must remain nine pages')
    for a,b in zip(old.pages,new.pages):
        require(a.mediabox==b.mediabox,'Changed page geometry')
        require(a.extract_text()==b.extract_text(),'Extracted page text differs; inspect toolchain before accepting build')
        fonts(b['/Resources'])
    require(uris(old)==uris(new),'Changed external links')
    labels={}
    for line in (ROOT/'build/scheduling-report.aux').read_text().splitlines():
        match=re.search(r'newlabel\{table:([^:]+):(start|end)\}.*?\}\}\{(\d+)\}',line)
        if match:labels.setdefault(match[1],{})[match[2]]=int(match[3])
    require(len(labels)==9 and all(v['start']==v['end'] for v in labels.values()),'Missing or split table')
    log=(ROOT/'build/scheduling-report.log').read_text()
    require('Overfull' not in log,'Overfull box; inspect layout')
    same=hashlib.sha256(CANONICAL.read_bytes()).digest()==hashlib.sha256(args.pdf.read_bytes()).digest()
    print('PASS: nine pages, exact page text/geometry, whole tables, embedded fonts and unchanged links.')
    print('PDF bytes: '+('identical' if same else 'different; PDF metadata/object encoding can differ. Visual page comparison is still required.'))


if __name__=='__main__':main()
