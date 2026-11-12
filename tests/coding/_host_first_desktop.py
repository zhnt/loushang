"""Opt-in manual Tauri acceptance. Observer never registers or submits work."""
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import mkdtemp
from time import monotonic

root = Path(__file__).resolve().parents[2]
evidence = Path(mkdtemp(prefix='loushang-host-first-desktop-'))
home = evidence / 'home'
home.mkdir(mode=0o700)
(home / "desktop-acceptance").touch()
roots = [evidence / 'A', evidence / 'B']
for path in roots:
    path.mkdir(mode=0o700)
    (path / 'marker').write_text(path.name)
(home / 'host.json').write_text(json.dumps({'web': {'bind': '127.0.0.1', 'port': 0, 'dist': str(root / 'gui/dist')}}))
env = {**os.environ, 'LOUSHANG_HOME': str(home), 'LOUSHANG_RUNTIME_DIR': str(evidence / 'runtime'),
       'LOUSHANG_TMPDIR': str(evidence / 'temporary'),
       'LOUSHANG_GUI_WEB': str(root / 'gui/web/target/debug/loushang-web'),
       'XDG_CONFIG_HOME': str(evidence / 'gui-config'), 'XDG_DATA_HOME': str(evidence / 'gui-data'),
       'XDG_CACHE_HOME': str(evidence / 'gui-cache')}


def manage(action, **fields):
    p = subprocess.run([sys.executable, str(Path(__file__).with_name("_host_first_manager.py"))],
        input=json.dumps({'action': action, **fields}), text=True, capture_output=True, env=env,
        timeout=90, check=True)
    return json.loads(p.stdout)


def record(kind, **fields):
    row = {'kind': kind, 'time': monotonic(), **fields}
    with (evidence / 'desktop.jsonl').open('a') as log:
        log.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)


with (evidence / 'gui.log').open('w') as log:
    def launch(label):
        process = subprocess.Popen([str(root / 'gui/src-tauri/target/debug/harness-gui')],
                                   cwd=evidence, env=env, stdout=log, stderr=log)
        record('gui_launched', label=label, pid=process.pid, evidence=str(evidence))
        return process

    host = manage('start')
    assert host['state'] == 'running', host
    env['LOUSHANG_APP_RECORD_ROOT'] = host['recordRoot']
    gui = None
    try:
        gui = launch('A')
        assert gui.wait(timeout=1500) == 0
        entered = [json.loads(line) for line in (home / 'entered.jsonl').read_text().splitlines()]
        assert {row['cwd'] for row in entered} == {str(path) for path in roots}, entered
        assert all(not (path / 'effects.jsonl').exists() for path in roots)
        state = manage('status')
        assert state['state'] == 'running' and {row['pid'] for row in entered} == {state['pid']}
        record('host_survived_gui_a', gui_pid=gui.pid, host_pid=state['pid'], service=state['serviceInstanceId'], entered=entered)
        (home / 'release').touch()
        gui = launch('B')
        assert gui.wait(timeout=1200) == 0
        for path in roots:
            effects = (path / 'effects.jsonl').read_text().splitlines()
            assert len(effects) == 1, effects
            record('workspace_effect', **json.loads(effects[0]))
    finally:
        (home / 'release').touch()
        if gui is not None and gui.poll() is None:
            gui.terminate()
            gui.wait(timeout=15)
        state = manage('status')
        if state['state'] != 'not_running' and state.get('instanceId'):
            stopped = manage('stop', instanceId=state['instanceId'])
            record('managed_stop', **{k:v for k,v in stopped.items() if k != 'recordRoot'})
            assert stopped.get('cleanlyStopped'), stopped
        assert not (home / 'state/web/endpoint.json').exists()
