"""Fail closed unless every selected job succeeded and every other job skipped."""

from __future__ import annotations

import argparse
import json
import os


def verify(
    plan: dict, needs: dict, jobs: dict[str, str], *, section: str = "checks", reused: bool = False
) -> None:
    if plan.get("version") != 1 or not isinstance(plan.get(section), dict):
        raise ValueError("missing or invalid change-selection plan")
    if set(needs) != set(jobs):
        raise ValueError(
            f"job inventory mismatch: expected {sorted(jobs)}, got {sorted(needs)}"
        )
    if reused and section != "workflows":
        raise ValueError("PR evidence only applies to top-level workflow aggregation")
    errors = []
    for job, scope in jobs.items():
        job_section, separator, job_scope = scope.partition(".")
        if separator:
            if job_section not in {"checks", "workflows", "windows"}:
                raise ValueError(f"unknown selection section {job_section!r}")
            selected = plan.get(job_section, {}).get(job_scope)
        else:
            selected = plan[section].get(scope)
        if not isinstance(selected, bool):
            raise ValueError(f"missing boolean selection for {scope}")
        expected = "success" if selected and not reused else "skipped"
        result = needs[job].get("result")
        if result != expected:
            errors.append(f"{job}: expected {expected}, got {result}")
        print(f"{job}: {result} ({'required' if selected else 'not applicable'})")
    if errors:
        raise ValueError("; ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, help="JSON map of job IDs to scopes")
    parser.add_argument("--section", choices=("checks", "workflows", "windows"), default="checks")
    parser.add_argument("--require-changes", action="store_true")
    args = parser.parse_args()
    needs = json.loads(os.environ["CI_NEEDS"])
    if args.require_changes:
        if args.section != "workflows":
            raise ValueError("selector dependency requires workflow aggregation")
        changes = needs.pop("changes", {})
        if changes.get("result") != "success":
            raise ValueError("change selection failed or did not run")
    reused_run = os.environ.get("CI_REUSED_RUN", "")
    if reused_run:
        if not args.require_changes or not reused_run.isdigit() or int(reused_run) <= 0:
            raise ValueError("invalid reused PR evidence dependency")
        print(f"Selected checks were satisfied by successful PR run {reused_run}")
    verify(
        json.loads(os.environ["CI_PLAN"]),
        needs,
        json.loads(args.jobs),
        section=args.section,
        reused=bool(reused_run),
    )


if __name__ == "__main__":
    main()
