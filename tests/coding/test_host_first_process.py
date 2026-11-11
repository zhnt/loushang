import json
import os
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.requires_host_runtime,
              pytest.mark.skipif(sys.platform != 'linux', reason='Linux managed lifecycle')]


def test_empty_host_accepts_multiple_workspaces_without_new_process(tmp_path):
    home = tmp_path / 'home'
    home.mkdir(mode=0o700)
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    env = {**os.environ, 'LOUSHANG_HOME': str(home),
           'LOUSHANG_RUNTIME_DIR': str(tmp_path / 'runtime'),
           'LOUSHANG_TMPDIR': str(tmp_path / 'temporary')}

    def call(action, **fields):
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
        assert not value.get("errorCode"), value
        return value

    host = None
    try:
        assert call('status')['state'] == 'not_running'
        host = call('start')
        assert host['state'] == 'running', host
        assert host['pid'] != os.getpid()
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
    finally:
        if host and host.get('instanceId'):
            stopped = call('stop', instanceId=host['instanceId'])
            assert stopped.get('cleanlyStopped'), stopped


def test_real_host_runs_four_sessions_in_two_workspace_contexts(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path
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
