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
import runpy
import sys
import time
from pathlib import Path

INPUT = "G18 synthetic input"
REPLY = "G18 synthetic reply"


def run(wrapper: Path, trace: Path, argv: list[str]) -> None:
    if any(name == "loushang" or name.startswith("loushang.") for name in sys.modules):
        raise RuntimeError("Product must not be preloaded in the synthetic child")
    fd = os.open(trace, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    records = 0

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
                "loushang.harness.session.agent_product",
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
                    else:
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
        os.close(fd)


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])
