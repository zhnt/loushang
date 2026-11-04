"""Linux offline Coding SDK → Work references → separate-process cold read.

Run with --output-dir pointing to a fresh private directory. --reopen consumes
only the saved Product binding and original stores; it creates no SDK Session.
The model transport is deterministic and uses no network or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loushang.agent import synthetic_model_transport
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.coding import create_agent_session_runtime
from loushang.coding.adapters.harnesswork import create_coding_work_runtime
from loushang.foundation.platform_paths import resolve_platform_home
from loushang.harness.transcript.source_reader import TranscriptSourceReader
from loushang.harnesswork import JsonlEventLogBackend, WorkRecordingPolicy
from loushang.harnesswork.integrations.session import SessionWorkTurn
from loushang.harnesswork.integrations.transcript import (
    WorkTranscriptSource,
    resolve_work_transcript,
)
from loushang.harnesswork.recording import project_work_recording


@synthetic_model_transport
async def offline_stream(model, context, options=None):
    message = AssistantMessage(
        role="assistant",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        provider="offline",
        model="reference-demo",
        response_id=None,
        content=[
            TextPart(type="text", text="Recorded reply from the real Coding SDK.")
        ],
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0,
    )
    stream = AssistantMessageEventStream()
    stream.push({"type": "start", "partial": message})
    stream.push({"type": "done", "reason": "stop", "message": message})
    return stream


async def reopen(root: Path) -> None:
    # This manifest is Product-owned input, not an opening instruction from Work.
    binding = json.loads((root / "binding.json").read_text())
    reader = TranscriptSourceReader(
        session_file=Path(binding["session_file"]),
        conversation_id=binding["conversation_id"],
        store_state_root=Path(binding["store_state_root"]),
    )
    try:
        source = await WorkTranscriptSource.bind(
            reader,
            binding_id="reference-demo",
            retained_until=datetime.fromisoformat(binding["retained_until"]),
        )
        history = JsonlEventLogBackend(root / "work.jsonl").query()
        record = project_work_recording(history, "reference-demo")
        assert record is not None
        resolved = await resolve_work_transcript(record, history, source=source)
        assert resolved.handoffs.complete
        assert record.run.status == "completed"
        print(
            json.dumps(
                {
                    "event": "cold_read_verified",
                    "run_id": record.run.run_id,
                    "handoffs_complete": True,
                    "unique_records": len(resolved.records),
                    "bytes_read": resolved.bytes_read,
                    "ancestors_hashed": resolved.ancestors_hashed,
                }
            )
        )
    finally:
        await reader.aclose()


async def main(root: Path, read_only: bool) -> None:
    root = root.absolute()
    if read_only:
        await reopen(root)
        return
    if root.exists():
        raise ValueError("choose a fresh output directory, or use --reopen")
    root.mkdir(mode=0o700, parents=True)
    os.environ["LOUSHANG_HOME"] = str(root / "platform")
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    sdk = create_agent_session_runtime(
        session_dir=root / "data/sessions",
        model=Model(
            id="reference-demo",
            name="Offline reference demo",
            provider="offline",
            endpoint="anthropic-messages",
            capabilities=Capabilities(
                input=("text",), context_window=128000, max_tokens=1024
            ),
        ),
        stream_fn=offline_stream,
        tools=[],
        enable_multiagent=False,
        system_prompt="Reply briefly. This example verifies Transcript provenance.",
    )
    reader = work = None
    try:
        session = await sdk.create_session(cwd=str(workspace))
        path = session.session_manager.get_session_file()
        assert path is not None
        state_root = resolve_platform_home() / "state/session-stores"
        deadline = datetime.now(UTC) + timedelta(days=1)
        reader = TranscriptSourceReader(
            session_file=path,
            conversation_id=session.session_id,
            store_state_root=state_root,
        )
        source = await WorkTranscriptSource.bind(
            reader, binding_id="reference-demo", retained_until=deadline
        )
        work = create_coding_work_runtime(
            session=session,
            event_log=JsonlEventLogBackend(root / "work.jsonl"),
            session_id=lambda: session.session_id,
            transcript_source=source,
            recording_policy=WorkRecordingPolicy(require_persistence=True),
        )
        run = await work.submit_plan(
            [
                SessionWorkTurn(
                    "First recorded reply", plan_id="demo", step_id="inspect"
                ),
                SessionWorkTurn(
                    "Second recorded reply",
                    plan_id="demo",
                    step_id="verify",
                    follow_up_messages=("Final recorded reply",),
                ),
            ],
            session_id=session.session_id,
            run_id="reference-demo",
        )
        assert run.status == "completed"
        (root / "binding.json").write_text(
            json.dumps(
                {
                    "session_file": str(path),
                    "conversation_id": session.session_id,
                    "store_state_root": str(state_root),
                    "retained_until": deadline.isoformat(),
                },
                indent=2,
            )
        )
        print(
            json.dumps(
                {
                    "event": "work_completed",
                    "run_id": run.run_id,
                    "output_dir": str(root),
                }
            )
        )
    finally:
        if work is not None:
            await work.dispose()
        if reader is not None:
            await reader.aclose()
        await sdk.dispose_session_runtime()
    await reopen(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reopen", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.output_dir, args.reopen))
