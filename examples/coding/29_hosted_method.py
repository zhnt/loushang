"""Offline AppHost/AppService SDK → fixed Method → Work execution and query.

No API key, network model, remote transport, or Goal scheduler is used. Work
facts live until the application closes. result.json is a display snapshot,
not a resumable Work log. An optional --output-dir must be a fresh directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

from loushang.agent import synthetic_model_transport
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.appserver.protocol import (
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
)
from loushang.coding.hosted_bootstrap import CodingHostedLaunchV1
from loushang.coding.hosted_method import CodingHostedMethodV1
from loushang.coding.hosted_method_application import create_coding_method_application
from loushang.method.types import MethodDescriptor


@synthetic_model_transport
async def offline_stream(model, context, options=None):
    message = AssistantMessage(
        role="assistant", api="anthropic-messages", endpoint="anthropic-messages",
        provider="offline", model="hosted-method-demo", response_id=None,
        content=[TextPart(type="text", text="The assigned Method step has run.")],
        usage=Usage(input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}),
        stop_reason="stop", error_message=None, timestamp=0,
    )
    stream = AssistantMessageEventStream()
    stream.push({"type": "start", "partial": message})
    stream.push({"type": "done", "reason": "stop", "message": message})
    return stream


async def main(root: Path) -> None:
    workspace = root / "workspace"
    workspace.mkdir()
    launch = CodingHostedLaunchV1(
        workspace, root / "application", "coding.method-demo",
        root / "cwd-sessions", root / "home-sessions",
    )
    method = CodingHostedMethodV1(MethodDescriptor(
        id="method:hosted-demo", name="Inspect and verify", kind="example",
        description="Two sequential steps on the original hosted Session.",
        content="Carry out the assigned step and report its result.",
        metadata={"frontmatter": {"plan_mode": "fixed", "steps": ["inspect", "verify"]}},
    ))
    app = await create_coding_method_application(
        launch, method, tools=[], stream_fn=offline_stream,
        model=Model(
            id="hosted-method-demo", name="Offline", provider="offline",
            endpoint="anthropic-messages",
            capabilities=Capabilities(input=("text",), context_window=128000, max_tokens=4096),
        ),
    )
    try:
        scope = app.open_client_scope()
        mux = await scope.create_mux(MuxCreateV1("method-demo"))
        selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
        await scope.attach_mux(MuxAttachV1(selector))
        mux = await scope.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
            product_id="coding", continuity_id="method-demo", scope=SessionScopeV1.CWD,
            scope_fingerprint=launch.scopes[0].fingerprint, title="Hosted Method demo",
        )))
        attachment = await scope.attach_mux(MuxAttachV1(selector))
        control = SessionSnapshotRequestV1(
            attachment.attachment_id, attachment.controller_generation, mux.members[0].member_id,
        )
        client = scope.method_work_client
        assert client is not None
        submitted = await client.submit(control, client.service_instance_id, "demo-1", "Inspect, then verify.")
        print(json.dumps({"execution_id": submitted.handle.execution_id, "status": submitted.execution.state.status.value}), flush=True)
        completed = await client.wait(control, submitted.handle)
        work = completed.observation.work
        assert work is not None and completed.observation.recording is not None
        result = {
            "execution": completed.execution.state.status.value,
            "work": work.status,
            "session_id": work.session_id,
            "run_id": work.run_id,
            "steps": [{"step": step.step_id, "status": step.status} for step in work.steps],
            "recording": completed.observation.recording.retention,
            "model_transport": "offline",
            "output_dir": str(root),
        }
        (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        if result["execution"] != "succeeded" or result["work"] != "completed":
            raise RuntimeError("hosted Method did not complete")
    finally:
        await app.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir is None:
        output = Path(tempfile.mkdtemp(prefix="loushang-hosted-method-")).resolve()
    else:
        output = args.output_dir.resolve()
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
    # Keep this demonstration's configuration and native resources local.
    for variable, leaf in (("LOUSHANG_HOME", "platform"), ("LOUSHANG_RUNTIME_DIR", "runtime"), ("LOUSHANG_TMPDIR", "scratch")):
        os.environ[variable] = str(output / leaf)
    asyncio.run(main(output))
