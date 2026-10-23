"""Export every owned guest result, excluding dependency trees/build cache/sockets."""
import json
from pathlib import Path
import stat
import tarfile
root=Path('/opt/ehu-madt')
skipped=[]
with tarfile.open('/tmp/ehu-repair-evidence.tar.gz','w:gz') as archive:
    def keep(info):
        path=root/info.name
        if path.exists() and stat.S_ISSOCK(path.lstat().st_mode):
            skipped.append(info.name)
            return None
        return info
    for path in sorted(root.iterdir()):
        if path.name not in ['venv','madt','build']:
            archive.add(path,arcname=path.name,filter=keep)
print(json.dumps({'export':'/tmp/ehu-repair-evidence.tar.gz','excluded':['venv','madt','build'],'skipped_sockets':skipped}))
