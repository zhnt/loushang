"""Real opt-in Goal: failing check -> Method/model repair -> independent check.

Pass --model-planning for model-selected actions and revisable routes.
Use a fresh output directory. --reopen only reads the stored result and evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import build_kimi_model

from loushang.coding.adapters.goal import CodingGoal, inspect_goal


def show(view):
    return {
        "goal_id": view.goal.id,
        "status": view.goal.status,
        "revision": view.goal.revision,
        "epoch": view.goal.epoch,
        "validity": view.validity,
        "reason": view.reason,
        "goal_reason": view.goal.reason,
        "execution_unresolved": view.execution_unresolved,
    }


async def report_progress(owner, number):
    """Observe the original Work; this task never advances or cancels it."""
    started = asyncio.get_running_loop().time()
    while True:
        await asyncio.sleep(5)
        facts = owner.controller.facts()
        print(
            json.dumps(
                {
                    "event": "advance_in_progress",
                    "advance": number,
                    "elapsed_seconds": int(asyncio.get_running_loop().time() - started),
                    "work": [
                        {
                            "operation_id": run.operation_id,
                            "status": run.status,
                            "step_id": run.current_step_id,
                        }
                        for run in facts.runs
                    ],
                },
                sort_keys=True,
            ),
            flush=True,
        )


async def main(args):
    output = args.output_dir.expanduser().resolve()
    receipt_file = output / "receipt.json"
    workspace, data = output / "project", output / "data"
    if args.reopen:
        receipt = json.loads(receipt_file.read_text())
        view = inspect_goal(
            workspace=workspace,
            data_root=data,
            session_id=receipt["session_id"],
            goal_id="calculator",
        )
        print(json.dumps(show(view), ensure_ascii=False, sort_keys=True), flush=True)
        if view.planning is not None:
            print(
                json.dumps(
                    {"planning": view.planning}, ensure_ascii=False, sort_keys=True
                ),
                flush=True,
            )
        return (
            0 if view.goal.status == "completed" and view.validity == "current" else 1
        )
    if output.exists():
        raise ValueError(
            "choose a fresh output directory; use --reopen to read a prior run"
        )
    output.mkdir(mode=0o700, parents=True)
    shutil.copytree(Path(__file__).with_name("goal_calculator"), workspace)
    model = build_kimi_model()
    limit = 20 if args.model_planning else 6
    owner = await CodingGoal.open(
        workspace=workspace,
        data_root=data,
        model=model,
        model_planning=args.model_planning,
    )
    try:
        receipt_file.write_text(
            json.dumps(
                {
                    "session_id": owner.session_id,
                    "model_id": model.id,
                    "provider": model.provider_id,
                    "goal_id": "calculator",
                    "limit": limit,
                    "model_planning": args.model_planning,
                },
                indent=2,
            )
        )
        owner.create("calculator", command_id="create", limit=limit)
        print(
            json.dumps(
                {
                    "event": "goal_started",
                    "output_dir": str(output),
                    "note": (
                        "The model selects actions; each advance admits one planning or implementation Work."
                        if args.model_planning
                        else "Initial verification is expected to fail; model repair follows, then independent verification."
                    ),
                }
            ),
            flush=True,
        )
        for number in range(limit):
            state = owner.controller.query("calculator")
            if state.status != "active":
                break
            print(
                json.dumps({"event": "advance_started", "advance": number}),
                flush=True,
            )
            progress = asyncio.create_task(report_progress(owner, number))
            try:
                receipt = await owner.advance(
                    "calculator",
                    command_id=f"advance-{number}",
                    revision=state.revision,
                    epoch=state.epoch,
                )
            finally:
                progress.cancel()
                with suppress(asyncio.CancelledError):
                    await progress
            facts = owner.controller.facts()
            if args.model_planning:
                trace = owner.planning_trace("calculator")
                (output / "planning-trace.json").write_text(json.dumps(trace, indent=2))
                print(
                    json.dumps(
                        {
                            "event": "planning_trace",
                            "status": trace["status"],
                            "planning_intents": trace.get("planning_intents"),
                            "rejections": trace.get("rejections", []),
                            "latest_route": trace.get("routes", [])[-1:],
                        }
                    ),
                    flush=True,
                )
            print(
                json.dumps(
                    {
                        "advance": number,
                        "outcome": receipt.outcome,
                        "work": [
                            {"operation_id": r.operation_id, "status": r.status}
                            for r in facts.runs
                        ],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        view = await owner.query("calculator")
        print(json.dumps(show(view), sort_keys=True), flush=True)
        return (
            0 if view.goal.status == "completed" and view.validity == "current" else 1
        )
    finally:
        await owner.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reopen", action="store_true")
    parser.add_argument(
        "--model-planning",
        action="store_true",
        help="Let the model select the next bounded action and revise its route",
    )
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(main(args)))
    except KeyboardInterrupt:
        print(
            "Interrupted. The Goal has not been declared completed. "
            f"Records are retained in {args.output_dir.expanduser().resolve()}; "
            "use --reopen to inspect them without executing work.",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(130) from None
