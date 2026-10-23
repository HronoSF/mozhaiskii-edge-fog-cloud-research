#!/usr/bin/env python3
"""Real guest namespace/peer regressions; no substitute packet measurements."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if sys.platform!='linux' or os.geteuid()!=0:raise RuntimeError('Dedicated root Linux guest required')
    args.output.mkdir(parents=True,exist_ok=False)
    import docker
    from tcconfig._docker import DockerClient
    cli=docker.DockerClient(base_url='unix:///var/run/docker.sock',timeout=15)
    token='ehu-mapping-'+uuid.uuid4().hex[:12]
    key='org.ehu.madt.mapping-probe'
    resources=[]
    namespace_path=None
    namespace_target=None
    result={'status':'FAILED','cases':[],'cleanup_errors':[]}
    def save(name,data):(args.output/name).write_text(json.dumps(data,indent=2)+'\n')
    def inventory():return {'containers':sorted(c.id for c in cli.containers.list(all=True)),
                            'networks':sorted(n.id for n in cli.networks.list())}
    def command(argv):
        r=subprocess.run(argv,capture_output=True,text=True,timeout=30)
        row={'argv':argv,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
        result['cases'].append(row);save('results.json',result)
        return row
    def qdisc_shape():
        r=command(['tc','-j','qdisc','show'])
        assert r['returncode']==0,r
        return sorted((json.dumps({k:q.get(k) for k in ['kind','dev','handle','parent','root','options']},sort_keys=True)
                       for q in json.loads(r['stdout'])))
    def own(family,obj):
        resources.append((family,obj.id));save('ledger.json',resources)
        return obj
    def container(name,network):
        c=own('containers',cli.containers.create(args.image,name=token+'-'+name,network=network,
             labels={key:token},mem_limit='64m',nano_cpus=250_000_000))
        c.start();c.reload()
        return c
    before=inventory();save('inventory-before.json',before)
    try:
        image=cli.images.get(args.image)
        assert image.id==args.image and image.attrs['Architecture']=='arm64'
        a=own('networks',cli.networks.create(token+'-access',internal=True,labels={key:token}))
        b=own('networks',cli.networks.create(token+'-wan',internal=True,labels={key:token}))
        edge=container('edge',a.name)
        fog=container('fog',a.name)
        b.connect(fog)
        cloud=container('cloud',b.name)
        host=command(['ip','-j','link','show','type','veth'])
        assert host['returncode']==0
        host_links={r['ifindex']:r for r in json.loads(host['stdout'])}
        mapped=[]
        for c in [cloud,fog,edge]:
            row=c.exec_run(['ip','-j','link','show','type','veth'])
            assert row.exit_code==0
            links=json.loads(row.output)
            expected=[]
            for link in links:
                peer=c.exec_run(['cat','/sys/class/net/'+link['ifname']+'/iflink'])
                assert peer.exit_code==0
                host_index=int(peer.output.strip())
                h=host_links[host_index]
                assert h['link_index']==link['ifindex'],(h,link)
                expected.append(h['ifname'])
            mapper=DockerClient()
            assert mapper.create_veth_table(c.id)==0
            actual=mapper.fetch_veth_list(c.name)
            assert len(actual)==len(expected) and set(actual)==set(expected),(actual,expected)
            c.reload()
            mapped.append({'id':c.id,'name':c.name,'namespace_inode':os.stat('/proc/'+str(c.attrs['State']['Pid'])+'/ns/net').st_ino,
                           'links':links,'expected':expected,'actual':actual})
        save('mapping.json',mapped)
        assert len({r['namespace_inode'] for r in mapped})==3
        assert sorted(len(r['actual']) for r in mapped)==[1,1,2]
        before_negative=qdisc_shape()
        none=container('no-network','none')
        binary=str(Path(sys.executable).parent/'tcset')
        absent=command([binary,'--docker','--delay','20msec',token+'-absent'])
        assert absent['returncode']!=0,absent
        no_link=command([binary,'--docker','--delay','20msec',none.id])
        assert no_link['returncode']!=0,no_link
        namespace_path=Path('/var/run/netns')/none.name
        namespace_path.parent.mkdir(exist_ok=True)
        assert not os.path.lexists(namespace_path)
        namespace_target='/proc/self/ns/net'
        namespace_path.symlink_to(namespace_target)
        foreign=command([binary,'--docker','--delay','20msec',none.id])
        assert foreign['returncode']!=0,foreign
        assert namespace_path.is_symlink() and os.readlink(namespace_path)==namespace_target
        after_negative=qdisc_shape()
        assert before_negative==after_negative,'Negative commands changed a qdisc'
        result['negative_qdiscs_unchanged']=True
        result['foreign_namespace_preserved']=True
        result['status']='PASSED'
    except BaseException as error:
        result['failure']={'error':repr(error),'traceback':traceback.format_exc()}
    finally:
        if namespace_path is not None and os.path.lexists(namespace_path):
            if namespace_path.is_symlink() and os.readlink(namespace_path)==namespace_target:
                namespace_path.unlink()
            else:result['cleanup_errors'].append('Namespace ownership mismatch')
        for family,rid in reversed(resources):
            try:
                obj=getattr(cli,family).get(rid);obj.reload()
                labels=obj.labels if family=='containers' else obj.attrs.get('Labels',{})
                if labels.get(key)!=token:raise RuntimeError('Resource ownership mismatch')
                obj.remove(**({'force':True} if family=='containers' else {}))
            except BaseException as error:result['cleanup_errors'].append({'family':family,'id':rid,'error':repr(error)})
        after=inventory();save('inventory-after.json',after)
        result['inventory_restored']=before==after
        if result['cleanup_errors'] or before!=after:result['status']='FAILED'
        save('results.json',result)
        cli.close()
    print(json.dumps(result))
    return 0 if result['status']=='PASSED' else 1


if __name__=='__main__':raise SystemExit(main())
