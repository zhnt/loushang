#!/usr/bin/env bash
# Build and verify a native Fedora RPM on a disposable Ubuntu Actions runner.
set -euo pipefail

arch=$1
commit=$2
uid=$(id -u)
gid=$(id -g)
image=loushang-fedora-ci:43
evidence=dist/package-evidence
mkdir -p "$evidence" "${UV_CACHE_DIR:-$HOME/.cache/uv}" "$HOME/.npm"

docker build --tag "$image" --build-arg HOST_UID="$uid" --build-arg HOST_GID="$gid" - <<'DOCKERFILE' 2>&1 | tee "$evidence/environment.log"
FROM registry.fedoraproject.org/fedora:43
ENV container=docker
RUN dnf -y --setopt=install_weak_deps=False install \
    bash ca-certificates dbus-broker desktop-file-utils file findutils gcc gcc-c++ git \
    glibc-devel gtk3-devel libayatana-appindicator-gtk3-devel librsvg2-devel libxdo-devel \
    make openssl-devel pkgconf-pkg-config procps-ng rpm-build shadow-utils sudo \
    systemd systemd-pam webkit2gtk4.1-devel xdg-utils xdotool xorg-x11-server-Xvfb \
    && dnf clean all
ARG HOST_UID
ARG HOST_GID
RUN groupadd -o -g "$HOST_GID" builder && useradd -m -u "$HOST_UID" -g builder builder \
    && echo 'builder ALL=(root) NOPASSWD: ALL' > /etc/sudoers.d/loushang-ci
DOCKERFILE

node_root=$(dirname "$(dirname "$(realpath "$(command -v node)")")")
container=$(docker run -d --privileged --cgroupns=private --tmpfs /run --tmpfs /run/lock \
  --volume "$PWD:/workspace" \
  --volume "$node_root:/opt/node:ro" \
  --volume "$(realpath "$(command -v uv)"):/usr/local/bin/uv:ro" \
  --volume "$HOME/.cargo:/home/builder/.cargo" \
  --volume "${RUSTUP_HOME:-$HOME/.rustup}:/home/builder/.rustup" \
  --volume "${UV_CACHE_DIR:-$HOME/.cache/uv}:/home/builder/.cache/uv" \
  --volume "$HOME/.npm:/home/builder/.npm" \
  --workdir /workspace "$image" /usr/sbin/init)
cleanup() {
  docker exec "$container" journalctl --no-pager -b -n 300 > "$evidence/fedora-journal.log" 2>&1 || true
  docker rm -f "$container" >/dev/null
}
trap cleanup EXIT

for attempt in {1..30}; do
  if docker exec "$container" loginctl enable-linger builder; then break; fi
  sleep 1
done
docker exec "$container" loginctl enable-linger builder

run_as_builder() {
  docker exec --user builder --env HOME=/home/builder \
    --env PATH=/home/builder/.cargo/bin:/opt/node/bin:/usr/local/bin:/usr/bin:/usr/sbin \
    --env GITHUB_ACTIONS=true --env RUNNER_ENVIRONMENT=github-hosted \
    --env XDG_RUNTIME_DIR="/run/user/$uid" \
    --env DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" "$container" "$@"
}
for attempt in {1..30}; do
  if run_as_builder systemctl --user show-environment >/dev/null; then break; fi
  sleep 1
done
run_as_builder systemctl --user show-environment >/dev/null
run_as_builder uv run --no-project --python 3.11 python scripts/build/build_full_linux.py \
  --arch "$arch" --format rpm 2>&1 | tee "$evidence/build.log"
run_as_builder bash -euc '
  export DISPLAY=:99
  Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp &
  trap "kill $!" EXIT
  for attempt in {1..30}; do
    if xdotool getdisplaygeometry; then break; fi
    sleep 1
  done
  xdotool getdisplaygeometry
  uv run --no-project --python 3.11 python scripts/gui/check_installed_unix_package.py \
    dist/packages/*.rpm --arch "$1" --commit "$2" --evidence dist/package-evidence
' bash "$arch" "$commit" 2>&1 | tee "$evidence/install.log"
