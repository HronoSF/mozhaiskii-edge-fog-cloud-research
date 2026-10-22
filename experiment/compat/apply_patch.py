#!/usr/bin/env python3
"""Apply a hash-checked tcconfig 0.30.1 compatibility patch in a root Linux guest."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if sys.platform!='linux' or os.geteuid()!=0:
        raise RuntimeError('Dedicated root Linux guest required')
    if importlib.metadata.version('tcconfig')!='0.30.1':
        raise RuntimeError('Unexpected tcconfig version')
    import tcconfig
    base=Path(tcconfig.__file__).resolve().parent.parent
    here=Path(__file__).resolve().parent
    expected=json.loads((here/'original-hashes.json').read_text())
    patch=here/'tcconfig-0.30.1-docker28.patch'
    original={name:(base/name).read_bytes() for name in expected}
    for name,sha in expected.items():
        if hashlib.sha256(original[name]).hexdigest()!=sha:
            raise RuntimeError('Unexpected/already modified dependency: '+name)
    args.output.mkdir(parents=True,exist_ok=False)
    for name,data in original.items():
        dest=args.output/'original'/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(data)
    shutil.copy2(patch,args.output/'applied.patch')
    subprocess.run(['git','apply','--check',str(patch)],cwd=base,check=True)
    subprocess.run(['git','apply',str(patch)],cwd=base,check=True)
    after={}
    for name in expected:
        data=(base/name).read_bytes()
        compile(data,str(base/name),'exec')
        after[name]=hashlib.sha256(data).hexdigest()
        # Source length/timestamps must not leave an old bytecode cache usable.
        cache=(base/name).parent/'__pycache__'
        for old in cache.glob(Path(name).stem+'.*.pyc'):
            old.unlink()
    result=dict(original_sha256=expected,adapted_sha256=after,
        patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
        upstream_candidate='https://github.com/thombashi/tcconfig/pull/199',
        upstream_candidate_sha='68f810765f2e7150935fa95a631897372b05b467',
        scope='Docker28 only; upstream uniqueness repair plus namespace key, reciprocal checks and failure propagation')
    (args.output/'provenance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
