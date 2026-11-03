"""Offline AppHost → Goal → model planning → Method/Work → independent verification.

Uses a deterministic prepared-request provider, not a live model. This checks
hosted integration; it is not evidence of new model planning ability. The
calculator task and verifier are the existing fixed profile. No restart/resume
or remote protocol is enabled. The caller owns and closes the application.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
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
from loushang.coding.hosted_goal_application import (
    CodingHostedGoalV1,
    create_coding_goal_application,
)

FIXED = '''def subtract(a, b):
    return a - b


def clamp(value, lower, upper):
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value
'''


class CalculatorAdapter:
    api = "hosted-goal-offline"

    def __init__(self, workspace):
        self.workspace = workspace
        self.calls = self.plans = 0
        self.wrote = False

    def prepare_request(self, request):
        return PreparedModelRequest.from_provider_request(request, payload={
            "system": request.context.system_prompt,
            "messages": [serialize_message(m) for m in request.context.messages],
            "tools": [t.name for t in request.context.tools or ()], "model": request.model.id,
        })

    async def invoke_raw(self, request):
        async for event in self.invoke_prepared_raw(request, self.prepare_request(request)):
            yield event

    async def invoke_prepared_raw(self, request, prepared):
        self.calls += 1
        assert request.options.max_output_tokens <= 1024
        assert request.options.retry.max_attempts == 1
        prepared.payload_for_transport()
        yield {"type": "response_start", "response_id": f"hosted-{self.calls}"}
        names = {t.name for t in request.context.tools or ()}
        if not names:
            action = ("check", "repair", "verify_all")[min(self.plans, 2)]
            self.plans += 1
            targets = ["subtraction", "clamp"] if action == "check" else ["calculator"] if action == "repair" else []
            value = {
                "next_action": action, "targets": targets,
                "requirement_ids": ["R-SUB", "R-CLAMP", "R-FILES"],
                "rationale": "Use the latest execution evidence",
                "expected_evidence": ["method_execution"] if action == "repair" else ["report", "validation"],
                "remaining_route": [{"action": action, "targets": targets}],
                "change_reason": "Follow the completed check or repair", "evidence_refs": [],
            }
            yield {"type": "text_delta", "text": json.dumps(value)}
        elif names == {"read", "edit", "write"} and not self.wrote:
            self.wrote = True
            yield {"type": "tool_call_start", "id": "fix-calculator", "name": "write"}
            yield {"type": "tool_call_args_delta", "delta": json.dumps({"path": str(self.workspace / "calculator.py"), "content": FIXED})}
            yield {"type": "tool_call_done"}
            yield {"type": "stop_reason", "stop_reason": "toolUse"}
            yield {"type": "response_done"}
            return
        else:
            yield {"type": "text_delta", "text": "Inspect or repair step complete; independent verification must decide."}
        yield {"type": "stop_reason", "stop_reason": "stop"}
        yield {"type": "response_done"}


def task(tmp_path):
    workspace = tmp_path / "workspace"
    shutil.copytree(Path(__file__).with_name("goal_calculator"), workspace)
    launch = CodingHostedLaunchV1(workspace, tmp_path / "application", "coding.goal-test",
                                 tmp_path / "cwd-sessions", tmp_path / "home-sessions")
    return launch, CodingHostedGoalV1(workspace, tmp_path / "goal-data")


async def application(launch, config, adapter):
    get_default_api_registry().register_api_adapter(adapter, source_id=adapter.api)
    model = Model(id="offline-calculator", provider="offline", endpoint="offline", api=adapter.api,
                  base_url="https://unused.invalid", auth=Auth(kind="none"),
                  capabilities=Capabilities(input=("text",), output=("text",), context_window=128000,
                                            max_tokens=4096, stream=True, tool_use=True))
    app = await create_coding_goal_application(launch, config, model=model)
    try:
        scope = app.open_client_scope()
        mux = await scope.create_mux(MuxCreateV1("goal"))
        selector = MuxSelectorV1(mux_space_id=mux.mux_space_id)
        await scope.attach_mux(MuxAttachV1(selector))
        mux = await scope.open_member(MuxMemberOpenV1(selector, SessionOpenSpecV1(
            product_id="coding", continuity_id="goal", scope=SessionScopeV1.CWD,
            scope_fingerprint=launch.scopes[0].fingerprint, title="Hosted Goal",
        )))
        attachment = await scope.attach_mux(MuxAttachV1(selector))
        control = SessionSnapshotRequestV1(attachment.attachment_id, attachment.controller_generation, mux.members[0].member_id)
        return app, scope, control, selector
    except BaseException:
        await app.close()
        raise


async def main(root):
    launch, config = task(root)
    adapter = CalculatorAdapter(config.workspace)
    app, scope, control, _ = await application(launch, config, adapter)
    try:
        client = scope.goal_client
        submitted = await client.start(control, client.service_instance_id, "calculator-demo")
        print(json.dumps({"event": "accepted", "execution_id": submitted.handle.execution_id}), flush=True)
        result = await client.wait(control, submitted.handle)
        output = {"execution": result.execution.state.status.value, "goal": asdict(result.observation),
                  "model_transport": "offline", "output_dir": str(root)}
        (root / "result.json").write_text(json.dumps(output, indent=2) + "\n")
        print(json.dumps(output), flush=True)
        if output["execution"] != "succeeded" or result.observation.validity != "current":
            raise RuntimeError("hosted Goal did not complete")
    finally:
        await app.close()
        get_default_api_registry().unregister_api_adapters(adapter.api)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir is None:
        root = Path(tempfile.mkdtemp(prefix="loushang-hosted-goal-")).resolve()
    else:
        root = args.output_dir.resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for key, leaf in (("LOUSHANG_HOME", "platform"), ("LOUSHANG_RUNTIME_DIR", "runtime"), ("LOUSHANG_TMPDIR", "scratch")):
        os.environ[key] = str(root / leaf)
    asyncio.run(main(root))
