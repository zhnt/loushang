"""Durable interactive sampling over the existing Linux G18 pause protocol.

Only a published safe pause resumes. A failed/in-flight attempt is evidence,
never a cursor that may be silently retried. Collection is not acceptance.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import sys
import tempfile
from collections.abc import Callable
from importlib.metadata import distributions
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "interactive_checkpoint", Path(__file__).with_name("_g18_checkpoint.py")
)
checkpoint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checkpoint)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observer_identity(repo: Path, provenance) -> dict:
    # Source modules loaded by observer helpers must come from this checkout,
    # never from one of the measured installations or a user site override.
    for name, module in tuple(sys.modules.items()):
        if name == "loushang" or name.startswith("loushang."):
            origin = getattr(module, "__file__", None)
            if origin and not Path(origin).resolve().is_relative_to(repo / "src"):
                raise ValueError("observer Product module origin changed")
    return dict(
        commit=provenance._git(repo, "rev-parse", "HEAD").decode().strip(),
        executable=str(Path(sys.executable).resolve()),
        executable_sha256=checkpoint.file_hash(Path(sys.executable)),
        python=sys.version,
        prefix=sys.prefix,
        dependencies=sorted(
            [
                item.metadata["Name"],
                item.version,
                str(Path(item.locate_file("")).resolve()),
            ]
            for item in distributions()
        ),
    )


def bytecode_manifest(prefix: Path) -> dict:
    """Seal existing installation bytecode; all warmup happens before freeze."""
    result = {}
    for path in sorted(prefix.rglob("*.pyc")):
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("non-canonical installation bytecode")
        result[str(path.relative_to(prefix))] = checkpoint.file_hash(path)
    return result


def freeze_installed_plan(configuration: dict) -> dict:
    """Derive receipts from an explicit experiment configuration after warmup.

    This neither warms Product workloads nor silently chooses a performance
    threshold. Callers must declare both before freezing the experiment.
    """
    import copy

    plan = copy.deepcopy(configuration)
    repo = Path(__file__).resolve().parents[2]
    measure = _load(
        "interactive_freeze_verifier", repo / "scripts/dev/measure_g18_startup.py"
    )
    provenance = measure.provenance_module()
    provenance.require_clean_product(repo)
    budget = plan["max_input_observer_seconds"]
    if type(budget) not in (float, int) or not math.isfinite(budget) or budget <= 0:
        raise ValueError("explicit positive observer budget required")
    if not plan["cases"] or any(
        case not in {"new-edit", "resume-edit", "new-turn", "resume-turn"}
        for case in plan["cases"]
    ):
        raise ValueError("unsupported frozen cases")
    if len(set(plan["cases"])) != len(plan["cases"]):
        raise ValueError("duplicate frozen cases")
    for key in ("blocks", "pairs_per_block"):
        if type(plan[key]) is not int or plan[key] < 1:
            raise ValueError("positive schedule required")
    plan.update(
        repo=str(repo),
        bytecode_policy="warm-installation",
        helpers=provenance.helper_manifest(repo),
        observer_identity=observer_identity(repo, provenance),
    )
    for key in ("seed", "resume_workspace", "verification_root"):
        plan[key] = str(Path(plan[key]).resolve(strict=True))
    for key in ("wheels", "installations"):
        plan[key] = {
            side: str(Path(plan[key][side]).resolve(strict=True)) for side in ("a", "b")
        }
    if plan["installations"]["a"] == plan["installations"]["b"]:
        raise ValueError("A/B installations must be independent directories")
    plan["seed_sha256"] = checkpoint.file_hash(Path(plan["seed"]))
    plan["resume_workspace_manifest"] = checkpoint.tree_manifest(
        Path(plan["resume_workspace"])
    )
    plan["sources"], plan["installation_receipts"], plan["bytecode_manifests"] = (
        {},
        {},
        {},
    )
    for side in ("a", "b"):
        wheel, prefix = Path(plan["wheels"][side]), Path(plan["installations"][side])
        source = provenance.verify_wheel_at_commit(repo, wheel, plan["revisions"][side])
        plan["sources"][side] = source
        with tempfile.TemporaryDirectory(
            prefix="freeze-interactive-", dir=plan["verification_root"]
        ) as scratch:
            plan["installation_receipts"][side] = measure.verify_pinned_install(
                prefix, wheel, Path(scratch), source["wheel_sha256"]
            )
        plan["bytecode_manifests"][side] = bytecode_manifest(prefix)
    validate_installed_inputs(plan)
    return plan


def validate_installed_inputs(plan: dict, *, measured_side: str | None = None) -> None:
    """Read-only source checks plus isolated installation verification children.

    Scratch is outside the measured sample. This may warm metadata/page caches;
    the campaign therefore makes only the declared warm-start comparison.
    """
    repo = Path(__file__).resolve().parents[2]
    if plan["repo"] != str(repo) or plan["bytecode_policy"] != "warm-installation":
        raise ValueError("wrong observer checkout or bytecode policy")
    measure = _load(
        "interactive_install_verifier", repo / "scripts/dev/measure_g18_startup.py"
    )
    provenance = measure.provenance_module()
    provenance.require_clean_product(repo)
    if observer_identity(repo, provenance) != plan["observer_identity"]:
        raise ValueError("observer source or environment changed")
    if provenance.helper_manifest(repo) != plan["helpers"]:
        raise ValueError("observer helpers changed")
    if checkpoint.file_hash(Path(plan["seed"])) != plan["seed_sha256"]:
        raise ValueError("resume seed changed")
    if (
        checkpoint.tree_manifest(Path(plan["resume_workspace"]))
        != plan["resume_workspace_manifest"]
    ):
        raise ValueError("resume workspace changed")
    receipts = {}
    # The measured side is always checked last, irrespective of A/B schedule.
    order = ("b", "a") if measured_side == "a" else ("a", "b")
    for side in order:
        if (
            bytecode_manifest(Path(plan["installations"][side]))
            != plan["bytecode_manifests"][side]
        ):
            raise ValueError("installation bytecode changed")
        expected = plan["sources"][side]
        wheel = Path(plan["wheels"][side])
        source = provenance.verify_wheel_at_commit(repo, wheel, expected["commit"])
        if source != expected:
            raise ValueError("source or wheel changed")
        with tempfile.TemporaryDirectory(
            prefix="verify-interactive-", dir=plan["verification_root"]
        ) as scratch:
            receipt = measure.verify_pinned_install(
                Path(plan["installations"][side]),
                wheel,
                Path(scratch),
                expected["wheel_sha256"],
            )
        if receipt != plan["installation_receipts"][side]:
            raise ValueError("installation changed")
        receipts[side] = receipt
    for key in ("python", "dependencies", "entries"):
        if receipts["a"][key] != receipts["b"][key]:
            raise ValueError(f"paired installation contract differs: {key}")
    for key in ("lock_sha256", "project_sha256"):
        if plan["sources"]["a"][key] != plan["sources"]["b"][key]:
            raise ValueError(f"paired source contract differs: {key}")


def collect_installed(
    output: Path, plan: dict, *, resume=False, pause_after=None
) -> dict:
    """Bind the checkpoint protocol to the real installed PTY probe."""
    repo = Path(__file__).resolve().parents[2]
    # The existing test-only observer imports sibling support modules. Product
    # children do not inherit these paths: installed measure removes PYTHONPATH.
    previous_path = sys.path[:]
    try:
        sys.path[:0] = [str(repo), str(repo / "tests/coding")]
        probe = _load(
            "interactive_installed_probe",
            repo / "tests/coding/_interactive_startup_probe.py",
        )

        def observe(root: Path, case: str, side: str) -> dict:
            # Check again between samples, not just at campaign entry/finish.
            validate_installed_inputs(plan, measured_side=side)
            result = probe.measure(
                root,
                repo,
                Path(plan["installations"][side]) / "bin/python",
                installed=True,
                synthetic=case.endswith("-turn"),
                edit_train=case.endswith("-edit"),
                seed=Path(plan["seed"]) if case.startswith("resume-") else None,
                workspace=Path(plan["resume_workspace"])
                if case.startswith("resume-")
                else None,
            )
            validate_installed_inputs(plan, measured_side=side)
            return result

        return collect(
            output,
            plan,
            observe,
            validate_installed_inputs,
            validate_workload,
            resume=resume,
            pause_after=pause_after,
        )
    finally:
        sys.path[:] = previous_path


def validate_workload(plan: dict, case: str, side: str, report: dict) -> None:
    """Validate installed probe evidence, not relative performance acceptance.

    The immutable plan supplies expected installations, seed and observer budget.
    Slow but faithfully observed input is valid evidence of a slow implementation.
    """

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    def number(value, name: str) -> float:
        require(type(value) in (int, float), f"invalid numeric {name}")
        require(math.isfinite(value) and value >= 0, f"invalid numeric {name}")
        return value

    def close(actual, expected, name: str) -> None:
        require(
            math.isclose(number(actual, name), expected, rel_tol=0, abs_tol=1e-7),
            f"inconsistent {name}",
        )

    require(
        case in {"new-edit", "resume-edit", "new-turn", "resume-turn"}, "unknown case"
    )
    require(side in {"a", "b"}, "unknown side")
    require(
        report.get("schema") == 3 and report.get("status") == "complete",
        "incomplete probe",
    )
    require(
        report.get("installation") == plan["installations"][side], "wrong installation"
    )
    require(
        report.get("seed") == (plan["seed"] if case.startswith("resume-") else None),
        "wrong seed",
    )
    editing = case.endswith("-edit")
    require(report.get("synthetic") is (not editing), "wrong synthetic workload")
    require(report.get("instrumented") is (not editing), "unexpected instrumentation")
    metrics = report["metrics"]
    for key in (
        "first_frame_seconds",
        "initial_echo_seconds",
        "ready_observed_seconds",
        "exit_seconds",
    ):
        number(metrics[key], key)
    sent = number(report["input_sent_seconds"], "input sent")
    require(
        metrics["first_frame_seconds"] <= sent,
        "invalid startup order",
    )
    require(
        metrics["first_frame_seconds"] <= metrics["ready_observed_seconds"],
        "ready precedes first frame",
    )
    budget = number(plan["max_input_observer_seconds"], "observer budget")
    require(budget > 0, "observer budget must be positive")
    observer = report["startup_observer"]
    require(
        observer.get("timestamp_basis") == "snapshot-before-replay",
        "wrong timestamp basis",
    )
    maximum = number(observer["max_input_frame_processing_seconds"], "observer maximum")
    total = number(observer["input_frame_processing_seconds"], "observer total")
    require(maximum <= total and maximum <= budget, "observer overhead budget exceeded")
    if not editing:
        require("edit_train" not in report, "unexpected edit train")
        reply = number(metrics["first_reply_seconds"], "first reply")
        settled = number(metrics["prompt_settled_observed_seconds"], "prompt settled")
        through = number(metrics["spawn_through_reply_seconds"], "spawn through reply")
        require(
            reply <= settled and through >= metrics["ready_observed_seconds"] + reply,
            "invalid first-turn order",
        )
        require(
            through - reply + 1e-7 >= sent + metrics["initial_echo_seconds"],
            "first turn precedes draft echo",
        )
        trace = report["synthetic_trace"]
        phases = [
            row.get("phase") for row in trace if row.get("phase") != "hook_installed"
        ]
        require(
            phases == ["prompt_entered", "model_input", "prompt_returned"],
            "wrong model call count or settlement",
        )
        model_input = next(row for row in trace if row.get("phase") == "model_input")
        expected_input = b"G18 synthetic input"
        require(
            model_input.get("length") == len(expected_input)
            and model_input.get("digest") == hashlib.sha256(expected_input).hexdigest(),
            "wrong first-turn input",
        )
        return
    train = report["edit_train"]
    require(
        train.get("workload") == "fixed-cadence-cumulative-append-v1",
        "wrong edit workload",
    )
    require(
        train.get("planned_count") == 100 and train.get("interval_seconds") == 0.1,
        "wrong edit schedule",
    )
    require(observation_valid(report), "incomplete edit observation")
    rows = train["rows"]
    require(
        len(rows) == 100 and train.get("attempted_count") == 100, "wrong attempt count"
    )
    anchor = number(train["anchor"], "anchor")
    start = number(report["spawn"]["start"], "spawn start")
    close(anchor - start, sent, "input anchor")
    token = "G18draftQ7"
    delays, lags = [], []
    previous_sent, previous_echo = 0.0, 0.0
    for index, row in enumerate(rows):
        token += f"{index:02x}"
        require(
            row.get("token") == token and row.get("written") is True,
            "invalid edit receipt",
        )
        planned = number(row["planned"], "planned")
        written = number(row["sent"], "sent")
        echo = number(row["echo"], "echo")
        close(planned, anchor + index * 0.1, "planned edit")
        require(planned <= written <= echo, "invalid edit order")
        require(
            written >= previous_sent and echo >= previous_echo,
            "nonmonotonic edit witnesses",
        )
        previous_sent, previous_echo = written, echo
        lag, delay = written - planned, echo - written
        close(row["pacing_lag_seconds"], lag, "pacing lag")
        close(row["echo_seconds"], delay, "echo latency")
        require(lag <= 0.025, "sender lag exceeds protocol")
        delays.append(delay)
        lags.append(lag)
    ready = start + metrics["ready_observed_seconds"]
    require(
        start + sent + metrics["initial_echo_seconds"] <= rows[0]["echo"],
        "initial draft echo follows cumulative echo",
    )
    require(rows[0]["sent"] < ready < rows[-1]["sent"], "edits do not span ready")
    close(train["mean_observed_echo_seconds"], sum(delays) / len(delays), "mean echo")
    close(train["max_observed_echo_seconds"], max(delays), "maximum echo")
    close(train["max_pacing_lag_seconds"], max(lags), "maximum pacing lag")
    groups = {
        "echo_before_observed_ready": [row for row in rows if row["echo"] < ready],
        "pending_across_observed_ready": [
            row for row in rows if row["sent"] < ready <= row["echo"]
        ],
        "sent_after_observed_ready": [row for row in rows if row["sent"] >= ready],
    }
    for name, group in groups.items():
        summary = train["by_observed_ready"][name]
        require(
            summary.get("count") == len(group) and summary.get("missing_count") == 0,
            "wrong phase counts",
        )
        if group:
            values = [row["echo_seconds"] for row in group]
            close(summary["mean_echo_seconds"], sum(values) / len(values), "phase mean")
            close(summary["max_echo_seconds"], max(values), "phase maximum")
        else:
            require(
                summary.get("mean_echo_seconds") is None
                and summary.get("max_echo_seconds") is None,
                "nonempty phase latency",
            )


def observation_valid(report: dict) -> bool:
    if report.get("status") != "complete":
        return False
    train = report.get("edit_train")
    if train is None:
        return bool(report.get("synthetic")) and all(
            key in report.get("metrics", {})
            for key in ("first_reply_seconds", "prompt_settled_observed_seconds")
        )
    count = train.get("planned_count")
    return (
        type(count) is int
        and count > 0
        and train.get("sender_schedule_valid") is True
        and train.get("sent_count") == train.get("observed_count") == count
        and train.get("unsent_count") == train.get("missing_count") == 0
        and train.get("spans_ready") is True
        and train.get("sender_failure") is None
    )


def collect(
    output: Path,
    plan: dict,
    observe: Callable[[Path, str, str], dict],
    validate_inputs: Callable[[dict], None],
    validate_observation: Callable[[dict, str, str, dict], None],
    *,
    resume: bool = False,
    pause_after: int | None = None,
) -> dict:
    """Collect an immutable plan; callbacks own verified inputs and child cleanup."""
    if (
        type(plan.get("blocks")) is not int
        or plan["blocks"] < 1
        or type(plan.get("pairs_per_block")) is not int
        or plan["pairs_per_block"] < 1
        or not plan.get("cases")
        or len(set(plan["cases"])) != len(plan["cases"])
    ):
        raise ValueError("positive blocks/pairs and unique cases required")
    with checkpoint.Campaign(
        output, resume=resume, pause_after=pause_after
    ) as campaign:
        report = (
            campaign.report
            if resume
            else {
                "cases": plan["cases"],
                "blocks": plan["blocks"],
                "pairs_per_block": plan["pairs_per_block"],
                "samples": [],
            }
        )
        campaign.begin(report, plan)  # Consume a pause before any input callback.
        target = campaign.output / "report.json"
        checkpoint.durable_write(target, report)
        try:
            validate_inputs(plan)
            schedule = checkpoint.schedule(
                report["cases"], report["blocks"], report["pairs_per_block"]
            )
            for index in range(len(report["samples"]), len(schedule)):
                block, pair, case, side = schedule[index]
                root = campaign.output / f"sample-{index + 1:04d}"
                if root.exists():
                    raise ValueError(
                        "sample destination already exists; never overwrite evidence"
                    )
                sample = dict(
                    block=block,
                    pair=pair,
                    case=case,
                    side=side,
                    iteration=index + 1,
                    warmup=pair == -1,
                    status="running",
                    valid=False,
                )
                report["samples"].append(sample)
                checkpoint.durable_write(target, report)
                raw = observe(root, case, side)
                receipt = root / "report.json"
                if checkpoint.read_json(receipt) != raw:
                    raise ValueError(
                        "returned observation differs from its raw receipt"
                    )
                with receipt.open("rb") as stream:
                    os.fsync(stream.fileno())
                directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                validate_observation(plan, case, side, raw)
                sample.update(
                    status="complete",
                    valid=observation_valid(raw),
                    receipt=str(receipt),
                    receipt_sha256=checkpoint.file_hash(receipt),
                )
                checkpoint.durable_write(target, report)
                if not sample["valid"]:
                    raise ValueError(
                        "observation is incomplete or sender schedule invalid"
                    )
                if (index + 1) % 2 == 0 and campaign.wants_pause(report):
                    campaign.pause(report, resources={})
            validate_inputs(plan)
            checkpoint.evidence_files(report)  # Recheck every prior raw receipt.
            report.update(status="complete", comparison={"verdict": "not-evaluated"})
            campaign.finish(report)
        except checkpoint.Paused:
            return report
        except BaseException as error:
            report.update(status="failed", failure=f"{type(error).__name__}: {error}")
            checkpoint.durable_write(target, report)
            raise
        return report


def publish_frozen_plan(path: Path, plan: dict) -> None:
    """Atomic create-only publication; a concurrent freeze cannot be replaced."""
    import json

    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=".interactive-plan-"
    ) as temporary:
        json.dump(plan, temporary, indent=2, allow_nan=False)
        temporary.write("\n")
        temporary.flush()
        os.fsync(temporary.fileno())
        os.link(temporary.name, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--pause-after", type=int)
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="read experiment configuration from --plan; write frozen plan to --output, without sampling",
    )
    args = parser.parse_args()
    plan = checkpoint.read_json(args.plan)
    if args.freeze:
        if args.resume or args.pause_after is not None:
            parser.error("freeze cannot resume or pause collection")
        if args.output.exists() or args.output.is_symlink():
            parser.error("refuse to overwrite a frozen plan")
        frozen = freeze_installed_plan(plan)
        publish_frozen_plan(args.output, frozen)
        print(json.dumps({"status": "frozen", "plan": str(args.output)}))
        return
    report = collect_installed(
        args.output, plan, resume=args.resume, pause_after=args.pause_after
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "samples": len(report["samples"]),
                "comparison": report.get("comparison", {"verdict": "not-evaluated"}),
            }
        )
    )


if __name__ == "__main__":
    main()
