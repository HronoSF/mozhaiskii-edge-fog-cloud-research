#!/usr/bin/env bash
set -euo pipefail
mkdir -p /opt/ehu-madt/build
cp /tmp/endpoint.Dockerfile /opt/ehu-madt/build/Dockerfile
cp /opt/ehu-madt/runtime-baseline/endpoint-apt.preferences /opt/ehu-madt/build/apt.preferences
cd /opt/ehu-madt/build
docker build --build-arg BASE_IMAGE=ubuntu@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac -t ehu-madt-endpoint:20261019 .
docker image inspect ehu-madt-endpoint:20261019 > /opt/ehu-madt/endpoint-image.json
docker create --label org.ehu.madt.preparation=20261019 --name ehu-madt-package-manifest-v2 --cidfile /opt/ehu-madt/preparation-container-v2.id --entrypoint /usr/bin/dpkg-query ehu-madt-endpoint:20261019 -W
prep_id=$(cat /opt/ehu-madt/preparation-container-v2.id)
trap 'docker rm -f "$prep_id"' EXIT
docker start -a "$prep_id" > /opt/ehu-madt/endpoint-packages.txt
python3 - <<'PY'
import json
from pathlib import Path
image=json.loads(Path('/opt/ehu-madt/endpoint-image.json').read_text())[0]
assert image['Architecture']=='arm64',image['Architecture']
Path('/opt/ehu-madt/endpoint-id.txt').write_text(image['Id']+'\n')
print(image['Id'],image['Architecture'])
PY

python3 /opt/ehu-madt/runtime-baseline/verify_manifests.py endpoint
