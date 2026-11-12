"""Exercise the lifecycle used by loushang-mux with a native AppHost."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

pytestmark = [pytest.mark.requires_host_runtime,
              pytest.mark.skipif(sys.platform != "linux", reason="Linux managed lifecycle")]


def test_failed_native_spawn_is_not_reported_as_ready(tmp_path, monkeypatch):
    from loushang.coding.managed_process import coding_managed_process_request
    from loushang.coding.managed_service import (
        ServiceControlError,
        control_managed_service,
    )

    for name, leaf in (("LOUSHANG_HOME", "home"), ("LOUSHANG_RUNTIME_DIR", "runtime"),
                       ("LOUSHANG_TMPDIR", "temporary")):
        monkeypatch.setenv(name, str(tmp_path / leaf))

    def missing_executable(invocation, descriptor):
        original = coding_managed_process_request(invocation, descriptor,
            executable=sys.executable, environment=os.environ)
        return replace(original, argv=(str(tmp_path / "missing-python"),))

    with pytest.raises(ServiceControlError):
        asyncio.run(control_managed_service("start", None, request_factory=missing_executable))
    inspected = asyncio.run(control_managed_service("status", None))
    assert inspected["state"] != "running", inspected


def test_concurrent_starts_reuse_the_authenticated_host(tmp_path):
    home = tmp_path / 'home'
    home.mkdir(mode=0o700)
    env = {**os.environ, 'LOUSHANG_HOME': str(home),
           'PYTHONPATH': str(Path(__file__).resolve().parents[2] / 'src'),
           'LOUSHANG_RUNTIME_DIR': str(tmp_path / 'runtime'),
           'LOUSHANG_TMPDIR': str(tmp_path / 'temporary'),
           'LOUSHANG_MUX_BACKEND': 'managed'}

    def call(action, *, allow_error=False, instance_id=None):
        command = [sys.executable, "-m", "loushang.coding.cli.mux", "service", action, "--json"]
        if instance_id is not None:
            command.extend(["--instance", instance_id])
        result = subprocess.run(command, text=True, capture_output=True, env=env, timeout=90)
        assert result.returncode == int(allow_error), (result.stdout, result.stderr)
        return json.loads(result.stdout)

    host = None
    try:
        assert call('status')['state'] == 'not_running'
        host = call('start')
        assert host['state'] == 'running', host
        assert host['pid'] != os.getpid()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as callers:
            duplicates = list(callers.map(lambda _: call('start'), range(2)))
        assert {item['pid'] for item in duplicates} == {host['pid']}
        assert {item['serviceInstanceId'] for item in duplicates} == {host['serviceInstanceId']}
        assert call('start')['pid'] == host['pid']
        assert call('stop', allow_error=True, instance_id='0' * 32)['errorCode'] == 'instance_changed'
        record, = Path(host['recordRoot']).glob('*.json')
        original = record.read_bytes()
        try:
            corrupted = json.loads(original)
            assert corrupted['scopes'] == []
            corrupted['key'] = '00' * 32
            record.write_text(json.dumps(corrupted))
            assert call('status', allow_error=True)['errorCode'] == 'authentication_failed'
            corrupted['protocolVersion'] = 'unsupported/v99'
            record.write_text(json.dumps(corrupted))
            assert call('start', allow_error=True)['state'] == 'unknown'
        finally:
            record.write_bytes(original)
        assert call('status')['pid'] == host['pid']
    finally:
        if host and host.get('instanceId'):
            stopped = call('stop', instance_id=host['instanceId'])
            assert stopped.get('cleanlyStopped'), stopped
