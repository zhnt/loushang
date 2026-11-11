"""Desktop helper uses production managed processes, without an in-process Host."""
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
    from loushang.coding.gui_local_host import operate
    from loushang.coding.managed_process import coding_managed_process_request

    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    for name, leaf in (("LOUSHANG_HOME", "home"), ("LOUSHANG_RUNTIME_DIR", "runtime"),
                       ("LOUSHANG_TMPDIR", "temporary")):
        monkeypatch.setenv(name, str(tmp_path / leaf))

    def missing_executable(invocation, descriptor):
        original = coding_managed_process_request(invocation, descriptor,
            executable=sys.executable, environment=os.environ)
        return replace(original, argv=(str(tmp_path / "missing-python"),))

    failed = asyncio.run(operate({"action": "start", "workspace": str(workspace)},
                                 request_factory=missing_executable))
    assert failed["state"] == "unknown", failed
    assert failed["errorCode"] is not None
    assert not failed.get("serviceInstanceId")
    assert not failed.get("pid")
    inspected = asyncio.run(operate({"action": "status", "workspace": str(workspace)}))
    assert inspected["state"] != "running", inspected


def test_empty_host_accepts_multiple_workspaces_without_new_process(tmp_path):
    home = tmp_path / 'home'
    home.mkdir(mode=0o700)
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    env = {**os.environ, 'LOUSHANG_HOME': str(home),
           'LOUSHANG_RUNTIME_DIR': str(tmp_path / 'runtime'),
           'LOUSHANG_TMPDIR': str(tmp_path / 'temporary')}

    def call(action, *, allow_error=False, **fields):
        p = subprocess.run([sys.executable, '-m', 'loushang.coding.gui_local_host'],
                           input=json.dumps({'action': action, **fields}),
                           text=True, capture_output=True, env=env, timeout=90)
        assert p.returncode == 0, p.stderr
        value = json.loads(p.stdout)
        if value.get("errorCode") == "management_failed":
            diagnostic = subprocess.run([sys.executable, "-c",
                "import asyncio,json,sys; from loushang.coding.gui_local_host import operate; print(asyncio.run(operate(json.load(sys.stdin))))"],
                input=json.dumps({'action': action, **fields}), text=True,
                capture_output=True, env=env, timeout=90)
            pytest.fail(diagnostic.stderr or diagnostic.stdout)
        if not allow_error:
            assert not value.get("errorCode"), value
        return value

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
        assert call('workspace', workspaceAction='list')['workspaces'] == []
        for path in (a, b):
            registered = call('workspace', workspaceAction='register', workspace=str(path))
            assert not registered['errorCode'], registered
            opened = call('workspace', workspaceAction='open', workspace=str(path))
            assert opened['pid'] == host['pid']
            assert opened['serviceInstanceId'] == host['serviceInstanceId']
            assert opened['muxName'].startswith('ws-')
        listed = call('workspace', workspaceAction='list')
        assert {row['path'] for row in listed['workspaces']} == {str(a), str(b)}
        assert call('start')['pid'] == host['pid']
        assert call('stop', allow_error=True, instanceId='0' * 32)['errorCode'] == 'instance_changed'
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
        assert call('connect')['pid'] == host['pid']
    finally:
        if host and host.get('instanceId'):
            stopped = call('stop', instanceId=host['instanceId'])
            assert stopped.get('cleanlyStopped'), stopped
