"""Opt-in private Coding integration: run a check, consume and reopen evidence.

No model invocation. Use a trusted local output directory outside the checkout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from loushang.ai.model import Capabilities, Model
from loushang.coding import create_agent_session_runtime
from loushang.coding.adapters._verification_work import (
    CodingVerificationFailed,
    CodingVerificationWork,
    inspect_verification,
)
from loushang.harness.artifacts import SessionBlobStore
from loushang.harnesswork import JsonlEventLogBackend


async def main(args: argparse.Namespace) -> int:
    output = args.output_dir.expanduser().resolve()
    output.mkdir(mode=0o700, exist_ok=True)
    data = output / "data"
    data.mkdir(mode=0o700, exist_ok=True)
    receipt_path = output / "run.json"
    log_path = output / "work.jsonl"
    if not args.reopen:
        if receipt_path.exists() or log_path.exists():
            raise ValueError("use a new output directory, or --reopen")
        if not args.command:
            raise ValueError("--command is required for a new verification")
        sdk = create_agent_session_runtime(
            session_dir=data / "sessions",
            model=Model(
                id="offline-verification",
                name="Local verification",
                provider="offline",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    input=("text",), context_window=128000, max_tokens=1024
                ),
            ),
            system_prompt="Local command verification; no model invocation.",
        )
        try:
            session = await sdk.create_session(cwd=str(args.workspace.resolve()))
            receipt = {
                "session_id": session.session_id,
                "run_id": f"verify-{uuid4().hex}",
            }
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            work = CodingVerificationWork(
                session=session,
                blobs=SessionBlobStore(data, session.session_id),
                event_log=JsonlEventLogBackend(log_path),
            )
            try:
                await work.run(args.command, run_id=receipt["run_id"])
            except CodingVerificationFailed as error:
                print(str(error), file=sys.stderr)
        finally:
            await sdk.dispose_session_runtime()
    # The trusted SDK receipt selects the Session, not an arbitrary Work fact.
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    store = SessionBlobStore(data, receipt["session_id"], read_only=True)
    view = inspect_verification(
        JsonlEventLogBackend(log_path).query(), run_id=receipt["run_id"], blobs=store
    )
    print(
        json.dumps(
            {
                "run_id": view.run.run_id,
                "work_status": view.run.status,
                "verification_passed": view.passed,
                "issues": view.issues,
                "health": [
                    {"name": item.reference.logical_name, "state": item.state}
                    for item in view.health
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    for record in view.records:
        if any(
            item.reference == record.blob and item.state == "available"
            for item in view.health
        ):
            print(f"{record.role}: {store.read_bytes(record.blob).decode('utf-8')}")
    return 0 if view.passed is True else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--command")
    parser.add_argument("--reopen", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
