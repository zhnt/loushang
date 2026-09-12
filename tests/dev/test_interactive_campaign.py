"""Interrupted collections never silently overwrite or replay old observations."""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

if sys.platform != "linux":
    pytest.skip("Linux interactive checkpoints", allow_module_level=True)

SPEC = importlib.util.spec_from_file_location(
    "interactive_campaign",
    Path(__file__).resolve().parents[2] / "scripts/dev/_interactive_campaign.py",
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def collect(*args, **kwargs):
    return runner.collect(*args, validate_observation=lambda *args: None, **kwargs)


observation_valid = runner.observation_valid
durable_write = runner.checkpoint.durable_write


def raw():
    return dict(
        status="complete",
        edit_train=dict(
            planned_count=2,
            sent_count=2,
            observed_count=2,
            unsent_count=0,
            missing_count=0,
            spans_ready=True,
            sender_schedule_valid=True,
            sender_failure=None,
        ),
    )


def workload_evidence(case="new-edit"):
    plan = dict(
        installations={"a": "/isolated/a", "b": "/isolated/b"},
        seed="/isolated/seed.jsonl",
        max_input_observer_seconds=0.025,
    )
    editing = case.endswith("-edit")
    result = dict(
        schema=3,
        status="complete",
        installation=plan["installations"]["a"],
        seed=plan["seed"] if case.startswith("resume-") else None,
        synthetic=not editing,
        instrumented=not editing,
        input_sent_seconds=1.0,
        spawn=dict(start=100.0),
        metrics=dict(
            first_frame_seconds=0.5,
            initial_echo_seconds=0.01,
            ready_observed_seconds=6.0,
            exit_seconds=0.1,
        ),
        startup_observer=dict(
            timestamp_basis="snapshot-before-replay",
            input_frame_processing_seconds=0.1,
            max_input_frame_processing_seconds=0.002,
        ),
    )
    if not editing:
        result["metrics"].update(
            first_reply_seconds=0.2,
            prompt_settled_observed_seconds=0.3,
            spawn_through_reply_seconds=6.3,
        )
        result["synthetic_trace"] = [
            dict(phase="prompt_entered"),
            dict(
                phase="model_input",
                length=len(b"G18 synthetic input"),
                digest=hashlib.sha256(b"G18 synthetic input").hexdigest(),
            ),
            dict(phase="prompt_returned"),
        ]
        return plan, result
    rows = []
    token = "G18draftQ7"
    for index in range(100):
        token += f"{index:02x}"
        planned = 101.0 + index * 0.1
        sent = planned + 0.001
        echo = sent + 0.01
        rows.append(
            dict(
                token=token,
                planned=planned,
                sent=sent,
                echo=echo,
                written=True,
                echo_seconds=echo - sent,
                pacing_lag_seconds=sent - planned,
            )
        )
    result["edit_train"] = dict(
        workload="fixed-cadence-cumulative-append-v1",
        anchor=101.0,
        planned_count=100,
        interval_seconds=0.1,
        attempted_count=100,
        sent_count=100,
        observed_count=100,
        unsent_count=0,
        missing_count=0,
        spans_ready=True,
        sender_schedule_valid=True,
        sender_failure=None,
        rows=rows,
        mean_observed_echo_seconds=0.01,
        max_observed_echo_seconds=0.01,
        max_pacing_lag_seconds=0.001,
    )
    rebuild_phase_evidence(result)
    return plan, result


def rebuild_phase_evidence(report):
    ready = report["spawn"]["start"] + report["metrics"]["ready_observed_seconds"]
    rows = report["edit_train"]["rows"]
    groups = {
        "echo_before_observed_ready": [r for r in rows if r["echo"] < ready],
        "pending_across_observed_ready": [
            r for r in rows if r["sent"] < ready <= r["echo"]
        ],
        "sent_after_observed_ready": [r for r in rows if r["sent"] >= ready],
    }
    report["edit_train"]["by_observed_ready"] = {
        name: dict(
            count=len(group),
            missing_count=0,
            mean_echo_seconds=sum(r["echo_seconds"] for r in group) / len(group)
            if group
            else None,
            max_echo_seconds=max(r["echo_seconds"] for r in group) if group else None,
        )
        for name, group in groups.items()
    }


@pytest.mark.parametrize("case", ["new-edit", "resume-edit", "new-turn", "resume-turn"])
def test_frozen_workload_accepts_matching_evidence(case):
    plan, report = workload_evidence(case)
    runner.validate_workload(plan, case, "a", report)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(installation="/other"),
        lambda r: r.update(seed="/wrong-seed"),
        lambda r: r.update(synthetic=True),
        lambda r: r.update(instrumented=True),
        lambda r: r["metrics"].update(first_frame_seconds=float("nan")),
        lambda r: r["metrics"].update(exit_seconds=True),
        lambda r: r["startup_observer"].update(max_input_frame_processing_seconds=0.03),
        lambda r: r["edit_train"].update(planned_count=99),
        lambda r: r["edit_train"].update(mean_observed_echo_seconds=0.0),
        lambda r: r["edit_train"].update(anchor=102.0),
        lambda r: r["edit_train"]["rows"][0].update(token="wrong"),
        lambda r: r["edit_train"]["rows"][0].update(written=False),
        lambda r: r["edit_train"]["rows"][0].update(echo=float("inf")),
        lambda r: r["edit_train"]["rows"][0].update(planned=100.0),
    ],
)
def test_frozen_workload_rejects_mismatched_or_forged_evidence(mutation):
    plan, report = workload_evidence()
    mutation(report)
    with pytest.raises(ValueError):
        runner.validate_workload(plan, "new-edit", "a", report)


def test_slow_input_is_valid_evidence_not_an_automatic_performance_pass():
    plan, report = workload_evidence()
    train = report["edit_train"]
    for row in train["rows"]:
        row.update(echo=row["sent"] + 1.0, echo_seconds=1.0)
    train.update(mean_observed_echo_seconds=1.0, max_observed_echo_seconds=1.0)
    rebuild_phase_evidence(report)
    runner.validate_workload(plan, "new-edit", "a", report)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["synthetic_trace"].pop(),
        lambda r: r["synthetic_trace"].append(dict(phase="prompt_failed")),
        lambda r: r["synthetic_trace"].reverse(),
        lambda r: r["synthetic_trace"][1].update(digest="wrong"),
    ],
)
def test_first_turn_requires_ordered_settlement_and_exact_input(mutation):
    plan, report = workload_evidence("new-turn")
    mutation(report)
    with pytest.raises(ValueError):
        runner.validate_workload(plan, "new-turn", "a", report)


def test_first_turn_can_be_ready_before_draft_input():
    plan, report = workload_evidence("new-turn")
    report["metrics"]["ready_observed_seconds"] = 0.5
    runner.validate_workload(plan, "new-turn", "a", report)


@pytest.mark.parametrize(
    "metric,value", [("ready_observed_seconds", 0.1), ("initial_echo_seconds", 1000)]
)
def test_first_turn_rejects_inconsistent_startup_witnesses(metric, value):
    plan, report = workload_evidence("new-turn")
    report["metrics"][metric] = value
    with pytest.raises(ValueError):
        runner.validate_workload(plan, "new-turn", "a", report)


def test_phase_statistics_are_recomputed():
    plan, report = workload_evidence()
    report["edit_train"]["by_observed_ready"]["sent_after_observed_ready"]["count"] = 0
    with pytest.raises(ValueError, match="phase counts"):
        runner.validate_workload(plan, "new-edit", "a", report)


def test_cumulative_echo_cannot_precede_earlier_prefix():
    plan, report = workload_evidence()
    row = report["edit_train"]["rows"][0]
    row.update(echo=row["echo"] + 1, echo_seconds=row["echo_seconds"] + 1)
    with pytest.raises(ValueError, match="nonmonotonic"):
        runner.validate_workload(plan, "new-edit", "a", report)


def test_initial_draft_cannot_echo_after_cumulative_prefix():
    plan, report = workload_evidence()
    report["metrics"]["initial_echo_seconds"] = 0.1
    with pytest.raises(ValueError, match="initial draft"):
        runner.validate_workload(plan, "new-edit", "a", report)


def test_first_turn_rejects_extra_model_call():
    plan, report = workload_evidence("new-turn")
    report["synthetic_trace"].append(dict(phase="model_input"))
    with pytest.raises(ValueError, match="model call count"):
        runner.validate_workload(plan, "new-turn", "a", report)


def test_complete_process_is_not_enough_for_valid_observation():
    report = raw()
    assert observation_valid(report)
    report["edit_train"]["sender_schedule_valid"] = False
    assert not observation_valid(report)


@pytest.mark.parametrize("pause_after", [1, 2])
def test_safe_pause_resume_continues_prefix_without_replaying(tmp_path, pause_after):
    output = tmp_path / "campaign"
    plan = dict(cases=["new-edit"], blocks=1, pairs_per_block=1, observer="frozen-hash")
    calls = []

    def observe(root, case, side):
        calls.append((root.name, case, side))
        root.mkdir()
        result = raw()
        durable_write(root / "report.json", result)
        return result

    def validate(_):
        checkpoint = json.loads((output / "checkpoint.json").read_text())
        assert checkpoint["phase"] == "inflight", "pause must be consumed first"

    paused = collect(output, plan, observe, validate, pause_after=pause_after)
    assert paused["status"] == "paused" and len(calls) == 2
    complete = collect(output, plan, observe, validate, resume=True)
    assert complete["status"] == "complete"
    assert len(calls) == 4 and len({row[0] for row in calls}) == 4
    assert not complete["segmented_acceptance"]["eligible_for_automatic_acceptance"]


def test_invalid_sample_remains_failed_and_cannot_resume(tmp_path):
    output = tmp_path / "campaign"
    plan = dict(cases=["new-edit"], blocks=1, pairs_per_block=1)

    def observe(root, *_):
        root.mkdir()
        result = raw()
        result["edit_train"]["sender_schedule_valid"] = False
        durable_write(root / "report.json", result)
        return result

    with pytest.raises(ValueError, match="schedule invalid"):
        collect(output, plan, observe, lambda _: None)
    assert json.loads((output / "report.json").read_text())["status"] == "failed"
    with pytest.raises(ValueError, match="safe pause"):
        collect(output, plan, observe, lambda _: None, resume=True)


@pytest.mark.parametrize("changed", ["receipt", "plan"])
def test_resume_rejects_changed_evidence_or_plan_before_new_observation(
    tmp_path, changed
):
    output = tmp_path / "campaign"
    plan = dict(cases=["new-edit"], blocks=1, pairs_per_block=1, observer="original")
    calls = []

    def observe(root, *_):
        calls.append(root)
        root.mkdir()
        result = raw()
        durable_write(root / "report.json", result)
        return result

    collect(output, plan, observe, lambda _: None, pause_after=2)
    if changed == "receipt":
        durable_write(calls[0] / "report.json", {"status": "changed"})
    else:
        plan = {**plan, "observer": "changed"}
    with pytest.raises(ValueError, match="changed"):
        collect(output, plan, observe, lambda _: None, resume=True)
    assert len(calls) == 2


def test_request_after_first_side_waits_until_pair_finishes(tmp_path):
    output = tmp_path / "campaign"
    plan = dict(cases=["new-edit"], blocks=1, pairs_per_block=1)
    calls = []

    def observe(root, *_):
        calls.append(root)
        root.mkdir()
        result = raw()
        durable_write(root / "report.json", result)
        if len(calls) == 1:
            runner.checkpoint.request_pause(output)
        return result

    report = collect(output, plan, observe, lambda _: None)
    assert report["status"] == "paused" and len(calls) == 2


def test_completion_rechecks_earlier_raw_receipts(tmp_path):
    output = tmp_path / "campaign"
    plan = dict(cases=["new-edit"], blocks=1, pairs_per_block=1)
    calls = []

    def observe(root, *_):
        calls.append(root)
        root.mkdir()
        result = raw()
        durable_write(root / "report.json", result)
        if len(calls) == 2:
            durable_write(calls[0] / "report.json", {"status": "tampered"})
        return result

    with pytest.raises(ValueError, match="raw observation changed"):
        collect(output, plan, observe, lambda _: None)
    assert json.loads((output / "report.json").read_text())["status"] == "failed"


def test_expected_workload_validator_runs_before_sample_becomes_valid(tmp_path):
    plan = dict(cases=["new-edit"], blocks=1, pairs_per_block=1)
    output = tmp_path / "campaign"

    def observe(root, *_):
        root.mkdir()
        result = dict(
            status="complete",
            synthetic=True,
            metrics=dict(
                first_reply_seconds=0.1,
                prompt_settled_observed_seconds=0.2,
            ),
        )
        durable_write(root / "report.json", result)
        return result

    def validate(actual_plan, case, side, result):
        assert actual_plan == plan and case == "new-edit" and side in {"a", "b"}
        assert observation_valid(result), "generic shape alone would pass"
        raise ValueError("wrong workload for frozen edit case")

    with pytest.raises(ValueError, match="wrong workload"):
        runner.collect(output, plan, observe, lambda _: None, validate)
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "failed" and not report["samples"][0]["valid"]


def test_sample_directory_sync_failure_prevents_valid_publication(
    tmp_path, monkeypatch
):
    output = tmp_path / "campaign"
    plan = dict(cases=["new-edit"], blocks=1, pairs_per_block=1)
    original_fsync = os.fsync
    sample_identity = None

    def fail_sample_directory_sync(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == sample_identity:
            raise OSError("sample directory sync failed")
        original_fsync(fd)

    def observe(root, *_):
        nonlocal sample_identity
        root.mkdir()
        result = raw()
        durable_write(root / "report.json", result)
        info = root.stat()
        sample_identity = (info.st_dev, info.st_ino)
        monkeypatch.setattr(runner.os, "fsync", fail_sample_directory_sync)
        return result

    with pytest.raises(OSError, match="sample directory sync failed"):
        collect(output, plan, observe, lambda _: None)
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "failed"
    assert len(report["samples"]) == 1
    assert report["samples"][0]["valid"] is False
    assert json.loads((output / "checkpoint.json").read_text())["phase"] == "failed"


def test_installed_binding_preserves_case_and_resumes_without_replay(
    tmp_path, monkeypatch
):
    plan, _ = workload_evidence()
    plan.update(
        cases=["new-edit", "resume-turn"],
        blocks=1,
        pairs_per_block=1,
        resume_workspace="/isolated/workspace",
    )
    calls, validations = [], []
    original_path = sys.path[:]

    def measure(root, source, python, **kwargs):
        assert source == Path(__file__).resolve().parents[2]
        assert kwargs["installed"] is True
        case = "resume-turn" if kwargs["synthetic"] else "new-edit"
        assert kwargs["edit_train"] is (case == "new-edit")
        assert kwargs["seed"] == (Path(plan["seed"]) if case == "resume-turn" else None)
        assert kwargs["workspace"] == (
            Path(plan["resume_workspace"]) if case == "resume-turn" else None
        )
        _, result = workload_evidence(case)
        result["installation"] = str(python.parent.parent)
        calls.append((root.name, case, result["installation"]))
        root.mkdir()
        durable_write(root / "report.json", result)
        return result

    monkeypatch.setattr(runner, "_load", lambda *args: SimpleNamespace(measure=measure))
    monkeypatch.setattr(
        runner,
        "validate_installed_inputs",
        lambda actual, **kwargs: validations.append(actual),
    )
    output = tmp_path / "installed"
    paused = runner.collect_installed(output, plan, pause_after=1)
    assert paused["status"] == "paused" and len(calls) == 2
    assert len(validations) == 5
    complete = runner.collect_installed(output, plan, resume=True)
    assert complete["status"] == "complete" and len(calls) == 8
    assert len({call[0] for call in calls}) == 8
    assert len(validations) == 19
    assert sys.path == original_path


def test_installed_validation_failure_never_spawns_probe(tmp_path, monkeypatch):
    plan = dict(cases=["new-edit"], blocks=1, pairs_per_block=1)
    original_path = sys.path[:]

    def forbidden(*args, **kwargs):
        pytest.fail("must not spawn a Product with changed inputs")

    def validate(_):
        raise ValueError("installation changed")

    monkeypatch.setattr(
        runner, "_load", lambda *args: SimpleNamespace(measure=forbidden)
    )
    monkeypatch.setattr(runner, "validate_installed_inputs", validate)
    with pytest.raises(ValueError, match="installation changed"):
        runner.collect_installed(tmp_path / "failed", plan)
    assert sys.path == original_path


@pytest.mark.parametrize(
    "changed",
    [
        None,
        "helpers",
        "seed",
        "source",
        "installation",
        "dependencies",
        "observer",
        "bytecode",
        "workspace",
    ],
)
def test_installed_input_validation_seals_provenance(tmp_path, monkeypatch, changed):
    seed = tmp_path / "seed.jsonl"
    seed.write_text("synthetic history")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for side in ("a", "b"):
        (tmp_path / side).mkdir()
        (tmp_path / f"{side}.whl").write_bytes(b"verifier fixture")
    source = dict(
        commit="frozen",
        wheel_sha256="wheel-hash",
        lock_sha256="lock",
        project_sha256="project",
    )
    receipt = dict(python="3.11", dependencies=[["dependency", "1"]], entries={})
    plan = dict(
        repo=str(Path(__file__).resolve().parents[2]),
        bytecode_policy="warm-installation",
        observer_identity={"commit": "frozen-observer"},
        resume_workspace=str(workspace),
        resume_workspace_manifest=runner.checkpoint.tree_manifest(workspace),
        bytecode_manifests={"a": {}, "b": {}},
        helpers={"observer": "hash"},
        seed=str(seed),
        seed_sha256=runner.checkpoint.file_hash(seed),
        sources={side: dict(source) for side in ("a", "b")},
        revisions={side: "frozen" for side in ("a", "b")},
        cases=["new-edit", "resume-turn"],
        blocks=2,
        pairs_per_block=3,
        max_input_observer_seconds=0.025,
        installations={side: str(tmp_path / side) for side in ("a", "b")},
        wheels={side: str(tmp_path / f"{side}.whl") for side in ("a", "b")},
        installation_receipts={side: dict(receipt) for side in ("a", "b")},
        verification_root=str(tmp_path),
    )
    if changed == "seed":
        seed.write_text("changed history")
    if changed == "bytecode":
        (tmp_path / "a/changed.pyc").write_bytes(b"changed cache")
    if changed == "workspace":
        (workspace / "settings.json").write_text("{}")
    if changed == "dependencies":
        plan["installation_receipts"]["b"] = {
            **receipt,
            "dependencies": [["dependency", "2"]],
        }

    def verify(prefix, wheel, scratch, expected):
        assert scratch.is_dir() and expected == "wheel-hash"
        return (
            {}
            if changed == "installation"
            else plan["installation_receipts"][prefix.name]
        )

    provenance = SimpleNamespace(
        require_clean_product=lambda repo: None,
        helper_manifest=lambda repo: {} if changed == "helpers" else plan["helpers"],
        verify_wheel_at_commit=lambda *args: {} if changed == "source" else source,
    )
    measure = SimpleNamespace(
        provenance_module=lambda: provenance, verify_pinned_install=verify
    )
    monkeypatch.setattr(runner, "_load", lambda *args: measure)
    monkeypatch.setattr(
        runner,
        "observer_identity",
        lambda *args: {} if changed == "observer" else plan["observer_identity"],
    )
    if changed:
        with pytest.raises(ValueError, match="changed|differs"):
            runner.validate_installed_inputs(plan)
    else:
        runner.validate_installed_inputs(plan)
        frozen = runner.freeze_installed_plan(plan)
        assert frozen == plan and frozen is not plan
        assert frozen["sources"] is not plan["sources"]
        alias = tmp_path / "alias-a"
        alias.symlink_to(tmp_path / "a", target_is_directory=True)
        for shared in (tmp_path / "a", alias):
            with pytest.raises(ValueError, match="independent directories"):
                runner.freeze_installed_plan(
                    {
                        **plan,
                        "installations": {"a": str(tmp_path / "a"), "b": str(shared)},
                    }
                )
        for budget in (None, True, 0, float("nan"), float("inf")):
            with pytest.raises(ValueError, match="observer budget"):
                runner.freeze_installed_plan(
                    {**plan, "max_input_observer_seconds": budget}
                )
    assert not list(tmp_path.glob("verify-interactive-*"))
    assert not list(tmp_path.glob("freeze-interactive-*"))


def test_freeze_cli_refuses_existing_plan_without_running_verification(
    tmp_path, monkeypatch
):
    source, destination = tmp_path / "config.json", tmp_path / "frozen.json"
    source.write_text("{}")
    destination.write_text("existing evidence")
    monkeypatch.setattr(
        sys,
        "argv",
        ["campaign", "--plan", str(source), "--output", str(destination), "--freeze"],
    )
    monkeypatch.setattr(
        runner,
        "freeze_installed_plan",
        lambda _: pytest.fail("must refuse before verification"),
    )
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert destination.read_text() == "existing evidence"


def test_freeze_race_cannot_overwrite_concurrent_publication(tmp_path, monkeypatch):
    source, destination = tmp_path / "config.json", tmp_path / "frozen.json"
    source.write_text("{}")

    def freeze(_):
        destination.write_text("published by another collector")
        return {"new": "plan"}

    monkeypatch.setattr(runner, "freeze_installed_plan", freeze)
    monkeypatch.setattr(
        sys,
        "argv",
        ["campaign", "--plan", str(source), "--output", str(destination), "--freeze"],
    )
    with pytest.raises(FileExistsError):
        runner.main()
    assert destination.read_text() == "published by another collector"
    assert not list(tmp_path.glob(".interactive-plan-*"))


def test_frozen_plan_publication_is_complete_and_private(tmp_path):
    destination = tmp_path / "frozen.json"
    runner.publish_frozen_plan(destination, {"plan": "frozen"})
    assert json.loads(destination.read_text()) == {"plan": "frozen"}
    assert destination.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".interactive-plan-*"))
