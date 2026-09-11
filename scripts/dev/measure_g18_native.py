"""Record Linux native startup milestones, outside the Product runtime.

This A/A or A/B collector is deliberately record-only. Warmups and failures remain in
the report; wall timing comes from the private native observer, not test elapsed.
Exit zero means collection completed, not that the comparison verdict passed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import sys
import tempfile
import time
from functools import partial
from pathlib import Path


def support(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inert = support("measure_g18_startup")
owner = support("_evidence_process")
recovery_state = support("_g18_recovery")
installation_slot = support("_g18_slot")
bytecode_policy = support("_g18_bytecode")
PROBE = inert.ROOT / "tests/coding/_g18_native_probe.py"
CASES = (
    "embedded",
    "foreground",
    "local-mux",
    "g14-stdio",
    "recovery-cwd",
    "recovery-global",
    "product-first-use",
)


OBSERVER_FIELDS = {
    "schema_version",
    "case",
    "status",
    "valid",
    "milestones",
    "spawns",
    "observer_origin",
    "observer_prefix",
    "measured_prefix",
    "seed",
    "sample_id",
    "seed_setup",
}


def validate_isolation(value, prefix, root):
    isolation = value["isolation"]
    if (
        type(isolation) is not dict
        or set(isolation)
        != {"ambient_before", "ambient_after", "environment_unchanged", "controls"}
        or isolation["environment_unchanged"] is not True
        or isolation["ambient_before"] != isolation["ambient_after"]
        or isolation["ambient_after"] != inert.fingerprint_tree(root / "ambient-home")
        or value["seed"] != "empty"
        or value["seed_setup"] != []
        or value["milestones"] != {}
    ):
        raise ValueError("home isolation ambient evidence mismatch")
    controls = isolation["controls"]
    expected = (
        ("embedded", False, "poison-invalid-json"),
        ("embedded", True, "ready-exited"),
        ("foreground", False, "session-unavailable"),
        ("foreground", True, "member-opened"),
    )
    if type(controls) is not list or len(controls) != 4:
        raise ValueError("four home isolation controls required")
    starts, spawns = [], []
    for control, (case, isolated, witness) in zip(controls, expected, strict=True):
        if (
            type(control) is not dict
            or set(control)
            != {
                "case",
                "isolated",
                "status",
                "measured_prefix",
                "spawns",
                "milestones",
                "exit_code",
                "witness",
            }
            or control["case"] != case
            or control["isolated"] is not isolated
            or control["status"] != "settled"
            or control["witness"] != witness
            or control["measured_prefix"] != str(prefix)
            or type(control["exit_code"]) is not int
            or (
                control["exit_code"] <= 0
                if witness == "poison-invalid-json"
                else control["exit_code"] != 0
            )
            or type(control["spawns"]) is not list
            or len(control["spawns"]) != 1
        ):
            raise ValueError(
                "home isolation control did not settle with required witness"
            )
        required = (
            {"rejected_exit_seconds"}
            if witness == "poison-invalid-json"
            else {"ready_frame_seconds", "settlement_seconds"}
        )
        if case == "foreground":
            required.add("control_witness_seconds")
        if (
            type(control["milestones"]) is not dict
            or set(control["milestones"]) != required
            or any(
                type(duration) not in (int, float)
                or not math.isfinite(duration)
                or duration <= 0
                for duration in control["milestones"].values()
            )
        ):
            raise ValueError("home isolation control milestones missing")
        spawn = control["spawns"][0]
        executable = "loushang" if case == "embedded" else "loushang-hosted-tui"
        workspace = (
            root
            / "workspace"
            / f"{case}-{'private' if isolated else 'leaked'}"
            / "workspace"
        )
        if (
            type(spawn) is not dict
            or set(spawn) != {"pid", "start", "argv", "cwd"}
            or type(spawn["pid"]) is not int
            or spawn["pid"] <= 0
            or type(spawn["start"]) not in (int, float)
            or not math.isfinite(spawn["start"])
            or spawn["start"] <= 0
            or spawn["cwd"] != str(workspace)
            or type(spawn["argv"]) is not list
            or not spawn["argv"]
            or spawn["argv"][0] != str(prefix / "bin" / executable)
        ):
            raise ValueError("home isolation spawn identity mismatch")
        starts.append(spawn["start"])
        spawns.append(spawn)
    if value["spawns"] != spawns or any(
        left >= right for left, right in zip(starts, starts[1:])
    ):
        raise ValueError("home isolation launch order mismatch")


def validate_seed(seed, case):
    scope = "cwd" if case == "recovery-cwd" else "user_home"
    if (
        type(seed) is not dict
        or set(seed) != {"scope", "history", "session_count", "shape", "files"}
        or seed["scope"] != scope
        or type(seed["session_count"]) is not int
        or seed["session_count"] != 1
        or seed["history"] != f"G17 canonical history recovered in {scope}"
        or type(seed["shape"]) is not dict
        or not seed["shape"]
        or type(seed["files"]) is not dict
        or not seed["files"]
        or any(
            type(name) is not str
            or not Path(name).parts
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or type(digest) is not str
            or re.fullmatch("[0-9a-f]{64}", digest) is None
            for name, digest in seed["files"].items()
        )
    ):
        raise ValueError("recovery seed evidence missing")


def validate_setup_order(setup):
    if type(setup) is not list or len(setup) != 2:
        raise ValueError("recovery seed evidence missing")
    settled = 0
    for launch in setup:
        if (
            type(launch) is not dict
            or set(launch) != {"status", "spawns", "settled_at"}
            or launch["status"] != "settled"
            or type(launch["settled_at"]) not in (int, float)
            or not math.isfinite(launch["settled_at"])
            or type(launch["spawns"]) is not list
            or len(launch["spawns"]) != 1
            or type(launch["spawns"][0]) is not dict
            or type(launch["spawns"][0].get("start")) not in (int, float)
            or not math.isfinite(launch["spawns"][0]["start"])
        ):
            raise ValueError("recovery setup did not settle")
        if not settled < launch["spawns"][0]["start"] < launch["settled_at"]:
            raise ValueError("recovery setup order mismatch")
        settled = launch["settled_at"]
    return settled


def validate_prepared_snapshot(seed, snapshot):
    files = {
        name.removeprefix("workspace/"): value["sha256"]
        for name, value in snapshot["manifest"].items()
        if name.startswith("workspace/") and value["kind"] == "file"
    }
    if seed["files"] != files:
        raise ValueError("recovery seed differs from settled opaque snapshot")


def validate_observation(
    value, case, prefix, root, observer_prefix, *, observer_python=None
):
    fields = (
        OBSERVER_FIELDS | {"isolation"} if case == "home-isolation" else OBSERVER_FIELDS
    )
    if case == "g14-stdio":
        fields = fields | {"stdio_observer"}
    if (
        type(value) is not dict
        or set(value) != fields
        or value.get("schema_version") != 2
        or value.get("case") != case
        or value.get("status") != "observed"
        or value.get("valid") is not False
    ):
        raise ValueError("invalid native observer receipt")
    if value["sample_id"] != str(root.resolve()):
        raise ValueError("native receipt belongs to another sample")
    if (
        value["observer_prefix"] != str(observer_prefix)
        or not Path(value["observer_origin"])
        .resolve()
        .is_relative_to(observer_prefix.resolve())
        or value["measured_prefix"] != str(prefix)
    ):
        raise ValueError("native observer/measurement installation mismatch")
    if case == "g14-stdio" and (
        not isinstance(observer_python, str)
        or value["stdio_observer"]
        != {
            "backend": "cpython311-safe-child-watcher-v1",
            "watcher": "asyncio.unix_events.SafeChildWatcher",
            "python": observer_python,
        }
    ):
        raise ValueError("native stdio observer backend mismatch")
    if case == "home-isolation":
        validate_isolation(value, prefix, root)
        return
    required = set() if case == "product-first-use" else {"first_command_seconds"}
    if case == "product-first-use":
        required.update(
            (
                "server_ready_seconds",
                "review_attach_frame_seconds",
                "dev_attach_frame_seconds",
                "reattach_frame_seconds",
                "first_model_seconds",
                "spawn_through_first_model_seconds",
                "first_approval_seconds",
                "first_tool_seconds",
                "interrupt_seconds",
                "review_detach_settlement_seconds",
                "dev_detach_settlement_seconds",
                "reattach_detach_settlement_seconds",
                "settlement_seconds",
            )
        )
    elif case == "local-mux":
        required.update(
            (
                "server_ready_seconds",
                "attach_frame_seconds",
                "spawn_through_first_command_seconds",
                "detach_settlement_seconds",
                "stop_settlement_seconds",
            )
        )
    else:
        required.update(
            (
                "protocol_ready_seconds"
                if case == "g14-stdio"
                else "ready_frame_seconds",
                "settlement_seconds",
            )
        )
    if case.startswith("recovery-"):
        required.add("history_visible_seconds")
    milestones = value.get("milestones", {})
    if not required <= milestones.keys() or any(
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or duration <= 0
        for duration in milestones.values()
    ):
        raise ValueError("incomplete or invalid native milestones")
    executables = {
        "embedded": ["loushang"],
        "foreground": ["loushang-hosted-tui"],
        "g14-stdio": ["loushang-hosted"],
        "local-mux": ["loushang-mux", "loushang-mux"],
        "recovery-cwd": ["loushang-hosted-tui"],
        "recovery-global": ["loushang-hosted-tui"],
        "product-first-use": ["python", "loushang-mux", "loushang-mux", "loushang-mux"],
    }[case]
    spawns = value["spawns"]
    if type(spawns) is not list or len(spawns) != len(executables):
        raise ValueError("native spawn inventory mismatch")
    for spawn, executable in zip(spawns, executables, strict=True):
        if (
            set(spawn) != {"pid", "start", "argv", "cwd"}
            or type(spawn["pid"]) is not int
            or spawn["pid"] <= 0
            or type(spawn["start"]) not in (float, int)
            or not math.isfinite(spawn["start"])
            or spawn["start"] <= 0
            or spawn["cwd"] != str((root / "workspace").resolve())
            or type(spawn["argv"]) is not list
            or not spawn["argv"]
            or any(type(arg) is not str for arg in spawn["argv"])
            or spawn["argv"][0] != str(prefix / "bin" / executable)
        ):
            raise ValueError("native spawn identity mismatch")
        if executable == "python" and spawn["argv"][1:2] != [
            str(PROBE.with_name("_local_product_child.py"))
        ]:
            raise ValueError("unexpected Product synthetic transport fixture")
    if case.startswith("recovery-"):
        seed, setup = value["seed"], value["seed_setup"]
        validate_seed(seed, case)
        settled = validate_setup_order(setup)
        for launch in setup:
            validate_observation(
                {
                    **value,
                    "case": "foreground",
                    "seed": "empty",
                    "seed_setup": [],
                    "spawns": launch["spawns"],
                },
                "foreground",
                prefix,
                root,
                observer_prefix,
            )
        if not settled < spawns[0]["start"]:
            raise ValueError("recovery measurement overlaps setup")
    elif value["seed"] != "empty" or value["seed_setup"] != []:
        raise ValueError("fresh native sample contains recovery state")


def run_sample(
    prefix,
    case,
    root,
    bytecode,
    report,
    path,
    identity,
    *,
    observer_prefix,
    attempt=None,
    before_launch=None,
    defer_validation=False,
):
    parent_environment = dict(os.environ)
    workspace = root / "workspace"
    workspace.mkdir(parents=True, mode=0o700)
    environment = inert.private_environment(root / "environment", prefix, bytecode)
    environment.update(COLUMNS="100", LINES="30")
    ambient_before = None
    if case == "home-isolation":
        ambient = root / "ambient-home"
        models = ambient / ".loushang/models"
        models.mkdir(parents=True, mode=0o700)
        (models / "g18-poison.json").write_bytes(b"{")
        (ambient / "sentinel").write_bytes(
            b"G18 synthetic ambient HOME; leave unchanged\n"
        )
        ambient_before = inert.fingerprint_tree(ambient)
        environment.update(HOME=str(ambient), USERPROFILE=str(ambient))
    receipt = root / "native.json"
    if attempt is None:
        attempt = dict(identity)
        report["samples"].append(attempt)
    attempt.update(
        case=case,
        valid=False,
        status="running",
        cwd=str(workspace),
        load_before=os.getloadavg(),
    )
    inert.write_report(path, report)
    try:
        if before_launch is not None:
            before_launch(attempt)
        owner.run_python(
            [
                str(observer_prefix / "bin/python"),
                "-I",
                str(PROBE),
                str(workspace),
                case,
                str(receipt),
                str(prefix),
                str(path.parent / "observer-bytecode"),
            ],
            cwd=root,
            environment=environment,
            # Includes trusted fixture setup; Product deadlines inside stay at
            # their existing G14/G16/G17 values. Recovery has two untimed seeds.
            timeout=360
            if case == "home-isolation"
            else 240
            if case.startswith("recovery-") or case == "product-first-use"
            else 150,
        )
        observed = json.loads(receipt.read_text())
        validate_observation(
            observed,
            case,
            prefix,
            root,
            observer_prefix,
            observer_python=report.get("observer_installation", {}).get("python"),
        )
        if dict(os.environ) != parent_environment:
            raise ValueError("collector parent environment changed")
        if (
            case == "home-isolation"
            and observed["isolation"]["ambient_before"] != ambient_before
        ):
            raise ValueError("observer ambient input differs from collector")
        if case.startswith("recovery-"):
            shapes = report.setdefault("seed_shapes", {})
            if (
                shapes.setdefault(case, observed["seed"]["shape"])
                != observed["seed"]["shape"]
            ):
                raise ValueError("paired recovery workload differs")
        for key in OBSERVER_FIELDS - {
            "case",
            "schema_version",
            "status",
            "valid",
            "sample_id",
        }:
            attempt[key] = observed[key]
        if case == "home-isolation":
            attempt["isolation"] = observed["isolation"]
        elif case == "g14-stdio":
            attempt["stdio_observer"] = observed["stdio_observer"]
        attempt.update(
            valid=not defer_validation,
            status="observed" if defer_validation else "complete",
            sample_id=observed["sample_id"],
        )
    except BaseException as error:
        attempt.update(
            valid=False, status="failed", failure=f"{type(error).__name__}: {error}"
        )
        if hasattr(error, "evidence_threads"):
            attempt["owner_threads"] = error.evidence_threads
        if receipt.is_file():
            try:
                attempt["partial_observation"] = json.loads(receipt.read_text())
            except (OSError, ValueError) as receipt_error:
                attempt["receipt_error"] = type(receipt_error).__name__
        raise
    finally:
        attempt["load_after"] = os.getloadavg()
        inert.write_report(path, report)


def provision_slot(requirements, wheels, sources, reference, output, report, path):
    """Build both environments at one path, using the retained installer owner."""
    # Keep the canonical interpreter path within the supported console shebang
    # template. Parked environments are never copied from another prefix.
    parent = inert.ROOT / ".artifacts/g18-slots"
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    slot = installation_slot.InstallationSlot(parent)
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("uv is required for fixed-slot provisioning")
    requirements = requirements.resolve(strict=True)
    expected_requirements = inert.digest(requirements)
    report["slot"] = slot.receipt
    report["slot_builds"] = []
    report["requirements"] = dict(path=str(requirements), sha256=expected_requirements)
    for side in ("a", "b"):
        control = output / f"build-{side}"
        control.mkdir()
        attempt = dict(side=side, status="running", commands=[])
        report["slot_builds"].append(attempt)
        inert.write_report(path, report)

        def build(prefix, *, control=control, side=side, attempt=attempt):
            report["slot"] = slot.receipt
            environment = inert.private_environment(
                control / "environment", Path(sys.prefix), control / "bytecode"
            )
            common = [
                uv,
                "--no-config",
                "--offline",
                "--cache-dir",
                str(inert.ROOT / ".artifacts/g18-design/uv-cache"),
            ]
            commands = [
                [*common, "venv", "--python", sys.executable, str(prefix)],
                [
                    *common,
                    "pip",
                    "install",
                    "--python",
                    str(prefix / "bin/python"),
                    "--require-hashes",
                    "--no-deps",
                    "-r",
                    str(requirements),
                ],
                [
                    *common,
                    "pip",
                    "install",
                    "--python",
                    str(prefix / "bin/python"),
                    "--no-deps",
                    str(wheels[side]),
                ],
            ]
            if inert.digest(requirements) != expected_requirements:
                raise ValueError("slot requirements changed before installation")
            if inert.digest(wheels[side]) != sources[side]["wheel_sha256"]:
                raise ValueError("slot wheel changed before installation")
            for argv in commands:
                command = dict(argv=argv, status="running")
                attempt["commands"].append(command)
                inert.write_report(path, report)
                result = inert.capture(argv, cwd=control, env=environment, timeout=120)
                command.update(status="observed", result=result)
                inert.write_report(path, report)
                if result["failure"] or result["exit_code"] != 0:
                    raise ValueError(
                        "fixed-slot installer failed; retained evidence in report"
                    )
            if inert.digest(requirements) != expected_requirements:
                raise ValueError("slot requirements changed during installation")
            identity = control / "identity"
            identity.mkdir()
            receipt = inert.verify_pinned_install(
                prefix, wheels[side], identity, sources[side]["wheel_sha256"]
            )
            if any(
                receipt[key] != reference[key]
                for key in ("python", "dependencies", "entries")
            ):
                raise ValueError(
                    "fixed-slot installation differs from reference contract"
                )
            attempt["installation"] = receipt

        try:
            slot.provision(side, build)
            attempt["status"] = "complete"
        except BaseException as error:
            attempt.update(status="failed", failure=f"{type(error).__name__}: {error}")
            raise
        finally:
            report["slot"] = slot.receipt
            inert.write_report(path, report)
    return slot


def run_recovery_stage(
    stage,
    attempt,
    subject,
    control,
    *,
    case,
    measured,
    bytecode,
    observer_prefix,
    output,
    report,
    path,
    before_launch=None,
):
    workspace = subject / "workspace"
    if stage == "prepare":
        workspace.mkdir(mode=0o700)
    else:
        assert workspace.is_dir()
    environment = inert.private_environment(
        subject / "environment",
        measured,
        bytecode or output / "recovery-bytecode",
    )
    environment.update(COLUMNS="100", LINES="30")
    receipt = control / f"{stage}-{attempt['iteration']}.json"
    attempt.update(receipt=str(receipt), load_before=os.getloadavg())
    inert.write_report(path, report)
    try:
        if before_launch is not None:
            before_launch(attempt)
        owner.run_python(
            [
                str(observer_prefix / "bin/python"),
                "-I",
                str(PROBE),
                str(workspace),
                f"{stage}:{case}",
                str(receipt),
                str(measured),
                str(output / "observer-bytecode"),
            ],
            cwd=control,
            environment=environment,
            timeout=240 if stage == "prepare" else 150,
        )
    finally:
        attempt["load_after"] = os.getloadavg()
        inert.write_report(path, report)
    value = json.loads(receipt.read_text())
    if (
        type(value) is not dict
        or set(value) != OBSERVER_FIELDS | {"recovery_stage"}
        or value["status"] != "observed"
        or value["valid"] is not False
        or value["case"] != case
        or value["recovery_stage"] != stage
        or value["schema_version"] != 2
        or value["measured_prefix"] != str(measured)
        or value["observer_prefix"] != str(observer_prefix)
        or value["sample_id"] != str(subject.resolve())
        or not Path(value["observer_origin"])
        .resolve()
        .is_relative_to(observer_prefix.resolve())
    ):
        raise ValueError("restored recovery observer mismatch")
    setup = value["seed_setup"]
    if stage == "prepare":
        validate_seed(value["seed"], case)
        validate_setup_order(setup)
        if value["spawns"] or value["milestones"]:
            raise ValueError("recovery setup did not settle two real launches")
        launches = [item["spawns"] for item in setup]
    else:
        if setup or value["seed"] != "coordinator-verified-snapshot":
            raise ValueError("restored recovery invented fresh/seed setup")
        expected = {
            "ready_frame_seconds",
            "history_visible_seconds",
            "first_command_seconds",
            "spawn_through_first_command_seconds",
            "settlement_seconds",
        }
        if set(value["milestones"]) != expected or any(
            type(t) not in (int, float) or not math.isfinite(t) or t <= 0
            for t in value["milestones"].values()
        ):
            raise ValueError("restored recovery milestone missing")
        launches = [value["spawns"]]
    for index, group in enumerate(launches):
        workspace_arg = (
            workspace / "other-workspace"
            if case == "recovery-global" and (stage == "restored" or index == 1)
            else workspace
        )
        argv = [
            str(measured / "bin/loushang-hosted-tui"),
            "--workspace",
            str(workspace_arg),
            "--application-root",
            str(workspace / "application"),
            "--cwd-sessions",
            str(workspace / "cwd"),
            "--home-sessions",
            str(workspace / "home"),
        ]
        if stage == "restored" or index == 1:
            argv.extend(["--mux", "picker"])
        if (
            len(group) != 1
            or set(group[0]) != {"pid", "start", "argv", "cwd"}
            or group[0]["argv"] != argv
            or group[0]["cwd"] != str(workspace)
            or type(group[0]["pid"]) is not int
            or group[0]["pid"] <= 1
            or type(group[0]["start"]) not in (int, float)
            or not math.isfinite(group[0]["start"])
            or group[0]["start"] <= 0
        ):
            raise ValueError("restored recovery measured entry mismatch")
    attempt["observation"] = value


def restored_recovery_preflight(
    prefix,
    observer_prefix,
    output,
    report,
    path,
    *,
    slot=None,
    wheels=None,
    sources=None,
    temporary_parent=Path("/tmp"),
):
    """Baseline-only owner/reset integration; not a paired timing comparison."""
    report["recovery_states"] = {}
    for case in ("recovery-cwd", "recovery-global"):
        state = recovery_state.RecoveryState(temporary_parent, output)
        report["recovery_states"][case] = dict(
            subject=str(state.subject), control=str(state.control)
        )

        stage_operation = partial(
            run_recovery_stage,
            case=case,
            measured=prefix,
            bytecode=None,
            observer_prefix=observer_prefix,
            output=output,
            report=report,
            path=path,
        )

        sequence = ("a", "a", "b", "a") if slot is not None else ("a", "a", "a")
        for iteration, side in enumerate(sequence):
            stage = "prepare" if iteration == 0 else "restored"
            attempt = dict(
                case=case,
                stage=stage,
                iteration=iteration,
                status="running",
                valid=False,
            )
            if slot is not None:
                attempt["side"] = side
            report["samples"].append(attempt)
            inert.write_report(path, report)
            try:

                def execute(
                    measured,
                    *,
                    iteration=iteration,
                    side=side,
                    attempt=attempt,
                    stage=stage,
                    state=state,
                    stage_operation=stage_operation,
                ):
                    if slot is not None:
                        report["slot"] = slot.receipt
                        inert.write_report(path, report)
                        identity = state.control / f"pre-identity-{iteration}"
                        identity.mkdir()
                        attempt["pre_installation"] = inert.verify_pinned_install(
                            measured,
                            wheels[side],
                            identity,
                            sources[side]["wheel_sha256"],
                        )
                        if (
                            attempt["pre_installation"]
                            != report["slot_builds"][0 if side == "a" else 1][
                                "installation"
                            ]
                        ):
                            raise ValueError("slot pre-operation installation changed")
                    operation = partial(
                        stage_operation,
                        stage,
                        attempt,
                        measured=measured,
                        bytecode=output / f"slot-bytecode-{side}"
                        if slot is not None
                        else None,
                    )
                    if iteration == 0:
                        state.prepare(operation)
                        attempt["snapshot"] = state.receipt
                        validate_prepared_snapshot(
                            attempt["observation"]["seed"], state.receipt
                        )
                    else:
                        state.sample(operation)
                    if slot is not None:
                        identity = state.control / f"post-identity-{iteration}"
                        identity.mkdir()
                        attempt["post_installation"] = inert.verify_pinned_install(
                            measured,
                            wheels[side],
                            identity,
                            sources[side]["wheel_sha256"],
                        )
                        if attempt["post_installation"] != attempt["pre_installation"]:
                            raise ValueError("slot post-operation installation changed")

                if slot is not None:
                    slot.run(side, execute)
                else:
                    execute(prefix)
                attempt.update(status="complete", valid=True, snapshot=state.receipt)
                report["recovery_states"][case].update(snapshot=state.receipt)
            except BaseException as error:
                attempt.update(
                    status="failed", failure=f"{type(error).__name__}: {error}"
                )
                receipt = Path(attempt["receipt"]) if "receipt" in attempt else None
                if receipt is not None and receipt.is_file():
                    try:
                        attempt["partial_observation"] = json.loads(receipt.read_text())
                    except (OSError, ValueError) as receipt_error:
                        attempt["receipt_error"] = type(receipt_error).__name__
                raise
            finally:
                if slot is not None:
                    report["slot"] = slot.receipt
                inert.write_report(path, report)
            print(f"{case} {stage} iteration={iteration}: complete", flush=True)


def collect_fixed_native(
    slot,
    cache_mode,
    cases,
    blocks,
    pairs,
    observer_prefix,
    wheels,
    sources,
    output,
    report,
    path,
    *,
    temporary_parent=Path("/tmp"),
    campaign=None,
):
    """Declared warmups and paired native cases at one pinned execution prefix."""
    resumed = campaign is not None and campaign.resuming
    caches = (
        campaign.native[1] if resumed else bytecode_policy.BytecodePolicy(slot, output)
    )
    cache_evidence = output / "cache-evidence"
    if not resumed:
        cache_evidence.mkdir()
    report["cache_policy"] = dict(
        mode=cache_mode,
        external={side: str(caches.external(side)) for side in ("a", "b")},
        base="Python/stdlib shared as found",
        product_state="seed-preserved; never cleared",
    )
    if not resumed:
        report["seed_setup"] = []
        report["recovery_states"] = {}
    states = campaign.native[2] if resumed else {}

    def pin(prefix, side, control, label, attempt):
        identity = control / f"{label}-identity-{attempt['iteration']}"
        identity.mkdir()
        value = inert.verify_pinned_install(
            prefix, wheels[side], identity, sources[side]["wheel_sha256"]
        )
        attempt[f"{label}_installation"] = value
        expected = report["slot_builds"][0 if side == "a" else 1]["installation"]
        if value != expected:
            raise ValueError(f"fixed-slot {label} installation changed")

    def write_cache(attempt, label, value):
        evidence = cache_evidence / f"{attempt['iteration']:05d}-{label}.json"
        inert.write_report(evidence, value)
        attempt.setdefault("cache", {})[label] = dict(
            path=str(evidence), sha256=inert.digest(evidence)
        )
        inert.write_report(path, report)

    # Setup is excluded from samples and timings. Each scope has one immutable
    # baseline seed for all warmups, blocks and variants in this collector run.
    for case in cases:
        if not case.startswith("recovery-") or resumed:
            continue
        state = recovery_state.RecoveryState(temporary_parent, output)
        states[case] = state
        attempt = dict(
            case=case,
            stage="prepare",
            side="a",
            iteration=0,
            status="running",
            valid=False,
        )
        report["seed_setup"].append(attempt)
        report["recovery_states"][case] = dict(
            subject=str(state.subject), control=str(state.control)
        )
        inert.write_report(path, report)

        def prepare(prefix, *, case=case, state=state, attempt=attempt):
            pin(prefix, "a", state.control, "pre", attempt)
            state.prepare(
                partial(
                    run_recovery_stage,
                    "prepare",
                    attempt,
                    case=case,
                    measured=prefix,
                    bytecode=caches.external("a"),
                    observer_prefix=observer_prefix,
                    output=output,
                    report=report,
                    path=path,
                )
            )
            validate_prepared_snapshot(attempt["observation"]["seed"], state.receipt)
            pin(prefix, "a", state.control, "post", attempt)

        try:
            slot.run("a", prepare)
            attempt.update(status="complete", valid=True)
            if campaign is not None:
                attempt["receipt_sha256"] = inert.digest(Path(attempt["receipt"]))
            report["recovery_states"][case]["snapshot"] = state.receipt
        except BaseException as error:
            attempt.update(status="failed", failure=f"{type(error).__name__}: {error}")
            raise
        finally:
            report["slot"] = slot.receipt
            inert.write_report(path, report)

    warmed = {
        (sample["block"], sample["case"], sample["side"])
        for sample in report["samples"]
        if sample["warmup"]
    }
    completed = len(report["samples"])
    number = 0
    for block in range(blocks):
        for pair in range(-1, pairs):
            for case in cases if block % 2 == 0 else reversed(cases):
                for side in ("a", "b") if (block + pair) % 2 == 0 else ("b", "a"):
                    number += 1
                    if number <= completed:
                        continue
                    key = (block, case, side)
                    attempt = dict(
                        case=case,
                        side=side,
                        block=block,
                        pair=pair,
                        warmup=pair == -1,
                        cache_mode=cache_mode,
                        iteration=number,
                        status="running",
                        valid=False,
                    )
                    report["samples"].append(attempt)
                    state = states.get(case)
                    root = (
                        state.subject
                        if state is not None
                        else Path(report["scratch"]) / f"sample-{number}"
                    )
                    control = state.control if state is not None else root / "control"
                    if state is None:
                        control.mkdir(parents=True)
                    inert.write_report(path, report)

                    def execute(
                        prefix,
                        *,
                        attempt=attempt,
                        state=state,
                        control=control,
                        root=root,
                        side=side,
                        key=key,
                        case=case,
                        pair=pair,
                    ):
                        if pair >= 0 and key not in warmed:
                            raise ValueError(
                                "native sample has no completed declared warmup"
                            )
                        report["slot"] = slot.receipt
                        pin(prefix, side, control, "pre", attempt)

                        def before_launch(value):
                            if state is not None:
                                snapshot = state.receipt
                                age = time.time() - snapshot["created_at"]
                                if not math.isfinite(age) or age < 0:
                                    raise ValueError("recovery seed age is invalid")
                                value["recovery_input"] = dict(
                                    sha256=snapshot["sha256"],
                                    restores=snapshot["restores"],
                                    created_at=snapshot["created_at"],
                                    age_before_observer_seconds=age,
                                )
                            # Last target preparation: the next Python belongs to
                            # the fixed observer, not the measured installation.
                            write_cache(
                                value, "before", caches.prepare(side, cache_mode)
                            )

                        if state is not None:
                            attempt["stage"] = "restored"
                            state.sample(
                                partial(
                                    run_recovery_stage,
                                    "restored",
                                    attempt,
                                    case=case,
                                    measured=prefix,
                                    bytecode=caches.external(side),
                                    observer_prefix=observer_prefix,
                                    output=output,
                                    report=report,
                                    path=path,
                                    before_launch=before_launch,
                                )
                            )
                            attempt["milestones"] = attempt["observation"]["milestones"]
                        else:
                            run_sample(
                                prefix,
                                case,
                                root,
                                caches.external(side),
                                report,
                                path,
                                {},
                                observer_prefix=observer_prefix,
                                attempt=attempt,
                                before_launch=before_launch,
                                defer_validation=True,
                            )
                            if campaign is not None:
                                attempt["receipt"] = str(root / "native.json")
                        write_cache(attempt, "after", caches.inspect(side))
                        pin(prefix, side, control, "post", attempt)

                    try:
                        slot.run(side, execute)
                        attempt.update(status="complete", valid=True)
                        if campaign is not None:
                            attempt["receipt_sha256"] = inert.digest(
                                Path(attempt["receipt"])
                            )
                        if pair == -1:
                            warmed.add(key)
                    except BaseException as error:
                        attempt.update(
                            status="failed",
                            valid=False,
                            failure=f"{type(error).__name__}: {error}",
                        )
                        receipt = (
                            Path(attempt["receipt"]) if "receipt" in attempt else None
                        )
                        if receipt is not None and receipt.is_file():
                            try:
                                attempt["partial_observation"] = json.loads(
                                    receipt.read_text()
                                )
                            except (OSError, ValueError) as receipt_error:
                                attempt["receipt_error"] = type(receipt_error).__name__
                        raise
                    finally:
                        report["slot"] = slot.receipt
                        inert.write_report(path, report)
                    print(
                        f"{case} cache={cache_mode} block={block} pair={pair} side={side}: complete",
                        flush=True,
                    )
                    if campaign is not None and campaign.wants_pause(report):
                        resources = native_checkpoint(
                            campaign, report, slot, caches, states
                        )
                        campaign.pause(report, resources)


def native_checkpoint(campaign, report, slot, caches, states):
    """Seal only after all native guards/owners and postchecks have returned."""
    checkpoint = support("_g18_checkpoint")
    if (
        "helpers_before" in report
        and inert.provenance_module().helper_manifest(inert.ROOT)
        != report["helpers_before"]
    ):
        raise ValueError("trusted helpers changed before checkpoint")
    installation_paths = [
        Path(value["prefix"]) for value in report["installations"].values()
    ] + [Path(report["observer_installation"]["prefix"])]
    installation_paths += [
        slot.prefix if slot.receipt["active"] == side else slot.root / side
        for side in ("a", "b")
    ]
    return {
        "slot": slot.checkpoint(),
        "caches": caches.checkpoint(),
        "recovery": {case: state.checkpoint() for case, state in states.items()},
        "scratch_identity": checkpoint.identity(Path(report["scratch"])),
        "trees": {
            str(path): checkpoint.tree_manifest(path)
            for path in [
                *installation_paths,
                campaign.output / "observer-bytecode",
                *(state.archive for state in states.values()),
            ]
        },
    }


def reopen_native(campaign, report):
    """All paused file state is checked before a new interpreter probe runs."""
    checkpoint = support("_g18_checkpoint")
    resources = campaign.resources
    if checkpoint.identity(Path(report["scratch"])) != resources["scratch_identity"]:
        raise ValueError("checkpoint scratch changed")
    for path, expected in resources["trees"].items():
        if checkpoint.tree_manifest(Path(path)) != expected:
            raise ValueError("installation or observer cache changed during pause")
    slot = installation_slot.InstallationSlot.reopen(resources["slot"])
    caches = bytecode_policy.BytecodePolicy.reopen(slot, resources["caches"])
    states = {
        case: recovery_state.RecoveryState.reopen(value)
        for case, value in resources["recovery"].items()
    }
    return slot, caches, states


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "--request-pause":
        support("_g18_checkpoint").request_pause(Path(argv[1]))
        print("pause requested; wait for collector status=paused (not stopped yet)")
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="enable opt-in safe-boundary checkpoints (fixed-slot only)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume a v3 safe pause using the same original arguments",
    )
    parser.add_argument(
        "--pause-after",
        type=int,
        help="pause after this cumulative observation count, including warmups",
    )
    parser.add_argument("--install-a", type=Path, required=True)
    parser.add_argument("--install-b", type=Path, required=True)
    parser.add_argument(
        "--observer-install",
        type=Path,
        required=True,
        help="third, fixed installation of wheel A; never used as a measured installation",
    )
    inert.add_source_arguments(parser)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scratch-parent",
        type=inert.existing_scratch_parent,
        default=Path("/tmp"),
        help="existing parent for fresh task-owned temporary directories (default: /tmp)",
    )
    parser.add_argument(
        "--fixed-slot",
        action="store_true",
        help="collect native paired cases at one installed execution prefix",
    )
    parser.add_argument(
        "--cache-mode",
        choices=("warm", "absent"),
        help="explicit task-owned installation/external bytecode condition for --fixed-slot",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--slot-switch-recovery-preflight",
        action="store_true",
        help="same-wheel two-venv A/B/A at one fixed prefix; correctness only",
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        help="locked hashed dependency export for slot provisioning",
    )
    selection.add_argument(
        "--restored-recovery-preflight",
        action="store_true",
        help="baseline A fixed-prefix seed/reset integration only, not A/B timing",
    )
    selection.add_argument(
        "--home-isolation-only",
        action="store_true",
        help="four real HOME controls per installation, without timing samples",
    )
    selection.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--pairs-per-block", type=int, default=10)
    args = parser.parse_args(argv)
    if args.fixed_slot:
        if args.cache_mode is None or args.requirements is None:
            parser.error("--fixed-slot requires --cache-mode and --requirements")
        if (
            args.slot_switch_recovery_preflight
            or args.restored_recovery_preflight
            or args.home_isolation_only
        ):
            parser.error("fixed-slot timing and correctness-only modes are separate")
    elif args.cache_mode is not None:
        parser.error("--cache-mode requires --fixed-slot")
    if args.slot_switch_recovery_preflight:
        if args.requirements is None:
            parser.error("slot-switch recovery requires --requirements")
        args.restored_recovery_preflight = True
    elif args.requirements is not None and not args.fixed_slot:
        parser.error("--requirements requires a fixed installation slot")
    if args.pause_after is not None and args.pause_after < 1:
        parser.error("--pause-after must be positive")
    if args.checkpoint or args.resume or args.pause_after is not None:
        if not args.fixed_slot:
            parser.error("checkpoint/resume requires --fixed-slot")
        checkpoint = support("_g18_checkpoint")
        with checkpoint.Campaign(
            args.output, resume=args.resume, pause_after=args.pause_after
        ) as campaign:
            return collect_main(args, parser, campaign)
    return collect_main(args, parser)


def collect_main(args, parser, campaign=None):
    if platform.system() != "Linux":
        parser.error("Linux native collection only")
    if (
        args.blocks < 1
        or args.pairs_per_block < 1
        or len(set(args.cases)) != len(args.cases)
    ):
        parser.error("positive counts and unique cases required")
    if args.home_isolation_only:
        args.cases, args.blocks, args.pairs_per_block = ["home-isolation"], 1, 1
    if args.restored_recovery_preflight:
        args.cases, args.blocks, args.pairs_per_block = (
            ["recovery-cwd", "recovery-global"],
            1,
            1,
        )
    prefixes = {"a": args.install_a.absolute(), "b": args.install_b.absolute()}
    if prefixes["a"].resolve() == prefixes["b"].resolve():
        parser.error("independent installations required")
    observer_prefix = args.observer_install.absolute()
    if observer_prefix.resolve() in {prefix.resolve() for prefix in prefixes.values()}:
        parser.error(
            "observer installation must be independent of measured installations"
        )
    wheels, sources = inert.source_pair(args, parser)
    mode = (
        "aa" if sources["a"]["wheel_sha256"] == sources["b"]["wheel_sha256"] else "ab"
    )
    if args.restored_recovery_preflight and mode != "aa":
        parser.error("restored recovery preflight requires the same baseline wheel")
    output = args.output.absolute()
    resumed = campaign is not None and campaign.resuming
    if campaign is None:
        output.mkdir(parents=True, exist_ok=False)
    scratch = (
        Path(campaign.report["scratch"])
        if resumed
        else Path(
            tempfile.mkdtemp(prefix="loushang-g18-native-", dir=args.scratch_parent)
        )
    )
    report = {
        "schema_version": 2,
        "status": "running",
        "comparison": {"verdict": "not-evaluated", "reason": "collection incomplete"},
        "scope": f"linux-native-fixed-slot-{mode}-record-only"
        if args.fixed_slot
        else "linux-slot-switch-recovery-preflight-only"
        if args.slot_switch_recovery_preflight
        else "linux-restored-recovery-preflight-only"
        if args.restored_recovery_preflight
        else "linux-native-home-isolation-only"
        if args.home_isolation_only
        else f"linux-native-{mode}-record-only",
        "source_receipts": sources,
        "helpers_before": inert.provenance_module().helper_manifest(inert.ROOT),
        "provenance_support_sha256": inert.digest(
            Path(inert.__file__).with_name("_g18_provenance.py")
        ),
        "source_commit": sources["b"]["commit"],
        "lock_sha256": sources["b"]["lock_sha256"],
        "wheel_sha256": {
            side: source["wheel_sha256"] for side, source in sources.items()
        },
        "runner_sha256": inert.digest(Path(__file__)),
        "recovery_support_sha256": inert.digest(Path(recovery_state.__file__)),
        "slot_support_sha256": inert.digest(Path(installation_slot.__file__)),
        "bytecode_support_sha256": inert.digest(Path(bytecode_policy.__file__)),
        "probe_sha256": inert.digest(PROBE),
        "inert_support_sha256": inert.digest(Path(inert.__file__)),
        "platform": platform.platform(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "condition": f"fresh process; fixed measured prefix; {args.cache_mode} task-owned installed/external bytecode; base Python/stdlib as found; fixed observer; Product state fresh or baseline-seed-restored; no warm Store-head claim"
        if args.fixed_slot
        else "same baseline wheel; two venvs at fixed prefix via rename; restored bytes/modes/mtime; per-variant bytecode as found; no warm Store-head or timing claim"
        if args.slot_switch_recovery_preflight
        else "baseline fixed-prefix; restored bytes/modes/mtime; bytecode as found; no warm Store-head or A/B timing claim"
        if args.restored_recovery_preflight
        else "correctness controls only; no timing comparison"
        if args.home_isolation_only
        else "fresh process; warm bytecode; fixed baseline observer and separate observer cache; private per-sample state; native PTY 100x30; OS page cache uncontrolled",
        "cases": args.cases,
        "blocks": args.blocks,
        "pairs_per_block": args.pairs_per_block,
        "scratch": str(scratch),
        "scratch_parent": str(args.scratch_parent),
        "scratch_device": scratch.stat().st_dev,
        "samples": [],
        "installations": {},
    }
    path = output / "report.json"
    if campaign is not None:
        plan = {
            key: report[key]
            for key in (
                "scope",
                "source_receipts",
                "helpers_before",
                "runner_sha256",
                "probe_sha256",
                "condition",
                "cases",
                "blocks",
                "pairs_per_block",
            )
        }
        plan.update(
            references={side: str(prefix) for side, prefix in prefixes.items()},
            observer=str(observer_prefix),
            scratch_parent=str(args.scratch_parent),
            requirements=dict(
                path=str(args.requirements.resolve()),
                sha256=inert.digest(args.requirements),
            ),
        )
        if resumed:
            report = campaign.report
        campaign.begin(report, plan)
        if resumed:
            campaign.native = reopen_native(campaign, report)
    inert.write_report(path, report)
    try:
        segment_prefix = f"resume-{campaign.value['segment']}-" if resumed else ""
        observer_root = scratch / f"{segment_prefix}observer-identity"
        observer_root.mkdir()
        verified = inert.verify_pinned_install(
            observer_prefix, wheels["a"], observer_root, sources["a"]["wheel_sha256"]
        )
        if resumed and verified != report["observer_installation"]:
            raise ValueError("observer identity changed during pause")
        report["observer_installation"] = verified
        for side, prefix in prefixes.items():
            root = scratch / f"{segment_prefix}identity-{side}"
            root.mkdir()
            verified = inert.verify_pinned_install(
                prefix, wheels[side], root, sources[side]["wheel_sha256"]
            )
            if resumed and verified != report["installations"][side]:
                raise ValueError("reference installation changed during pause")
            report["installations"][side] = verified
        left, right = report["installations"].values()
        for key in ("python", "dependencies", "entries"):
            if (
                left[key] != right[key]
                or left[key] != report["observer_installation"][key]
            ):
                raise ValueError(f"paired installation contract differs: {key}")
        if args.fixed_slot:
            slot = (
                campaign.native[0]
                if resumed
                else provision_slot(
                    args.requirements,
                    wheels,
                    sources,
                    report["observer_installation"],
                    output,
                    report,
                    path,
                )
            )
            collect_fixed_native(
                slot,
                args.cache_mode,
                args.cases,
                args.blocks,
                args.pairs_per_block,
                observer_prefix,
                wheels,
                sources,
                output,
                report,
                path,
                temporary_parent=args.scratch_parent,
                **({"campaign": campaign} if campaign is not None else {}),
            )
        elif args.restored_recovery_preflight:
            slot = (
                provision_slot(
                    args.requirements,
                    wheels,
                    sources,
                    report["observer_installation"],
                    output,
                    report,
                    path,
                )
                if args.slot_switch_recovery_preflight
                else None
            )
            restored_recovery_preflight(
                prefixes["a"],
                observer_prefix,
                output,
                report,
                path,
                slot=slot,
                wheels=wheels,
                sources=sources,
                temporary_parent=args.scratch_parent,
            )
        for block in range(
            0 if args.restored_recovery_preflight or args.fixed_slot else args.blocks
        ):
            for pair in (
                range(1)
                if args.home_isolation_only
                else range(-1, args.pairs_per_block)
            ):
                cases = args.cases if block % 2 == 0 else reversed(args.cases)
                for case in cases:
                    for side in ("a", "b") if (block + pair) % 2 == 0 else ("b", "a"):
                        root = scratch / f"b{block}-p{pair}-{case}-{side}"
                        run_sample(
                            prefixes[side],
                            case,
                            root,
                            output / f"bytecode-{side}",
                            report,
                            path,
                            dict(block=block, pair=pair, side=side, warmup=pair == -1),
                            observer_prefix=observer_prefix,
                        )
                        print(
                            f"{case} block={block} pair={pair} side={side}: complete",
                            flush=True,
                        )
        for side, prefix in prefixes.items():
            root = scratch / f"final-identity-{side}"
            root.mkdir()
            if (
                inert.verify_pinned_install(
                    prefix, wheels[side], root, sources[side]["wheel_sha256"]
                )
                != report["installations"][side]
            ):
                raise ValueError("installation changed during measurement")
        observer_root = scratch / "final-observer-identity"
        observer_root.mkdir()
        if (
            inert.verify_pinned_install(
                observer_prefix,
                wheels["a"],
                observer_root,
                sources["a"]["wheel_sha256"],
            )
            != report["observer_installation"]
        ):
            raise ValueError("observer installation changed during measurement")
        report["helpers_after"] = inert.provenance_module().helper_manifest(inert.ROOT)
        if report["helpers_after"] != report["helpers_before"]:
            raise ValueError("trusted helper inputs changed during measurement")
        if (
            args.fixed_slot
            and set(args.cases) == set(CASES)
            and args.blocks == 2
            and args.pairs_per_block == 10
        ):
            report["comparison"] = inert.comparison_module().compare_native(
                report["samples"],
                cache_mode=args.cache_mode,
                phase=mode,
                blocks=args.blocks,
                pairs_per_block=args.pairs_per_block,
            )
        else:
            report["comparison"]["reason"] = (
                "requires all seven fixed-slot cases and exactly two blocks of ten pairs"
            )
        report["status"] = "complete-record-only"
        if campaign is not None:
            campaign.finish(report)
    except BaseException as error:
        if campaign is not None and campaign.is_pause(error):
            return 0
        report.update(status="failed", failure=f"{type(error).__name__}: {error}")
        raise
    finally:
        if campaign is None or report["status"] not in {
            "paused",
            "complete-record-only",
        }:
            inert.write_report(path, report)
        print(f"evidence: {path}; scratch retained: {scratch}", flush=True)
        print(f"advisory comparison: {report['comparison']['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
