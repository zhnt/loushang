"""Fail closed unless every selected job succeeded and every other job skipped."""

from __future__ import annotations

import argparse
import json
import os


def verify(
    plan: dict, needs: dict, jobs: dict[str, str], *, section: str = "checks"
) -> None:
    if plan.get("version") != 1 or not isinstance(plan.get(section), dict):
        raise ValueError("missing or invalid change-selection plan")
    if set(needs) != set(jobs):
        raise ValueError(
            f"job inventory mismatch: expected {sorted(jobs)}, got {sorted(needs)}"
        )
    errors = []
    for job, scope in jobs.items():
        selected = plan[section].get(scope)
        if not isinstance(selected, bool):
            raise ValueError(f"missing boolean selection for {scope}")
        expected = "success" if selected else "skipped"
        result = needs[job].get("result")
        if result != expected:
            errors.append(f"{job}: expected {expected}, got {result}")
        print(f"{job}: {result} ({'required' if selected else 'not applicable'})")
    if errors:
        raise ValueError("; ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, help="JSON map of job IDs to scopes")
    parser.add_argument("--section", choices=("checks", "workflows"), default="checks")
    args = parser.parse_args()
    needs = json.loads(os.environ["CI_NEEDS"])
    if args.section == "workflows":
        changes = needs.pop("changes", {})
        if changes.get("result") != "success":
            raise ValueError("change selection failed or did not run")
    verify(
        json.loads(os.environ["CI_PLAN"]),
        needs,
        json.loads(args.jobs),
        section=args.section,
    )


if __name__ == "__main__":
    main()
