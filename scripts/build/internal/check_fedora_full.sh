#!/usr/bin/env bash
# Build and verify a native Fedora RPM on a disposable Ubuntu Actions runner.
set -euo pipefail

arch=$1
commit=$2
uid=$(id -u)
gid=$(id -g)
image=loushang-fedora-ci
dockerfile=scripts/build/internal/fedora-ci.Dockerfile
evidence=dist/package-evidence
mkdir -p "$evidence" "${UV_CACHE_DIR:-$HOME/.cache/uv}" "$HOME/.npm"

for stage in build acceptance; do
  docker build --tag "$image:$stage" --target "$stage" --file "$dockerfile" \
    --build-arg HOST_UID="$uid" --build-arg HOST_GID="$gid" "$(dirname "$dockerfile")" 2>&1 | tee -a "$evidence/environment.log"
done

node_root=$(dirname "$(dirname "$(realpath "$(command -v node)")")")
workspace_mounts=(
  --volume "$PWD:/workspace"
  --volume "$(realpath "$(command -v uv)"):/usr/local/bin/uv:ro"
  --volume "${UV_CACHE_DIR:-$HOME/.cache/uv}:/home/builder/.cache/uv"
  --workdir /workspace
)
docker run --rm --user builder "${workspace_mounts[@]}" \
  --volume "$node_root:/opt/node:ro" \
  --volume "$HOME/.cargo:/home/builder/.cargo" \
  --volume "${RUSTUP_HOME:-$HOME/.rustup}:/home/builder/.rustup" \
  --volume "$HOME/.npm:/home/builder/.npm" \
  --env HOME=/home/builder \
  --env PATH=/home/builder/.cargo/bin:/opt/node/bin:/usr/local/bin:/usr/bin:/usr/sbin \
  "$image:build" uv run --no-project --python 3.11 python scripts/build/build_full_linux.py \
  --arch "$arch" --format rpm 2>&1 | tee "$evidence/build.log"

docker run --rm --user builder "${workspace_mounts[@]}" \
  --env HOME=/home/builder \
  --env PATH=/usr/local/bin:/usr/bin:/usr/sbin \
  --env GITHUB_ACTIONS=true --env RUNNER_ENVIRONMENT=github-hosted \
  "$image:acceptance" dbus-run-session -- bash -euc '
  XDG_RUNTIME_DIR=$(mktemp -d)
  export XDG_RUNTIME_DIR
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
