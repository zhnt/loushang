"""Test-only transport injection without pre-importing the measured Product.

Runs the installed console wrapper unchanged after a stdlib-only import hook.
Only Agent's injected transport and a Session prompt-return observer differ.
Never enable this child against real user data. No network or tool work is used.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import os
import resource
import runpy
import sys
import time
from pathlib import Path
from threading import Lock

INPUT = "G18 synthetic input"
REPLY = "G18 synthetic reply"


def run(wrapper: Path, trace: Path, argv: list[str]) -> None:
    if any(name == "loushang" or name.startswith("loushang.") for name in sys.modules):
        raise RuntimeError("Product must not be preloaded in the synthetic child")
    fd = os.open(trace, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    records = 0
    fsync_calls = 0
    fsync_seconds = 0.0
    full_model_input_rebuilds = 0
    resume_writer_acquire_seconds: list[float] = []
    metric_lock = Lock()
    resume_probe = any(
        argument == "--resume" or argument.startswith("--resume=")
        for argument in argv
    )
    process_started = time.process_time()
    original_fsync = os.fsync

    def observed_fsync(fd) -> None:
        nonlocal fsync_calls, fsync_seconds
        started = time.perf_counter()
        try:
            original_fsync(fd)
        finally:
            elapsed = time.perf_counter() - started
            with metric_lock:
                fsync_calls += 1
                fsync_seconds += elapsed

    os.fsync = observed_fsync

    def emit(phase: str, **values) -> None:
        nonlocal records
        records += 1
        if records > 16:
            raise RuntimeError("synthetic observation record budget exceeded")
        payload = (
            json.dumps(
                dict(
                    seq=records,
                    phase=phase,
                    pid=os.getpid(),
                    ns=time.monotonic_ns(),
                    **values,
                )
            ).encode()
            + b"\n"
        )
        if len(payload) > 2048:
            raise RuntimeError("synthetic observation size budget exceeded")
        if os.write(fd, payload) != len(payload):
            raise RuntimeError("incomplete synthetic observation")

    async def stream(model, context, options=None):
        from loushang.ai.event_stream.stream import AssistantMessageEventStream
        from loushang.ai.types import AssistantMessage, TextPart, Usage

        latest = context.messages[-1]
        text = (
            latest.content
            if isinstance(latest.content, str)
            else "".join(
                part.text for part in latest.content if isinstance(part, TextPart)
            )
        )
        if latest.role != "user" or text != INPUT:
            raise RuntimeError("unexpected synthetic first-turn input")
        emit(
            "model_input",
            length=len(text),
            digest=hashlib.sha256(text.encode()).hexdigest(),
        )
        message = AssistantMessage(
            role="assistant",
            content=[TextPart(type="text", text=REPLY)],
            api=model.api,
            endpoint=model.endpoint_id,
            provider=model.provider_id,
            model=model.id,
            response_id=None,
            timestamp=0,
            usage=Usage(
                input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
            ),
            stop_reason="stop",
            error_message=None,
        )
        result = AssistantMessageEventStream()
        result.push({"type": "start", "partial": message})
        result.push(
            {
                "type": "text_delta",
                "content_index": 0,
                "delta": REPLY,
                "partial": message,
            }
        )
        result.push({"type": "done", "reason": "stop", "message": message})
        return result

    class Hook:
        def find_spec(self, fullname, path=None, target=None):
            if fullname not in {
                "loushang.agent.agent",
                "loushang.coding.interaction.resume_history",
                "loushang.coding.runtime.agent_session_runtime",
                "loushang.coding.session_manager",
                "loushang.coding.session.agent_session",
                "loushang.harness.session.agent_product",
                "loushang.harness.transcript.model_input",
            }:
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None or spec.loader is None:
                raise ImportError(fullname)
            original = spec.loader

            class Loader:
                def create_module(self, spec):
                    return original.create_module(spec)

                def exec_module(self, module):
                    original.exec_module(module)
                    if fullname in {
                        "loushang.agent.agent",
                        "loushang.harness.session.agent_product",
                    }:
                        emit("hook_installed", module=fullname, origin=module.__file__)
                    if fullname == "loushang.agent.agent":
                        from loushang.agent.model_transport import (
                            synthetic_model_transport,
                        )

                        synthetic_model_transport(stream)
                        init = module.Agent.__init__

                        def initialize(self, **kwargs):
                            if kwargs.get("stream_fn") is not None:
                                raise RuntimeError(
                                    "unexpected existing model transport"
                                )
                            init(self, **{**kwargs, "stream_fn": stream})

                        module.Agent.__init__ = initialize
                    elif fullname == "loushang.harness.session.agent_product":
                        prompt = module.AgentProductSession.prompt

                        async def observed(self, *args, **kwargs):
                            emit("prompt_entered")
                            try:
                                value = await prompt(self, *args, **kwargs)
                            except BaseException:
                                emit("prompt_failed")
                                raise
                            emit("prompt_returned")
                            return value

                        module.AgentProductSession.prompt = observed
                    elif (
                        resume_probe
                        and fullname
                        == "loushang.coding.runtime.agent_session_runtime"
                    ):
                        runtime = module.AgentSessionRuntime
                        preview = runtime.preview_resume_history
                        start_plan = runtime.start_configured_resume_planning
                        prepare_plan = runtime.prepare_configured_resume_plan

                        async def observed_preview(self, *args, **kwargs):
                            value = await preview(self, *args, **kwargs)
                            emit("resume_history_ready")
                            return value

                        async def observed_start_plan(self, *args, **kwargs):
                            value = await start_plan(self, *args, **kwargs)
                            emit("resume_plan_started", configured=value is True)
                            task = self._resume_planning._task
                            if task is not None:
                                def plan_done(done):
                                    emit(
                                        "resume_background_plan_ready",
                                        status=(
                                            "cancelled"
                                            if done.cancelled()
                                            else "failed"
                                            if done.exception() is not None
                                            else "ready"
                                        ),
                                    )

                                task.add_done_callback(plan_done)
                            return value

                        async def observed_prepare_plan(self, *args, **kwargs):
                            value = await prepare_plan(self, *args, **kwargs)
                            emit("resume_plan_ready")
                            return value

                        runtime.preview_resume_history = observed_preview
                        runtime.start_configured_resume_planning = observed_start_plan
                        runtime.prepare_configured_resume_plan = observed_prepare_plan
                    elif (
                        resume_probe
                        and fullname == "loushang.coding.session_manager"
                    ):
                        manager = module.SessionManager
                        descriptor = manager.__dict__["_load_resume_writer"]
                        load_writer = descriptor.__func__

                        async def observed_writer(cls, *args, **kwargs):
                            started = time.perf_counter()
                            try:
                                return await load_writer(cls, *args, **kwargs)
                            finally:
                                resume_writer_acquire_seconds.append(
                                    time.perf_counter() - started
                                )

                        manager._load_resume_writer = classmethod(observed_writer)
                    elif (
                        resume_probe
                        and fullname == "loushang.coding.session.agent_session"
                    ):
                        session = module.AgentSession
                        commit = session._commit_resume_first_user_input

                        async def observed_commit(self, *args, **kwargs):
                            value = await commit(self, *args, **kwargs)
                            emit("resume_input_durable")
                            return value

                        session._commit_resume_first_user_input = observed_commit
                    elif (
                        resume_probe
                        and fullname == "loushang.coding.interaction.resume_history"
                    ):
                        actions = module._HistoryActions
                        submit = actions.submit

                        async def observed_submit(self, action):
                            if action.text == INPUT:
                                emit("resume_input_accepted")
                            return await submit(self, action)

                        actions.submit = observed_submit
                    elif (
                        resume_probe
                        and fullname == "loushang.harness.transcript.model_input"
                    ):
                        rebuild = module.rebuild_model_input

                        def observed_rebuild(*args, **kwargs):
                            nonlocal full_model_input_rebuilds
                            full_model_input_rebuilds += 1
                            return rebuild(*args, **kwargs)

                        module.rebuild_model_input = observed_rebuild

            spec.loader = Loader()
            return spec

    def no_network(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError("network is forbidden in synthetic startup evidence")

    hook = Hook()
    sys.addaudithook(no_network)
    sys.meta_path.insert(0, hook)
    try:
        sys.argv = [str(wrapper), *argv]
        runpy.run_path(str(wrapper), run_name="__main__")
    finally:
        sys.meta_path.remove(hook)
        if resume_probe:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            with metric_lock:
                fsync_count = fsync_calls
                fsync_elapsed = fsync_seconds
            emit(
                "resume_process_resources",
                cpu_seconds=time.process_time() - process_started,
                peak_rss_kib=usage.ru_maxrss,
                open_fds=len(tuple(Path("/proc/self/fd").iterdir())),
                fsync_calls=fsync_count,
                fsync_seconds=fsync_elapsed,
                resume_writer_acquire_seconds=resume_writer_acquire_seconds,
                full_model_input_rebuilds=full_model_input_rebuilds,
            )
        os.fsync = original_fsync
        os.close(fd)


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])
