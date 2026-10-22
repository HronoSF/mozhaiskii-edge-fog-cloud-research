#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
mkdir -p /opt/ehu-madt
if test -e /opt/ehu-madt/bootstrap-started; then
  echo 'Refusing bootstrap rerun; inspect preserved failure first' >&2
  exit 2
fi
touch /opt/ehu-madt/bootstrap-started
test "$(uname -m)" = aarch64
uname -a
cat /etc/os-release
# Check each package independently: a multi-package dpkg-query can return
# nonzero even when some engine packages are installed. Run before apt changes.
for package in docker.io docker-ce docker-ce-cli containerd.io containerd runc; do
  installed_status=$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)
  if test "$installed_status" = installed; then
    echo "Refusing pre-existing engine/runtime package: $package" >&2
    exit 3
  fi
done
if test -S /var/run/docker.sock || test -d /var/lib/docker; then
  echo 'Refusing pre-existing Docker socket/data directory' >&2
  exit 3
fi
cp -a /tmp/ehu-inputs/tests/runtime-baseline /opt/ehu-madt/runtime-baseline
cp /opt/ehu-madt/runtime-baseline/apt.preferences /etc/apt/preferences.d/ehu-scheduling-baseline
apt-get update
apt-get install --no-install-recommends -y ca-certificates=20260816ubuntu0.24.04.1 curl=8.5.0-2ubuntu10.16 gnupg=2.4.4-2ubuntu17.6 python3-venv=3.12.3-0ubuntu2.1 python3-pip=24.0+dfsg-1ubuntu1.3 git=1:2.43.0-1ubuntu7.4 iproute2=6.1.0-1ubuntu6.4 iputils-ping=3:20240117-1ubuntu0.1
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc > /opt/ehu-madt/docker-signing-key.txt
grep -q '9DC858229FC7DD38854AE2D88D81803C0EBFCD88' /opt/ehu-madt/docker-signing-key.txt
cat > /etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: arm64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
engine_version='5:28.5.2-1~ubuntu.24.04~noble'
containerd_version='1.7.29-1~ubuntu.24.04~noble'
apt-cache show "docker-ce=$engine_version" "docker-ce-cli=$engine_version" "containerd.io=$containerd_version" > /opt/ehu-madt/docker-package-metadata.txt
apt-get install --no-install-recommends -y "docker-ce=$engine_version" "docker-ce-cli=$engine_version" "containerd.io=$containerd_version"
apt-mark hold docker-ce docker-ce-cli containerd.io
systemctl enable --now docker
modprobe sch_netem
python3 -m venv /opt/ehu-madt/venv
/opt/ehu-madt/venv/bin/python -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r /opt/ehu-madt/runtime-baseline/requirements.lock
/opt/ehu-madt/venv/bin/python -m pip freeze --all > /opt/ehu-madt/python-lock.txt
dpkg-query -W > /opt/ehu-madt/debian-packages.txt
git clone https://github.com/dltcspbu/madt.git /opt/ehu-madt/madt
git -C /opt/ehu-madt/madt checkout --detach ca7df8460448ae515f17bfb3a594b30ef9503415
test "$(git -C /opt/ehu-madt/madt rev-parse HEAD)" = ca7df8460448ae515f17bfb3a594b30ef9503415
docker version
test "$(docker version --format '{{.Server.Version}}')" = 28.5.2
docker pull --platform linux/arm64 ubuntu@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
docker image inspect ubuntu@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac > /opt/ehu-madt/base-image.json
python3 /opt/ehu-madt/runtime-baseline/verify_manifests.py guest
touch /opt/ehu-madt/bootstrap-complete
