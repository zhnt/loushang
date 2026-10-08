"""Test-only detached Product composition, not an installed daemon entry point.

The separate test socket controls model release and emergency graceful teardown;
it is created here, never added to the production launcher's inherited fd set.
"""

from __future__ import annotations

import asyncio
import faulthandler
import os
import signal
import socket
import sys
import threading
import traceback
from pathlib import Path
from time import monotonic, sleep
from typing import TextIO

from _hosted_product_child import scripted_stream

from loushang.agent import synthetic_model_transport
from loushang.ai.model import Capabilities, Model
from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.bootstrap import ManagedChildBootstrapV1
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.coding.hosted_local import CodingLocalCommandV1
from loushang.coding.managed_bootstrap import create_coding_managed_launch
from loushang.coding.managed_local import (
    CodingManagedLocalCommandV1,
    create_coding_managed_local_launch,
)


def run(root: Path, endpoint: socket.socket, bootstrap: ManagedChildBootstrapV1,
        invocation: ManagedChildInvocationV1, diagnostic: TextIO) -> None:
    def mark(stage):
        print(stage, file=diagnostic, flush=True)

    endpoint.settimeout(0.1)
    write_lock = threading.Lock()

    def send(data):
        with write_lock:
            endpoint.sendall(data)

    mark("bootstrap_opened")
    send(b"B")  # Test observation only; not birth/commit authority.
    release, finished = threading.Event(), threading.Event()
    failures = []
    calls = 0

    @synthetic_model_transport
    async def held_stream(model, context, options=None):
        nonlocal calls
        calls += 1
        mark("model_entered")
        await asyncio.to_thread(send, b"E")
        while not release.is_set():
            await asyncio.sleep(0.01)
        return await scripted_stream(model, context, options)

    model = Model(id="faux-model", name="Faux", provider="faux", endpoint="anthropic-messages",
                  capabilities=Capabilities(input=("text",), context_window=128000, max_tokens=4096))
    if sys.argv[3] == "canonical":
        canonical = create_coding_managed_local_launch(
            invocation, application_id="coding.default", endpoint="workspace",
            session_root=root / "sessions", session_discovery=True,
        )
        application = CodingManagedLocalCommandV1(canonical, model=model, stream_fn=held_stream, tools=[])
    else:
        launch = create_coding_managed_launch(
            invocation, application_id="coding.default", endpoint="workspace",
            cwd_sessions=root / "cwd-sessions", home_sessions=root / "home-sessions",
        )
        application = CodingLocalCommandV1(launch, model=model, stream_fn=held_stream, tools=[])
    owner = bootstrap.bind(application)

    def test_control():
        try:
            while not owner.accepting:
                if finished.wait(0.005):
                    return
            send(b"R")
            mark("accepting")
            while not finished.is_set():
                try:
                    command = endpoint.recv(1)
                except TimeoutError:
                    continue
                if not command:
                    if not finished.is_set():
                        os.kill(os.getpid(), signal.SIGTERM)  # Test fallback, explicit self-stop.
                    return
                if command == b"G":
                    release.set()
                elif command == b"C":
                    send(str(calls).encode() + b"\n")
                else:
                    raise AssertionError("invalid test command")
        except BaseException as error:
            failures.append(error)
            if not finished.is_set():
                os.kill(os.getpid(), signal.SIGTERM)

    controller = threading.Thread(target=test_control, name="managed-test-control")
    controller.start()
    try:
        status = bootstrap.run_process()  # Owns the actual main-thread loop and signal policy.
        finished.set()
        controller.join(2)
        assert not controller.is_alive()
        if failures:
            raise failures[0]
        assert status == 0 and not bootstrap.cleanup_pending
        mark("all_owners_closed")
        send(b"D")  # Production owners and the test controller have all settled.
    finally:
        finished.set()
        release.set()
        controller.join(2)
        endpoint.close()


if __name__ == "__main__":
    # A test watchdog exit is failure, never evidence of graceful cleanup.
    root = Path(sys.argv[1])
    fd = os.open(root / "child-diagnostic.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as diagnostic:
        faulthandler.dump_traceback_later(55, exit=True, file=diagnostic)
        bootstrap = None
        try:
            os.environ["LOUSHANG_HOME"] = str(root / "platform")
            os.environ["LOUSHANG_RUNTIME_DIR"] = str(root / "runtime")
            invocation = ManagedChildInvocationV1.from_json(sys.argv[4])
            assert invocation.service.product_id == "coding" and invocation.service.workspace == str(root)
            bootstrap = ManagedChildBootstrapV1(
                invocation.namespace, invocation.service, invocation.instance, invocation.attempt_id,
                socket.socket(fileno=int(sys.argv[5])), runtime_root=invocation.runtime_root,
            )
            deadline = monotonic() + 15
            while True:
                try:
                    bootstrap.open(deadline=deadline)
                    break
                except ManagedStorageError as error:
                    if error.code != "busy" or monotonic() >= deadline:
                        raise
                    sleep(0.01)
            endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            endpoint.settimeout(10)
            endpoint.connect("\0" + sys.argv[2])
            run(root, endpoint, bootstrap, invocation, diagnostic)
        except BaseException:
            traceback.print_exc(file=diagnostic)
            diagnostic.flush()
            raise
        finally:
            try:
                if bootstrap is not None:
                    bootstrap.close()
            finally:
                faulthandler.cancel_dump_traceback_later()
