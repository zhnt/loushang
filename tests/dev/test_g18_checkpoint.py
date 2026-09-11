from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

if sys.platform != "linux":
    pytest.skip("Linux checkpoint contract", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts/dev" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checkpoint = load("_g18_checkpoint")
native = load("measure_g18_native")

def report():
    return dict(
        schema_version=2,
        status="running",
        cases=["one", "two"],
        blocks=2,
        pairs_per_block=1,
        samples=[],
        comparison={"verdict": "not-evaluated"},
    )


def append(result):
    index = len(result["samples"])
    block, pair, case, side = checkpoint.schedule(result["cases"], 2, 1)[index]
    result["samples"].append(
        dict(
            block=block,
            pair=pair,
            case=case,
            side=side,
            iteration=index + 1,
            warmup=pair == -1,
            status="complete",
            valid=True,
        )
    )


def collect(output, *, resume=False, pause_after=None, plan=None):
    with checkpoint.Campaign(
        output, resume=resume, pause_after=pause_after
    ) as campaign:
        result = campaign.report if resume else report()
        campaign.begin(result, {"fixed": "plan"} if plan is None else plan)
        try:
            while len(result["samples"]) < 16:
                append(result)
                if campaign.wants_pause(result):
                    campaign.pause(result, {})
            result.update(status="complete-record-only", comparison={"verdict": "pass"})
            campaign.finish(result)
        except checkpoint.Paused:
            pass
    return checkpoint.read_json(output / "report.json")


@pytest.mark.parametrize("boundary", [1, 2, 4, 8, 15])
def test_resume_keeps_exact_prefix_order_warmups_and_never_repeats(tmp_path, boundary):
    output = tmp_path / "run"
    first = collect(output, pause_after=boundary)
    assert first["status"] == "paused" and len(first["samples"]) == boundary
    completed = collect(output, resume=True)
    assert completed["samples"][:boundary] == first["samples"]
    assert len(completed["samples"]) == 16
    assert sum(sample["warmup"] for sample in completed["samples"]) == 8
    assert completed["status"] == "complete-record-only"
    assert len(completed["segments"]) == 2
    assert (
        completed["segmented_acceptance"]["eligible_for_automatic_acceptance"] is False
    )
    with pytest.raises(ValueError, match="safe pause"):
        collect(output, resume=True)


def test_repeated_pauses_use_cumulative_count(tmp_path):
    output = tmp_path / "run"
    collect(output, pause_after=3)
    second = collect(output, resume=True, pause_after=7)
    assert len(second["samples"]) == 7
    assert [segment["first_index"] for segment in second["segments"]] == [0, 3]
    final = collect(output, resume=True)
    assert len(final["samples"]) == 16
    assert final["segmented_acceptance"]["eligible_for_automatic_acceptance"] is False


@pytest.mark.parametrize("target", [1, 3])
def test_resume_rejects_already_reached_pause_before_consuming_token(tmp_path, target):
    output = tmp_path / "run"
    first = collect(output, pause_after=3)
    with pytest.raises(ValueError, match="must exceed"):
        collect(output, resume=True, pause_after=target)
    assert checkpoint.read_json(output / "checkpoint.json")["phase"] == "paused"
    assert checkpoint.read_json(output / "report.json") == first
    assert len(collect(output, resume=True)["samples"]) == 16


def test_last_observation_does_not_bypass_finalization(tmp_path):
    result = collect(tmp_path / "run", pause_after=16)
    assert result["status"] == "complete-record-only"
    assert result["segmented_acceptance"]["eligible_for_automatic_acceptance"]


def test_pause_request_is_bound_and_is_not_an_interrupt(tmp_path):
    output = tmp_path / "run"
    with checkpoint.Campaign(output) as campaign:
        result = report()
        campaign.begin(result, {"fixed": "plan"})
        checkpoint.request_pause(output)
        checkpoint.request_pause(output)
        assert checkpoint.read_json(output / "checkpoint.json")["phase"] == "inflight"
        append(result)
        assert campaign.wants_pause(result)
        with suppress(checkpoint.Paused):
            campaign.pause(result, {})
    assert collect(output, resume=True)["status"] == "complete-record-only"


@pytest.mark.parametrize(
    "fault", ["report", "cursor", "machine", "lock", "version", "next", "phase"]
)
def test_resume_rejects_mismatch_and_ambiguous_publication(tmp_path, fault):
    output = tmp_path / "run"
    collect(output, pause_after=2)
    path = output / "checkpoint.json"
    value = checkpoint.read_json(path)
    if fault == "report":
        (output / "report.json").write_text("{}")
    elif fault == "next":
        (output / "checkpoint.json.checkpoint-next").write_text("partial")
    elif fault == "lock":
        (output / "checkpoint.lock").rename(output / "old-lock")
    else:
        if fault == "cursor":
            value["next_index"] += 1
        elif fault == "machine":
            value["machine"]["boot_id"] = "other-boot"
        elif fault == "version":
            value["version"] = 99
        else:
            value["phase"] = "inflight"
        checkpoint.durable_write(path, value)
    with pytest.raises(ValueError):
        collect(output, resume=True)


def test_consumed_checkpoint_cannot_replay_after_resume_failure(tmp_path):
    output = tmp_path / "run"
    collect(output, pause_after=2)
    with pytest.raises(RuntimeError):
        with checkpoint.Campaign(output, resume=True) as campaign:
            campaign.begin(campaign.report, {"fixed": "plan"})
            assert (
                checkpoint.read_json(output / "checkpoint.json")["phase"] == "inflight"
            )
            raise RuntimeError("probe or owner failed")
    assert checkpoint.read_json(output / "checkpoint.json")["phase"] == "failed"
    with pytest.raises(ValueError, match="safe pause"):
        collect(output, resume=True)


def test_failure_publication_preserves_original_error_and_releases_lock(
    tmp_path, monkeypatch
):
    output = tmp_path / "run"
    original = RuntimeError("original owner failure")
    with pytest.raises(RuntimeError) as caught:
        with checkpoint.Campaign(output) as campaign:
            monkeypatch.setattr(
                campaign, "_write", lambda: (_ for _ in ()).throw(OSError("disk full"))
            )
            raise original
    assert caught.value is original
    assert "disk full" in original.__notes__[0]
    assert (
        campaign.fd is not None
    )  # The fd number is retained diagnostically but closed.
    with pytest.raises(OSError):
        os.fstat(campaign.fd)
    assert checkpoint.read_json(output / "checkpoint.json")["phase"] == "inflight"


def test_pause_request_published_during_resume_is_not_lost(tmp_path, monkeypatch):
    output = tmp_path / "run"
    collect(output, pause_after=2)
    with checkpoint.Campaign(output, resume=True) as campaign:
        original = campaign._write

        def publish_then_request():
            original()
            checkpoint.request_pause(output)

        monkeypatch.setattr(campaign, "_write", publish_then_request)
        campaign.begin(campaign.report, {"fixed": "plan"})
        assert campaign.wants_pause(campaign.report)
        assert (output / "pause-request-1.json").exists()


def test_wrong_plan_cannot_launch_or_consume_compatible_checkpoint(tmp_path):
    output = tmp_path / "run"
    collect(output, pause_after=2)
    with pytest.raises(ValueError, match="plan"):
        collect(output, resume=True, plan={"changed": True})
    assert checkpoint.read_json(output / "checkpoint.json")["phase"] == "paused"
    assert collect(output, resume=True)["status"] == "complete-record-only"


def test_lock_is_cross_process_and_not_inherited(tmp_path):
    output = tmp_path / "run"
    with checkpoint.Campaign(output) as campaign:
        assert not os.get_inheritable(campaign.fd)
        code = "import fcntl,sys; f=open(sys.argv[1],'r+'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
        result = subprocess.run(
            [sys.executable, "-I", "-c", code, str(output / "checkpoint.lock")],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode != 0 and b"BlockingIOError" in result.stderr


@pytest.mark.parametrize("change", ["tamper", "delete"])
def test_raw_receipt_drift_is_rejected(tmp_path, change):
    output = tmp_path / "run"
    with checkpoint.Campaign(output) as campaign:
        result = report()
        campaign.begin(result, {"fixed": "plan"})
        append(result)
        raw = output / "raw.json"
        raw.write_text('{"valid":true}')
        result["samples"][0]["receipt"] = str(raw)
        with suppress(checkpoint.Paused):
            campaign.pause(result, {})
    if change == "tamper":
        raw.write_text('{"valid":false}')
    else:
        raw.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        collect(output, resume=True)


@pytest.mark.parametrize("fault", ["invalid", "order", "iteration", "warmup"])
def test_checkpoint_requires_complete_exact_prefix(fault):
    value = report()
    append(value)
    sample = value["samples"][0]
    sample[
        {
            "invalid": "valid",
            "order": "side",
            "iteration": "iteration",
            "warmup": "warmup",
        }[fault]
    ] = False
    with pytest.raises(ValueError, match="prefix"):
        checkpoint.validate_prefix(value)


def resources(tmp_path, active="a"):
    slot = native.installation_slot.InstallationSlot(tmp_path)
    for side in ("a", "b"):

        def build(prefix):
            prefix.mkdir()
            (prefix / "main.py").write_text("pass\n")

        slot.provision(side, build)
    slot.run(active, lambda _: None)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    caches = native.bytecode_policy.BytecodePolicy(slot, artifacts)
    recovery = native.recovery_state.RecoveryState(tmp_path, artifacts)
    recovery.prepare(lambda subject, _: (subject / "input").write_text("seed"))
    recovery.sample(lambda subject, _: (subject / "input").write_text("after-product"))
    return slot, caches, recovery


@pytest.mark.parametrize("active", ["a", "b"])
def test_native_reopens_same_slot_cache_and_post_product_subject(tmp_path, active):
    slot, caches, recovery = resources(tmp_path, active)
    first_slot, first_cache, first_recovery = (
        slot.checkpoint(),
        caches.checkpoint(),
        recovery.checkpoint(),
    )
    reopened = native.installation_slot.InstallationSlot.reopen(first_slot)
    restored_cache = native.bytecode_policy.BytecodePolicy.reopen(reopened, first_cache)
    restored_recovery = native.recovery_state.RecoveryState.reopen(first_recovery)
    assert reopened.checkpoint() == first_slot
    assert restored_cache.checkpoint() == first_cache
    assert restored_recovery.receipt["restores"] == 1
    assert (restored_recovery.subject / "input").read_text() == "after-product"
    restored_recovery.sample(
        lambda subject, _: (subject / "input").read_text() == "seed"
    )
    assert restored_recovery.receipt["restores"] == 2


@pytest.mark.parametrize(
    "fault", ["root", "active", "seed", "subject", "external", "failed"]
)
def test_native_reopen_rejects_changed_or_failed_resources(tmp_path, fault):
    slot, caches, recovery = resources(tmp_path)
    s, c, r = slot.checkpoint(), caches.checkpoint(), recovery.checkpoint()
    if fault in ("root", "active"):
        path = slot.root if fault == "root" else slot.prefix
        path.rename(path.with_name(path.name + "-old"))
        path.mkdir()
    elif fault == "seed":
        (recovery.seed / "input").write_text("changed")
    elif fault == "subject":
        (recovery.subject / "input").write_text("changed")
    elif fault == "external":
        (caches.external("a") / "unexpected.pyc").write_bytes(b"changed")
    else:
        s["receipt"]["failed"] = True
    with pytest.raises((ValueError, OSError)):
        reopened = native.installation_slot.InstallationSlot.reopen(s)
        native.bytecode_policy.BytecodePolicy.reopen(reopened, c)
        native.recovery_state.RecoveryState.reopen(r)


def test_cli_rejects_checkpoint_for_other_modes_before_product(tmp_path):
    with pytest.raises(SystemExit):
        native.main(
            [
                "--install-a",
                str(tmp_path / "a"),
                "--install-b",
                str(tmp_path / "b"),
                "--observer-install",
                str(tmp_path / "observer"),
                "--output",
                str(tmp_path / "out"),
                "--checkpoint",
            ]
        )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("cache_mode", ["warm", "absent"])
@pytest.mark.parametrize("boundary", [1, 5, 12, 35])
def test_real_native_coordinator_resumes_without_replaying_setup_or_observations(
    tmp_path, monkeypatch, cache_mode, boundary
):
    # Reuse the strict existing fake-owner fixture: it asserts prepin/cache/owner
    # order, bytecode conditions, immutable seeds and every reset/observation.
    from tests.dev import test_measure_g18_native as contract

    runner = contract.runner
    original = runner.collect_fixed_native

    def segmented(*args, **kwargs):
        output, result = args[-3], args[-2]
        observer = tmp_path / "observer"
        observer.mkdir(exist_ok=True)
        result.update(
            schema_version=2,
            status="running",
            cases=list(args[2]),
            blocks=args[3],
            pairs_per_block=args[4],
            installations={},
            observer_installation={"prefix": str(observer)},
            comparison={"verdict": "not-evaluated"},
        )
        (Path(result["scratch"])).mkdir(exist_ok=True)
        checkpoint_output = output / "checkpoint-control"
        with checkpoint.Campaign(checkpoint_output, pause_after=boundary) as campaign:
            (checkpoint_output / "observer-bytecode").mkdir()
            campaign.begin(result, {"mode": cache_mode})
            with pytest.raises(checkpoint.Paused):
                original(*args, **kwargs, campaign=campaign)
        prefix = checkpoint.read_json(checkpoint_output / "report.json")["samples"]
        assert len(prefix) == boundary
        sealed = checkpoint.read_json(checkpoint_output / "checkpoint.json")
        assert all(sample["receipt"] in sealed["evidence"] for sample in prefix)
        assert all(
            "manifest.json" in sealed["resources"]["trees"][state["paths"]["archive"]]
            for state in sealed["resources"]["recovery"].values()
        )
        # The existing fixture replaces the constructor only to select tmp_path.
        monkeypatch.setattr(
            runner.recovery_state.RecoveryState,
            "reopen",
            native.recovery_state.RecoveryState.reopen,
            raising=False,
        )
        with checkpoint.Campaign(checkpoint_output, resume=True) as campaign:
            result.clear()
            result.update(campaign.report)
            campaign.begin(result, {"mode": cache_mode})
            campaign.native = runner.reopen_native(campaign, result)
            original(campaign.native[0], *args[1:], **kwargs, campaign=campaign)
            assert result["samples"][:boundary] == prefix
            assert len(result["seed_setup"]) == 2
            result["status"] = "complete-record-only"
            campaign.finish(result)

    monkeypatch.setattr(runner, "collect_fixed_native", segmented)
    contract.test_fixed_native_collector_orders_cache_and_owner_and_never_counts_failed_warmup(
        tmp_path, monkeypatch, cache_mode, None
    )


@pytest.mark.parametrize("cache_mode", ["warm", "absent"])
def test_native_cli_pause_resume_finalizes_once_after_original_41_metric_comparison(
    tmp_path, monkeypatch, cache_mode
):
    from tests.dev.test_g18_comparison import native_samples

    runner = load("measure_g18_native")
    output = tmp_path / "output"
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("locked-test-input")
    source = dict(commit="fixed", lock_sha256="lock", wheel_sha256="wheel")
    monkeypatch.setattr(
        runner.inert,
        "source_pair",
        lambda *_: (
            {side: tmp_path / "wheel" for side in ("a", "b")},
            {side: dict(source) for side in ("a", "b")},
        ),
    )
    monkeypatch.setattr(
        runner.inert,
        "provenance_module",
        lambda: SimpleNamespace(helper_manifest=lambda _: {}),
    )
    monkeypatch.setattr(
        runner.inert,
        "verify_pinned_install",
        lambda prefix, *_: dict(
            prefix=str(prefix),
            python="fixed",
            dependencies=[],
            entries={},
        ),
    )
    monkeypatch.setattr(runner, "provision_slot", lambda *_: object())
    calls = []
    ordinary = runner.inert.write_report

    def write_report(path, result):
        assert result["status"] != "complete-record-only", (
            "no ordinary rewrite after durable finish"
        )
        ordinary(path, result)

    monkeypatch.setattr(runner.inert, "write_report", write_report)

    def reopen(campaign, _):
        assert checkpoint.read_json(output / "checkpoint.json")["phase"] == "inflight"
        calls.append("reopen")
        return object(), None, {}

    monkeypatch.setattr(runner, "reopen_native", reopen)
    rows = {
        (s["block"], s["pair"], s["case"], s["side"]): s
        for s in native_samples(cache_mode=cache_mode)
    }
    ordered = [
        dict(rows[key], iteration=i)
        for i, key in enumerate(checkpoint.schedule(list(runner.CASES), 2, 10), 1)
    ]

    def collect_stub(*args, campaign, **kwargs):
        result = args[-2]
        for sample in ordered[len(result["samples"]) :]:
            result["samples"].append(sample)
            if campaign.wants_pause(result):
                campaign.pause(result, {})

    monkeypatch.setattr(runner, "collect_fixed_native", collect_stub)
    args = [
        "--install-a",
        str(tmp_path / "a"),
        "--install-b",
        str(tmp_path / "b"),
        "--observer-install",
        str(tmp_path / "observer"),
        "--wheel",
        str(tmp_path / "wheel"),
        "--output",
        str(output),
        "--scratch-parent",
        str(tmp_path),
        "--fixed-slot",
        "--cache-mode",
        cache_mode,
        "--requirements",
        str(requirements),
    ]
    assert runner.main([*args, "--checkpoint", "--pause-after", "1"]) == 0
    paused = checkpoint.read_json(output / "report.json")
    assert paused["status"] == "paused" and len(paused["samples"]) == 1
    assert runner.main([*args, "--resume"]) == 0
    final = checkpoint.read_json(output / "report.json")
    assert final["samples"][:1] == paused["samples"]
    assert len(final["samples"]) == 308 and calls == ["reopen"]
    assert sum(len(metrics) for metrics in final["comparison"]["cases"].values()) == 41
    assert final["comparison"]["verdict"] == "pass"
    assert final["segmented_acceptance"]["eligible_for_automatic_acceptance"] is False
    assert checkpoint.read_json(output / "checkpoint.json")["phase"] == "complete"
