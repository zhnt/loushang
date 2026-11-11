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


def test_real_host_runs_four_sessions_in_two_workspace_contexts(tmp_path, monkeypatch):
    import asyncio
    from time import monotonic

    from loushang.coding.web_client import WebHostClient

    home = tmp_path / 'home'
    home.mkdir(mode=0o700)
    for name, leaf in [('LOUSHANG_HOME', 'home'), ('LOUSHANG_RUNTIME_DIR', 'runtime'), ('LOUSHANG_TMPDIR', 'temporary')]:
        monkeypatch.setenv(name, str(tmp_path / leaf))
    roots = [tmp_path / 'a', tmp_path / 'b']
    for path in roots:
        path.mkdir()
        (path / 'marker').write_text(path.name)

    async def operate(request, **_ignored):
        def invoke():
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('_host_first_manager.py'))],
                input=json.dumps(request), text=True, capture_output=True, env=os.environ.copy(), timeout=90)
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)
        return await asyncio.to_thread(invoke)

    async def scenario():
        host = await operate({'action': 'start'})
        assert host['state'] == 'running', host
        clients = []
        executions = []
        try:
            for path in roots:
                registered = await operate({'action': 'workspace', 'workspaceAction': 'register', 'workspace': str(path)})
                assert not registered['errorCode'], registered
                opened = await operate({'action': 'workspace', 'workspaceAction': 'open', 'workspace': str(path)})
                assert opened['pid'] == host['pid']
                client = WebHostClient(Path(opened['recordRoot']), opened['muxName'], workspace_scope=opened['workspaces'][0])
                clients.append(client)
                await client.start()
                await client.call('create', {'title': 'Second Session'})
                assert len(client.attachment.mux_space.members) == 2
                for index, member in enumerate(client.attachment.mux_space.members):
                    label = f'{path.name}-{index}'
                    result = await client.call('submit', {'sessionId': member.session.session_id, 'submissionId': label, 'text': label})
                    assert result['accepted'], result
                    executions.append((client, member.session.session_id, label, result['executionId']))
            deadline = monotonic() + 20
            while not (home / 'entered.jsonl').exists() or len((home / 'entered.jsonl').read_text().splitlines()) < 4:
                assert monotonic() < deadline, [await c.call('snapshot', {}) for c in clients]
                await asyncio.sleep(.05)
            entered = [json.loads(row) for row in (home / 'entered.jsonl').read_text().splitlines()]
            assert {row['pid'] for row in entered} == {host['pid']}
            assert {row['cwd'] for row in entered} == {str(p) for p in roots}
            for client, session_id, submission, execution_id in executions:
                api = client.connection.execution_client
                control = client.control(session_id)
                record = await api.find_execution_by_submission(control, host['serviceInstanceId'], submission)
                assert record.state.execution_id == execution_id
                assert record.state.status.value == 'running'
            (home / 'release').touch()
            for client, session_id, submission, execution_id in executions:
                api = client.connection.execution_client
                while True:
                    record = await api.get_execution(client.control(session_id), host['serviceInstanceId'], execution_id)
                    if record.state.status.terminal:
                        assert record.state.status.value == 'succeeded', record
                        break
                    assert monotonic() < deadline
                    await asyncio.sleep(.05)
            for path in roots:
                effects = [json.loads(row) for row in (path / 'effects.jsonl').read_text().splitlines()]
                assert len(effects) == 2
                assert {row['marker'] for row in effects} == {path.name}
                assert {row['cwd'] for row in effects} == {str(path)}
            assert not (home / 'effects.jsonl').exists()
        finally:
            (home / "release").touch()
            await asyncio.gather(*(client.close() for client in clients))
            stopped = await operate({'action': 'stop', 'instanceId': host['instanceId']})
            assert stopped.get('cleanlyStopped'), stopped
    asyncio.run(scenario())


def test_gui_adapter_process_exit_and_reconnect_keep_original_execution(tmp_path):
    from time import monotonic

    home, workspace = tmp_path / 'home', tmp_path / 'workspace'
    home.mkdir(mode=0o700)
    workspace.mkdir()
    (workspace / 'marker').write_text('original')
    env = {**os.environ, 'LOUSHANG_HOME': str(home),
           'LOUSHANG_RUNTIME_DIR': str(tmp_path / 'runtime'),
           'LOUSHANG_TMPDIR': str(tmp_path / 'temporary')}
    manager = Path(__file__).with_name('_host_first_manager.py')

    def manage(request):
        result = subprocess.run([sys.executable, str(manager)], input=json.dumps(request),
                                text=True, capture_output=True, env=env, timeout=90, check=True)
        return json.loads(result.stdout)

    def connect():
        return subprocess.Popen([sys.executable, '-m', 'loushang.coding.web_gateway'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)

    def call(client, request):
        client.stdin.write(json.dumps({'id': 'test', 'request': request}) + '\n')
        client.stdin.flush()
        response = json.loads(client.stdout.readline())
        assert 'error' not in response, response
        return response['result']

    def close(client):
        if client.poll() is None:
            client.stdin.close()
            assert client.wait(timeout=15) == 0, client.stderr.read()

    host = manage({'action': 'start'})
    assert host['state'] == 'running', host
    a = b = None
    try:
        a = connect()
        connected = call(a, {'operation': 'manage', 'action': 'connect'})
        assert connected['pid'] == host['pid']
        assert call(a, {'operation': 'workspace', 'action': 'list'})['workspaces'] == []
        call(a, {'operation': 'workspace', 'action': 'register', 'path': str(workspace)})
        call(a, {'operation': 'workspace', 'action': 'open', 'path': str(workspace)})
        snapshot = call(a, {'operation': 'live', 'workspace': str(workspace), 'action': 'snapshot'})
        session = snapshot['sessions'][0]['source']['source']['identity']['sessionId']
        accepted = call(a, {'operation': 'live', 'workspace': str(workspace), 'action': 'submit',
            'input': {'sessionId': session, 'submissionId': 'survive-gui-a', 'text': 'once'}})
        assert accepted['accepted'], accepted
        deadline = monotonic() + 20
        while not (home / 'entered.jsonl').exists():
            assert monotonic() < deadline
            import time
            time.sleep(.05)
        assert not (workspace / 'effects.jsonl').exists()
        close(a)
        assert a.poll() == 0
        assert manage({'action': 'status'})['pid'] == host['pid']
        b = connect()
        assert b.pid != a.pid and b.pid != host['pid']
        reconnected = call(b, {'operation': 'manage', 'action': 'connect'})
        assert reconnected['serviceInstanceId'] == connected['serviceInstanceId']
        call(b, {'operation': 'workspace', 'action': 'open', 'path': str(workspace)})
        found = call(b, {'operation': 'live', 'workspace': str(workspace), 'action': 'find',
            'input': {'sessionId': session, 'submissionId': 'survive-gui-a'}})
        assert found['state']['executionId'] == accepted['executionId']
        assert found['state']['status'] == 'running'
        (home / 'release').touch()
        while True:
            found = call(b, {'operation': 'live', 'workspace': str(workspace), 'action': 'find',
                'input': {'sessionId': session, 'submissionId': 'survive-gui-a'}})
            if found['state']['status'] == 'succeeded':
                break
            assert monotonic() < deadline
        assert len((workspace / 'effects.jsonl').read_text().splitlines()) == 1
        close(b)
        assert manage({'action': 'stop', 'instanceId': host['instanceId']}).get('cleanlyStopped')
        previous = host
        host = manage({'action': 'start'})
        assert host['state'] == 'running', host
        assert host['serviceInstanceId'] != previous['serviceInstanceId']
        b = connect()
        call(b, {'operation': 'manage', 'action': 'connect'})
        call(b, {'operation': 'workspace', 'action': 'open', 'path': str(workspace)})
        restored = call(b, {'operation': 'live', 'workspace': str(workspace), 'action': 'snapshot'})
        assert restored['muxSpace']['muxSpaceId'] == snapshot['muxSpace']['muxSpaceId']
        source = restored['sessions'][0]['source']['source']
        assert source['identity']['sessionId'] == session
        assert any(row['kind'] == 'user' and row['text'] == 'once' for row in source['records'])
        assert len((workspace / 'effects.jsonl').read_text().splitlines()) == 1
    finally:
        (home / 'release').touch()
        for client in (a, b):
            if client is not None:
                close(client)
        assert manage({'action': 'stop', 'instanceId': host['instanceId']}).get('cleanlyStopped')
