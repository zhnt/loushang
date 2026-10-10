#!/usr/bin/env bash
# Reboot an isolated Linux guest and verify registered Worker recovery there.
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
artifact_root="$repo_root/.artifacts/registered-reboot-vm"
vm_root=$(mktemp -d)
mkdir -p "$artifact_root"

cleanup() {
  if [ -f "$vm_root/qemu.pid" ]; then
    vm_pid=$(cat "$vm_root/qemu.pid")
    kill "$vm_pid" 2>/dev/null || true
  fi
  if [ -f "$vm_root/serial.log" ]; then
    cp "$vm_root/serial.log" "$artifact_root/serial.log"
  fi
}
trap cleanup EXIT

sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  qemu-system-x86 qemu-utils cloud-image-utils openssh-client

image_base=https://cloud-images.ubuntu.com/releases/noble/release
image_name=ubuntu-24.04-server-cloudimg-amd64.img
curl -fsSL --retry 3 "$image_base/SHA256SUMS" -o "$vm_root/SHA256SUMS"
curl -fsSL --retry 3 "$image_base/$image_name" -o "$vm_root/$image_name"
(
  cd "$vm_root"
  grep -E "[[:space:]\\*]$image_name$" SHA256SUMS | sha256sum -c -
)

qemu-img create -f qcow2 -F qcow2 -b "$vm_root/$image_name" \
  "$vm_root/guest.qcow2" 12G
ssh-keygen -q -t ed25519 -N "" -f "$vm_root/id_ed25519"
cat > "$vm_root/user-data" <<EOF
#cloud-config
users:
  - default
  - name: drill
    groups: [sudo]
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat "$vm_root/id_ed25519.pub")
ssh_pwauth: false
EOF
cat > "$vm_root/meta-data" <<EOF
instance-id: registered-worker-reboot-${GITHUB_RUN_ID:-local}
local-hostname: registered-worker-drill
EOF
cloud-localds "$vm_root/seed.img" "$vm_root/user-data" "$vm_root/meta-data"

ssh_args=(
  -i "$vm_root/id_ed25519"
  -p 2222
  -o BatchMode=yes
  -o ConnectTimeout=5
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
)
scp_args=(
  -i "$vm_root/id_ed25519"
  -P 2222
  -o BatchMode=yes
  -o ConnectTimeout=5
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
)
guest() {
  ssh "${ssh_args[@]}" drill@127.0.0.1 "$@"
}

start_vm() {
  local accel=$1
  echo "Starting isolated guest with $accel acceleration"
  qemu-system-x86_64 \
    -machine q35,accel="$accel" -cpu max -smp 2 -m 3072 \
    -drive "file=$vm_root/guest.qcow2,format=qcow2,if=virtio" \
    -drive "file=$vm_root/seed.img,format=raw,if=virtio,readonly=on" \
    -netdev user,id=net0,hostfwd=tcp:127.0.0.1:2222-:22 \
    -device virtio-net-pci,netdev=net0 \
    -display none -monitor none -serial "file:$vm_root/serial.log" \
    -daemonize -pidfile "$vm_root/qemu.pid"
}

wait_for_guest() {
  local deadline=$((SECONDS + $1))
  while (( SECONDS < deadline )); do
    if guest true >/dev/null 2>&1; then
      return 0
    fi
    if [ -f "$vm_root/qemu.pid" ] && ! kill -0 "$(cat "$vm_root/qemu.pid")" 2>/dev/null; then
      return 1
    fi
    sleep 5
  done
  return 1
}

accel=tcg
if [ -r /dev/kvm ]; then
  set +e
  timeout 3 qemu-system-x86_64 -machine none,accel=kvm \
    -display none -monitor none -nodefaults -S >/dev/null 2>&1
  probe_status=$?
  set -e
  if [ "$probe_status" -eq 124 ]; then
    accel=kvm
  fi
fi
start_vm "$accel"
if ! wait_for_guest 900; then
  if [ "$accel" != kvm ]; then
    echo "QEMU guest failed to start; see serial.log" >&2
    exit 1
  fi
  echo "KVM guest did not start; retrying the same disk with TCG" >&2
  kill "$(cat "$vm_root/qemu.pid")" 2>/dev/null || true
  rm -f "$vm_root/qemu.pid"
  start_vm tcg
  wait_for_guest 1800
fi
guest 'cloud-init status --wait'

git -C "$repo_root" archive --format=tar HEAD | gzip -1 > "$vm_root/source.tar.gz"
scp "${scp_args[@]}" "$vm_root/source.tar.gz" drill@127.0.0.1:source.tar.gz
guest 'mkdir -p loushang && tar -xzf source.tar.gz -C loushang'
guest 'sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential python3-venv python3-dev'
guest 'cd loushang && python3 -m venv .venv && .venv/bin/python -m pip install -q --upgrade pip && .venv/bin/python -m pip install -q -e ".[dev]"'

guest 'cd loushang && LOUSHANG_HOME=/home/drill/registered-worker-drill/private-home PYTHONPATH=src .venv/bin/python scripts/dev/worker_registered_reboot_drill.py prepare --root /home/drill/registered-worker-drill'
scp "${scp_args[@]}" \
  drill@127.0.0.1:registered-worker-drill/registered-worker-reboot-drill.json \
  "$artifact_root/manifest.json"
before_boot=$(guest 'cat /proc/sys/kernel/random/boot_id' | tr -d '\r\n')
qemu_pid=$(cat "$vm_root/qemu.pid")
guest 'sudo systemctl reboot' >/dev/null 2>&1 || true

deadline=$((SECONDS + 900))
after_boot=
while (( SECONDS < deadline )); do
  after_boot=$(guest 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null | tr -d '\r\n') || true
  if [ -n "$after_boot" ] && [ "$after_boot" != "$before_boot" ]; then
    break
  fi
  sleep 5
done
if [ -z "$after_boot" ] || [ "$after_boot" = "$before_boot" ]; then
  echo "Guest did not complete a real kernel reboot" >&2
  exit 1
fi
if [ "$(cat "$vm_root/qemu.pid")" != "$qemu_pid" ] || ! kill -0 "$qemu_pid"; then
  echo "QEMU guest process changed across the OS reboot" >&2
  exit 1
fi
guest 'cloud-init status --wait'
guest 'cd loushang && LOUSHANG_HOME=/home/drill/registered-worker-drill/private-home PYTHONPATH=src .venv/bin/python scripts/dev/worker_registered_reboot_drill.py recover --root /home/drill/registered-worker-drill'
scp "${scp_args[@]}" \
  drill@127.0.0.1:registered-worker-drill/registered-worker-reboot-result.json \
  "$artifact_root/result.json"
python3 - "$artifact_root/manifest.json" "$artifact_root/result.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
result = json.loads(Path(sys.argv[2]).read_text())
assert manifest["bootIdBefore"] != result["bootIdAfter"]
assert manifest["bootIdBefore"] == result["bootIdBefore"]
assert manifest["attemptId"] == result["attemptId"]
assert manifest["storeId"] == result["storeId"]
assert result["phase"] == "settled"
assert result["noEffect"] is True
assert result["gcPrepare"] == "passed"
assert result["reopen"] == "idempotent"
print(json.dumps(result, sort_keys=True))
PY
git -C "$repo_root" rev-parse HEAD > "$artifact_root/source-commit.txt"
python3 - "$artifact_root/host-evidence.json" "$accel" "$qemu_pid" "$before_boot" "$after_boot" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "acceleration": sys.argv[2],
            "qemuPidBeforeAndAfter": int(sys.argv[3]),
            "bootIdBefore": sys.argv[4],
            "bootIdAfter": sys.argv[5],
        },
        sort_keys=True,
    ) + "\n"
)
PY
