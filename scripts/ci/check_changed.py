"""Run the local portion of the same check plan used by Actions."""

from __future__ import annotations

import argparse
import json
import sys

from run_checks import commands, run
from select_checks import ROOT, local_paths, select


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    plan = select(local_paths(args.base), full=args.full)
    artifact = ROOT / ".artifacts/check-plan.json"
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text(json.dumps(plan, indent=2) + "\n")
    pending = []
    for scope, selected in plan["checks"].items():
        if not selected:
            continue
        print(f"{scope}: {'; '.join(plan['reasons'][scope])}", flush=True)
        try:
            planned = commands(scope)
        except ValueError:
            pending.append(scope)
            continue
        if args.plan_only:
            for command in planned:
                print("  " + " ".join(command))
        else:
            run(scope)
    if pending:
        print(
            "Platform/installation/real-LSP checks still required in Actions: "
            + ", ".join(pending)
        )
    print(f"Plan: {artifact}")
    if sys.platform == "win32" and not args.plan_only:
        print(
            "Legacy Make-based scopes currently require Make; plan generation is cross-platform."
        )


if __name__ == "__main__":
    main()
