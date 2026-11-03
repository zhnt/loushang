"""Record Linux native startup milestones, outside the Product runtime.

This A/A or A/B collector is deliberately record-only. Warmups and failures remain in
the report; wall timing comes from the private native observer, not test elapsed.
Exit zero means collection completed, not that the comparison verdict passed.
"""

from __future__ import annotations

import argparse
import hashlib
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
HISTORY_CASES = ("managed-product-history-warm", "managed-product-history-restore")
OPTIONAL_CASES = ("managed-mux", "managed-product-first-use", *HISTORY_CASES)
HISTORY_WARM_FIELDS = {
    "measured_prefix", "status", "valid", "spawns", "terminal_settlements",
    "fixed_product_target", "fixed_product_detached", "fixed_product_native",
    "fixed_product_stop", "fixed_product_history",
}
HISTORY_RESTORE_FIELDS = {"history_generations", "fixed_product_history_restore"}


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

MANAGED_OBSERVER_FIELDS = {
    "managed_stop", "authenticated_instance_id", "managed_observations", "managed_actions",
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
    elif case == "managed-mux":
        fields = fields | MANAGED_OBSERVER_FIELDS
    elif case == "managed-product-first-use":
        fields = fields | {"fixed_product_scenarios", "outer_settlement"}
    elif case in HISTORY_CASES:
        fields = fields | (HISTORY_WARM_FIELDS if case == HISTORY_CASES[0] else HISTORY_RESTORE_FIELDS) | {"outer_settlement"}
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
    if case == "managed-mux":
        validate_managed_observation(value, prefix, root)
        return
    if case == "managed-product-first-use":
        validate_managed_product_collection(value, prefix, root)
        return
    if case in HISTORY_CASES:
        milestones = validate_managed_history_collection(value, prefix, root)
        if value["milestones"] != milestones or any(type(value["milestones"][key]) not in (int, float) for key in milestones):
            raise ValueError("history milestone summary differs from original endpoints")
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


def validate_managed_observation(value, prefix, root):
    """Validate the optional scenario's exact frame/query receipt inventory.

    These are values from the trusted installed observer, not an authentication
    mechanism. Its source and wheel provenance are still checked by the caller.
    """
    metrics = inert.comparison_module().MANAGED_METRICS["managed-mux"]
    milestones = value["milestones"]
    if (
        type(milestones) is not dict or set(milestones) != set(metrics)
        or any(type(item) not in (int, float) or not math.isfinite(item) or item <= 0
               for item in milestones.values())
        or value["seed"] != "empty" or value["seed_setup"] != []
    ):
        raise ValueError("managed milestone or fresh-state inventory mismatch")
    spawns = value["spawns"]
    if type(spawns) is not list or len(spawns) != 2:
        raise ValueError("managed foreground spawn inventory mismatch")
    workspace = (root / "workspace").resolve()
    for spawn, cwd, arguments in zip(
        spawns, (workspace, workspace / "elsewhere"),
        (("new", "-s", "perf"), ("attach", "-t", "perf")), strict=True,
    ):
        if (
            type(spawn) is not dict or set(spawn) != {"pid", "start", "argv", "cwd"}
            or type(spawn["pid"]) is not int or spawn["pid"] <= 0
            or type(spawn["start"]) not in (int, float)
            or not math.isfinite(spawn["start"]) or spawn["start"] <= 0
            or spawn["cwd"] != str(cwd)
            or spawn["argv"] != [str(prefix / "bin/lmux"), *arguments]
        ):
            raise ValueError("managed foreground identity mismatch")
    observations = value.get("managed_observations")
    if type(observations) is not list or len(observations) != 4:
        raise ValueError("managed authenticated observations missing")
    instance = value.get("authenticated_instance_id")
    if type(instance) is not str or re.fullmatch(r"[0-9a-f]{32}", instance) is None:
        raise ValueError("managed authenticated instance invalid")
    original = None
    previous_at = spawns[0]["start"] + milestones["cold_through_first_member_seconds"]
    previous_members = None
    for record, stage, count in zip(
        observations, ("first-member", "second-member", "detached", "reattached"),
        (1, 2, 2, 2), strict=True,
    ):
        if (
            type(record) is not dict
            or set(record) != {"stage", "observed_at", "instanceId", "serviceId", "muxId", "members"}
            or record["stage"] != stage or record["instanceId"] != instance
            or type(record["serviceId"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", record["serviceId"]) is None
            or type(record["muxId"]) is not str or not 1 <= len(record["muxId"]) <= 256
            or type(record["observed_at"]) not in (int, float)
            or not math.isfinite(record["observed_at"]) or record["observed_at"] < previous_at
            or type(record["members"]) is not list or len(record["members"]) != count
        ):
            raise ValueError("managed authenticated query identity mismatch")
        identity = record["serviceId"], record["muxId"]
        if original is not None and identity != original:
            raise ValueError("managed query changed service or mux")
        original, previous_at = identity, record["observed_at"]
        members = record["members"]
        if any(type(member) is not dict or set(member) != {"memberId", "sessionId"}
               or any(type(item) is not str or not 1 <= len(item) <= 256 for item in member.values())
               for member in members):
            raise ValueError("managed member identity malformed")
        if (len({member["memberId"] for member in members}) != count
                or len({member["sessionId"] for member in members}) != count
                or previous_members is not None and members[:len(previous_members)] != previous_members):
            raise ValueError("managed member was replaced or duplicated")
        previous_members = members
    if not observations[2]["observed_at"] <= spawns[1]["start"] <= observations[3]["observed_at"]:
        raise ValueError("managed reconnect does not follow detached live observation")
    actions = value.get("managed_actions")
    action_names = ("first_completion", "first_member_ready", "warm_member_ready",
                    "detach_settlement", "reattach_detach_settlement")
    if type(actions) is not dict or set(actions) != set(action_names):
        raise ValueError("managed action intervals missing")
    for name in action_names:
        action = actions[name]
        if (
            type(action) is not dict or set(action) != {"started_at", "finished_at"}
            or any(type(item) not in (int, float) or not math.isfinite(item) or item <= 0
                   for item in action.values())
            or action["finished_at"] - action["started_at"] != milestones[name + "_seconds"]
        ):
            raise ValueError("managed action duration mismatch")
    cold_end = spawns[0]["start"] + milestones["cold_frame_seconds"]
    first_end = spawns[0]["start"] + milestones["cold_through_first_member_seconds"]
    if not (
        cold_end <= actions["first_completion"]["started_at"]
        < actions["first_completion"]["finished_at"] <= actions["first_member_ready"]["started_at"]
        < actions["first_member_ready"]["finished_at"] == first_end
        <= observations[0]["observed_at"] <= actions["warm_member_ready"]["started_at"]
        < actions["warm_member_ready"]["finished_at"] <= observations[1]["observed_at"]
        <= actions["detach_settlement"]["started_at"] < actions["detach_settlement"]["finished_at"]
        <= observations[2]["observed_at"] <= spawns[1]["start"]
        < spawns[1]["start"] + milestones["warm_attach_frame_seconds"]
        <= observations[3]["observed_at"] <= actions["reattach_detach_settlement"]["started_at"]
        < actions["reattach_detach_settlement"]["finished_at"]
    ):
        raise ValueError("managed action and authenticated observation order mismatch")
    stop = value["managed_stop"]
    if (type(stop) is not dict or set(stop) != {"started_at", "result"}
            or type(stop["started_at"]) not in (int, float)
            or not math.isfinite(stop["started_at"])
            or stop["started_at"] < actions["reattach_detach_settlement"]["finished_at"]
            or stop["result"] != {"status": "stopped", "instanceId": instance}):
        raise ValueError("managed stop does not match authenticated lifecycle")


def validate_managed_history_collection(value, prefix, root):
    """Join generation evidence to the original observer's physical lifetime."""
    outer = value.get("outer_settlement")
    if (type(outer) is not dict or set(outer) != {"started_at", "settled_at"}
            or any(type(item) not in (int, float) or not 0 <= item <= sys.float_info.max
                   or not math.isfinite(item) for item in outer.values())
            or not outer["started_at"] < outer["settled_at"]
            or value.get("status") != "observed" or value.get("valid") is not False
            or value.get("seed") != "empty" or value.get("seed_setup") != []):
        raise ValueError("history original outer settlement or seed inventory invalid")
    bounds = dict(prefix=prefix, workspace=root / "workspace", earliest=outer["started_at"], latest=outer["settled_at"])
    if value["case"] == HISTORY_CASES[0]:
        return validate_managed_history_warm({key: value[key] for key in HISTORY_WARM_FIELDS}, **bounds)
    if value["case"] != HISTORY_CASES[1]:
        raise ValueError("unknown history collection case")
    generations = value["history_generations"]
    metrics = validate_managed_history_restore(generations, **bounds)
    if (value["spawns"] != [*generations["old"]["spawns"], *generations["new"]["spawns"]]
            or value["fixed_product_history_restore"] != generations["new"]["restored_history"]):
        raise ValueError("history restart summary differs from original generations")
    return metrics


def complete_managed_history(value, *, observer_started, owner_settled, prefix, root):
    """Only the original successful run_python caller may add outer settlement."""
    if type(value) is not dict or value.get("case") not in HISTORY_CASES:
        raise ValueError("history receipt cannot be completed")
    extras = HISTORY_WARM_FIELDS if value["case"] == HISTORY_CASES[0] else HISTORY_RESTORE_FIELDS
    if (set(value) != OBSERVER_FIELDS | extras or value.get("schema_version") != 2
            or value.get("measured_prefix") != str(prefix) or value.get("sample_id") != str(root.resolve())
            or value.get("milestones") != {}):
        raise ValueError("history raw observer inventory mismatch")
    completed = {**value, "outer_settlement": {"started_at": observer_started, "settled_at": owner_settled}}
    completed["milestones"] = validate_managed_history_collection(completed, prefix, root)
    return completed


def validate_managed_history_native(natives, *, first, stages):
    """All observations in one generation must identify the same native leader."""
    if type(natives) is not dict or set(natives) != stages:
        raise ValueError("history native stages missing")
    native = natives[first]
    if (type(native) is not dict or set(native) != {
            "pid", "start_ticks", "boot_id", "user_id", "pid_namespace_device", "pid_namespace_inode"}
            or type(native["pid"]) is not int or not 0 < native["pid"] < 2**31
            or type(native["boot_id"]) is not str
            or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", native["boot_id"]) is None
            or any(type(native[key]) is not int or not 0 <= native[key] < 2**64
                   for key in ("start_ticks", "user_id", "pid_namespace_device", "pid_namespace_inode"))
            or native["pid_namespace_inode"] == 0
            or any(type(item) is not dict or item != native
                   or any(type(item[key]) is not type(native[key]) for key in native) for item in natives.values())):
        raise ValueError("history native identity mismatch")
    return native


def validate_managed_history_restore(generations, *, prefix, workspace, earliest, latest):
    """Validate both complete lifetimes and the restart gap without promoting."""
    if type(generations) is not dict or set(generations) != {"old", "new"}:
        raise ValueError("history restart generation inventory mismatch")
    old, new = generations["old"], generations["new"]
    fields = {"measured_prefix", "status", "valid", "spawns", "terminal_settlements",
              "line_terminal_settlements", "start_command", "authenticated_at",
              "fixed_product_target", "fixed_product_native", "fixed_product_stop", "restored_history"}
    if (type(new) is not dict or set(new) != fields or new["status"] != "observed"
            or new["valid"] is not False or new["measured_prefix"] != str(prefix)):
        raise ValueError("history restart generation status mismatch")

    def timestamp(item):
        return (type(item) in (int, float) and 0 <= item <= sys.float_info.max and math.isfinite(item))

    try:
        validate_managed_history_warm(old, prefix=prefix, workspace=workspace,
                                     earliest=earliest, latest=new["spawns"][0]["start"])
        prior, target, result = old["fixed_product_history"], new["fixed_product_target"], new["restored_history"]
        if (type(result) is not dict or set(result) != {
                "attach", "canonical", "stop", "canonical_read", "action", "restored_history_frame_seconds"}
                or type(target) is not dict):
            raise ValueError("history restored result inventory mismatch")
        terminals = validate_managed_history_terminals(new, prefix=prefix, workspace=workspace,
            restored=True, earliest=prior["canonical_read"]["completed_at"], latest=latest)
        command = new["start_command"]
        if (type(command) is not dict or set(command) != {"started_at", "settled_at", "result", "exit_status"}
                or type(command["exit_status"]) is not int or command["exit_status"] != 0
                or command["result"] != {"status": "service_ready", "serviceId": target["serviceId"], "instanceId": target["instanceId"]}
                or not all(timestamp(item) for item in (command["started_at"], command["settled_at"],
                                                       target["observed_at"], new["authenticated_at"]))
                or command["started_at"] != new["spawns"][0]["start"]
                or not terminals[0]["settled_at"] <= command["settled_at"] <= target["observed_at"]
                <= new["authenticated_at"] <= new["spawns"][1]["start"]):
            raise ValueError("history restart ready or authentication order mismatch")
        if (any(target[key] != old["fixed_product_target"][key] for key in ("serviceId", "muxId", "members"))
                or target["instanceId"] == old["fixed_product_target"]["instanceId"]):
            raise ValueError("history restart must retain service and Session but change instance")
        native = validate_managed_history_native(new["fixed_product_native"], first="restored",
                                                stages={"restored", "history-detached", "stop"})
        prior_native = old["fixed_product_native"]["stop"]
        if (native == prior_native or any(native[key] != prior_native[key]
                for key in ("boot_id", "user_id", "pid_namespace_device", "pid_namespace_inode"))):
            raise ValueError("history restart native leader must change within the same namespace")
        attached, stop = result["attach"], new["fixed_product_stop"]
        if type(stop) is not dict or set(stop) != {"started_at", "observed_at", "local_owner_settled_at", "service_id", "result"}:
            raise ValueError("history restart stop inventory mismatch")
        validate_managed_history_timings(attached, attach_started_at=new["spawns"][1]["start"],
            restored={key: result[key] for key in ("action", "restored_history_frame_seconds")},
            service_started_at=new["spawns"][0]["start"], authenticated_at=new["authenticated_at"])
        validate_managed_history_confirmation(attached["detached"], target, identity=prior["seed"]["history_identity"],
                                              earliest=terminals[1]["settled_at"], latest=stop["started_at"])
        if (attached["actions"]["history_completion"]["finished_at"] > terminals[1]["termios_restored_at"]
                or stop["service_id"] != target["serviceId"]
                or stop["result"] != {"status": "stopped", "instanceId": target["instanceId"]}
                or result["stop"] != stop["result"]
                or not all(timestamp(stop[key]) for key in ("started_at", "observed_at", "local_owner_settled_at"))
                or not attached["detached"]["connection_settled_at"] <= stop["started_at"] <= stop["observed_at"] <= stop["local_owner_settled_at"]):
            raise ValueError("history restart exact stop or final terminal mismatch")
        validate_managed_history_canonical(result["canonical_read"], root=workspace / "platform/data/sessions",
            workspace=workspace, identity=prior["seed"]["history_identity"], owner_settled_at=stop["local_owner_settled_at"],
            next_started_at=latest)
        if result["canonical"] != prior["canonical"] or result["canonical"] != result["canonical_read"]["canonical"]:
            raise ValueError("history restart canonical changed")
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError("history restart evidence malformed") from error
    return {"restored_history_frame_seconds": result["restored_history_frame_seconds"]}


def validate_managed_history_warm(child, *, prefix, workspace, earliest, latest):
    """Join warm-generation proofs; outer provenance/promotion remain separate."""
    fields = HISTORY_WARM_FIELDS
    if (type(child) is not dict or set(child) != fields or child["status"] != "observed"
            or child["valid"] is not False or child["measured_prefix"] != str(prefix)):
        raise ValueError("history warm generation inventory or status mismatch")

    def timestamp(item):
        return (type(item) in (int, float) and 0 <= item <= sys.float_info.max
                and math.isfinite(item))

    try:
        target, result, stop = child["fixed_product_target"], child["fixed_product_history"], child["fixed_product_stop"]
        if (type(result) is not dict or set(result) != {"seed", "attach", "canonical", "stop", "canonical_read"}
                or type(stop) is not dict or set(stop) != {
                    "started_at", "observed_at", "local_owner_settled_at", "service_id", "result"}
                or type(target) is not dict):
            raise ValueError("history warm result inventory mismatch")
        terminals = validate_managed_history_terminals(child, prefix=prefix, workspace=workspace,
            restored=False, earliest=earliest, latest=latest)
        attached, seed = result["attach"], result["seed"]
        observation_fields = {"stage", "observed_at", "instanceId", "serviceId", "muxId", "members"}
        if (type(seed) is not dict or set(seed) != observation_fields | {
                "history_seed", "history_identity", "connection_settled_at", "verification"}):
            raise ValueError("history warm seed observation inventory mismatch")
        validate_managed_history_timings(attached, attach_started_at=child["spawns"][1]["start"])
        validate_managed_history_seed(seed["history_seed"], terminal_settled_at=terminals[0]["settled_at"],
            connection_settled_at=seed["connection_settled_at"], attach_started_at=child["spawns"][1]["start"],
            verification=seed["verification"])
        validate_managed_history_confirmation(attached["detached"], target, identity=seed["history_identity"],
            earliest=terminals[1]["settled_at"], latest=stop["started_at"])
        if (not timestamp(target["observed_at"])
                or not child["spawns"][0]["start"] <= target["observed_at"] <= terminals[0]["termios_restored_at"]
                or attached["actions"]["history_completion"]["finished_at"] > terminals[1]["termios_restored_at"]):
            raise ValueError("history warm frame or authentication outside terminal")
        detached = child["fixed_product_detached"]
        if type(detached) is not dict or set(detached) != observation_fields:
            raise ValueError("history warm detached observation inventory mismatch")
        for observation, before, after in (
            (seed, terminals[0]["settled_at"], seed["verification"]["started_at"]),
            (detached, seed["connection_settled_at"], child["spawns"][1]["start"]),
        ):
            if (observation["stage"] != "detached" or not timestamp(observation["observed_at"])
                    or not before <= observation["observed_at"] <= after
                    or any(observation[key] != target[key] for key in ("instanceId", "serviceId", "muxId", "members"))):
                raise ValueError("history warm authenticated observation mismatch")
        validate_managed_history_native(child["fixed_product_native"], first="first-member",
            stages={"first-member", "detached", "history-detached", "stop"})
        if (stop["service_id"] != target["serviceId"]
                or stop["result"] != {"status": "stopped", "instanceId": target["instanceId"]}
                or result["stop"] != stop["result"]
                or not all(timestamp(stop[key]) for key in ("started_at", "observed_at", "local_owner_settled_at"))
                or not attached["detached"]["connection_settled_at"] <= stop["started_at"] <= stop["observed_at"] <= stop["local_owner_settled_at"]):
            raise ValueError("history warm exact stop or settlement mismatch")
        validate_managed_history_canonical(result["canonical_read"], root=workspace / "platform/data/sessions",
            workspace=workspace, identity=seed["history_identity"], owner_settled_at=stop["local_owner_settled_at"],
            next_started_at=latest)
        if result["canonical"] != result["canonical_read"]["canonical"]:
            raise ValueError("history warm duplicated canonical evidence disagrees")
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError("history warm generation evidence malformed") from error
    return {name: attached[name] for name in ("history_frame_seconds", "history_completion_seconds")}


def validate_managed_history_confirmation(value, target, *, identity, earliest, latest):
    """Bind the exact bounded tail to the authenticated Session after detach.

    The frozen digest is for 1 omitted STATUS plus rounds 121..127 (14 messages),
    not the full 256-message canonical transcript validated separately.
    """
    fields = {"stage", "observed_at", "instanceId", "serviceId", "muxId", "members"}
    if (type(value) is not dict or set(value) != fields | {"history_snapshot", "connection_settled_at"}
            or type(target) is not dict or set(target) != fields
            or value["stage"] != "detached" or target["stage"] != "first-member"
            or any(value[key] != target[key] for key in ("instanceId", "serviceId", "muxId", "members"))):
        raise ValueError("history confirmation target mismatch")
    token = r"[A-Za-z0-9][A-Za-z0-9._~-]{0,511}"
    for key, pattern in (("instanceId", r"[0-9a-f]{32}"), ("serviceId", r"[0-9a-f]{64}"), ("muxId", token)):
        if type(target[key]) is not str or re.fullmatch(pattern, target[key]) is None:
            raise ValueError("history confirmation service identity invalid")
    members = target["members"]
    if (type(members) is not list or len(members) != 1 or type(members[0]) is not dict
            or set(members[0]) != {"memberId", "sessionId"}
            or any(type(item) is not str or re.fullmatch(token, item) is None for item in members[0].values())):
        raise ValueError("history confirmation membership invalid")
    if (type(identity) is not dict or set(identity) != {
            "product_id", "continuity_id", "session_id", "scope", "scope_fingerprint"}
            or any(type(item) is not str for item in identity.values())
            or identity["product_id"] != "coding" or identity["scope"] != "user_home"
            or identity["session_id"] != members[0]["sessionId"]
            or re.fullmatch(token, identity["continuity_id"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", identity["scope_fingerprint"]) is None):
        raise ValueError("history confirmation Session identity invalid")
    snapshot = value["history_snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != {"confirmed_at", "identity", "running", "records"}
            or type(snapshot["identity"]) is not dict or snapshot["identity"] != identity
            or snapshot["running"] is not False):
        raise ValueError("history confirmation snapshot identity or idle mismatch")
    times = (target["observed_at"], earliest, value["observed_at"], snapshot["confirmed_at"],
             value["connection_settled_at"], latest)
    if (any(type(item) not in (int, float) or item < 0 or item > sys.float_info.max
            or not math.isfinite(item) for item in times)
            or any(left > right for left, right in zip(times, times[1:]))):
        raise ValueError("history confirmation snapshot or connection order mismatch")
    rows = snapshot["records"]
    if (type(rows) is not list or len(rows) != 15
            or any(type(row) is not dict or set(row) != {"kind", "text"}
                   or type(row["text"]) is not str or type(row["kind"]) is not str
                   or row["kind"] != ("status" if index == 0 else "user" if index % 2 else "assistant")
                   for index, row in enumerate(rows))):
        raise ValueError("history confirmation requires the exact 15-record tail")
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    if digest != "327b38a5d29980cf550d442423e65e999ce4ca8abc9695ed6f80150a3740ea49":
        raise ValueError("history confirmation differs from the fixed bounded tail")


def validate_managed_history_terminals(child, *, prefix, workspace, restored,
                                       earliest, latest):
    """Validate each real history foreground, without inventing TUI line modes.

    Bounds belong to the enclosing original owner. Authentication, service stop
    and history content are separate checks. Return receipts in spawn order.
    """
    def timestamp(item):
        return (type(item) in (int, float) and 0 <= item <= sys.float_info.max
                and math.isfinite(item))

    if (type(restored) is not bool or type(child) is not dict
            or not timestamp(earliest) or not timestamp(latest) or earliest > latest):
        raise ValueError("history foreground bounds invalid")
    spawns, tui = child.get("spawns"), child.get("terminal_settlements")
    line = child.get("line_terminal_settlements", [])
    if (type(spawns) is not list or len(spawns) != 2
            or type(tui) is not list or len(tui) != (1 if restored else 2)
            or type(line) is not list or len(line) != (1 if restored else 0)):
        raise ValueError("history foreground inventory mismatch")
    terminals = [line[0], tui[0]] if restored else tui
    previous = earliest
    for index, (spawn, terminal) in enumerate(zip(spawns, terminals, strict=True)):
        is_line = restored and index == 0
        cwd = workspace if index == 0 else workspace / ("restored-elsewhere" if restored else "elsewhere")
        argv = ([str(prefix / "bin/python"), "-I", str(inert.ROOT / "tests/coding/_lmux_product_entry.py"),
                 "start", "-t", "perf"] if is_line else
                [str(prefix / "bin/python"), "-I", str(inert.ROOT / "tests/coding/_lmux_product_entry.py"),
                 "new", "-s", "perf"] if index == 0 else
                [str(prefix / "bin/lmux"), "attach", "-t", "perf"])
        fields = {"pid", "argv", "cwd", "exit_status", "termios_restored_at", "settled_at", "reader_settled", "fallback"}
        fields |= {"presentation"} if is_line else {"cursor_restored", "bracketed_paste_disabled"}
        if (type(spawn) is not dict or set(spawn) != {"pid", "start", "argv", "cwd"}
                or type(spawn["pid"]) is not int or not 0 < spawn["pid"] < 2**31
                or spawn["argv"] != argv or spawn["cwd"] != str(cwd) or not timestamp(spawn["start"])
                or type(terminal) is not dict or set(terminal) != fields
                or type(terminal["pid"]) is not int or terminal["pid"] != spawn["pid"]
                or terminal["argv"] != argv or terminal["cwd"] != str(cwd)
                or type(terminal["exit_status"]) is not int or terminal["exit_status"] != 0
                or terminal["reader_settled"] is not True or terminal["fallback"] is not False
                or (terminal["presentation"] != "line" if is_line else
                    terminal["cursor_restored"] is not True or terminal["bracketed_paste_disabled"] is not True)
                or not timestamp(terminal["termios_restored_at"]) or not timestamp(terminal["settled_at"])
                or not previous <= spawn["start"] <= terminal["termios_restored_at"] <= terminal["settled_at"] <= latest):
            raise ValueError("history foreground identity or settlement mismatch")
        previous = terminal["settled_at"]
    return terminals


def validate_managed_history_seed(value, *, terminal_settled_at,
                                  connection_settled_at, attach_started_at, verification):
    """Require the complete bounded seed before a measured warm attachment.

    External terminal/connection/spawn bounds are validated by the enclosing
    lifecycle check. This does not substitute for snapshots or persisted text.
    """
    def timestamp(item):
        return (type(item) in (int, float) and 0 <= item <= sys.float_info.max
                and math.isfinite(item))

    if type(value) is not dict or set(value) != {"started_at", "finished_at", "rounds", "detached_at", "attachment"}:
        raise ValueError("history seed inventory mismatch")
    attachment = value["attachment"]
    if (type(verification) is not dict or set(verification) != {"started_at", "deadline", "completed_at"}
            or not all(timestamp(item) for item in verification.values())
            or verification["deadline"] != verification["started_at"] + 660
            or not verification["started_at"] <= verification["completed_at"] < verification["deadline"]):
        raise ValueError("history verification admission deadline mismatch")
    if (type(attachment) is not dict or set(attachment) != {
            "deadline", "attach_started_at", "attach_deadline", "attached_at",
            "detach_started_at", "detach_deadline"}
            or not all(timestamp(item) for item in attachment.values())
            or not all(timestamp(value[key]) for key in ("started_at", "finished_at", "detached_at"))
            or not timestamp(terminal_settled_at)
            or attachment["deadline"] != verification["deadline"]
            or not terminal_settled_at <= verification["started_at"] <= attachment["attach_started_at"] <= attachment["attached_at"]
            <= value["started_at"] <= value["finished_at"] <= attachment["detach_started_at"] <= value["detached_at"]
            or attachment["attach_deadline"] != min(attachment["deadline"], attachment["attach_started_at"] + 30)
            or attachment["detach_deadline"] != min(attachment["deadline"], attachment["detach_started_at"] + 30)
            or attachment["attached_at"] >= attachment["attach_deadline"]
            or value["detached_at"] >= attachment["detach_deadline"]
            or value["finished_at"] >= attachment["deadline"] - 30):
        raise ValueError("history attachment dispatch or deadline mismatch")
    times = (terminal_settled_at, value["started_at"], value["finished_at"],
             value["detached_at"], verification["completed_at"], connection_settled_at, attach_started_at)
    if (not all(timestamp(item) for item in times)
            or any(left > right for left, right in zip(times, times[1:]))
            or value["finished_at"] - value["started_at"] >= 600):
        raise ValueError("history seed must finish and release owners before attach")
    rounds = value["rounds"]
    if type(rounds) is not list or len(rounds) != 128:
        raise ValueError("history seed requires all 128 rounds")
    previous = value["started_at"]
    for index, row in enumerate(rounds):
        if (type(row) is not dict or set(row) != {
                "round", "started_at", "acknowledged_at", "settled_at", "snapshot_reads"}
                or type(row["round"]) is not int or row["round"] != index
                or type(row["snapshot_reads"]) is not int or not 1 <= row["snapshot_reads"] <= 80):
            raise ValueError("history seed round inventory mismatch")
        interval = (previous, row["started_at"], row["acknowledged_at"], row["settled_at"],
                    value["finished_at"])
        if (not all(timestamp(item) for item in interval)
                or any(left > right for left, right in zip(interval, interval[1:]))
                or row["settled_at"] - row["started_at"] >= 40):
            raise ValueError("history seed round order or deadline mismatch")
        previous = row["settled_at"]


def validate_managed_history_canonical(value, *, root, workspace, identity,
                                       owner_settled_at, next_started_at):
    """Check the read receipt independently; this alone never accepts a sample.

    Bounds must come from the original generation/outer owner, not from this
    receipt. Paths bind the actual public read inputs, not native file identity.
    """
    fields = {"started_at", "completed_at", "root", "path", "workspace", "identity", "canonical"}
    identity_fields = {"product_id", "continuity_id", "session_id", "scope", "scope_fingerprint"}
    expected = {"recipe": "lmux-history-128x2048/v1", "rounds": 128,
                "records": 256, "text_bytes": 263680,
                "sha256": "00e1c01bb0a4603b94f5fbd70ea802f24a9389471893e5883310ba7c0c0fbb41"}
    if (type(value) is not dict or set(value) != fields
            or type(identity) is not dict or set(identity) != identity_fields
            or any(type(item) is not str or not item for item in identity.values())
            or identity["product_id"] != "coding"
            or identity["scope"] not in {"cwd", "user_home"}
            or type(value["identity"]) is not dict or value["identity"] != identity):
        raise ValueError("history canonical identity or inventory mismatch")
    session = identity["session_id"]
    if ("/" in session or "\\" in session or "\x00" in session
            or value["root"] != str(root) or value["workspace"] != str(workspace)
            or value["path"] != str(Path(root) / f"hosted-{session}.jsonl")):
        raise ValueError("history canonical read selection mismatch")
    canonical = value["canonical"]
    if (type(canonical) is not dict or canonical != expected
            or any(type(canonical[key]) is not type(item) for key, item in expected.items())):
        raise ValueError("history canonical recipe mismatch")
    times = (owner_settled_at, value["started_at"], value["completed_at"], next_started_at)
    if (any(type(item) not in (int, float) or item < 0 or item > sys.float_info.max
            or not math.isfinite(item) for item in times)
            or any(left > right for left, right in zip(times, times[1:]))):
        raise ValueError("history canonical owner/read ordering mismatch")


def validate_managed_history_timings(attached, *, attach_started_at, restored=None,
                                     service_started_at=None, authenticated_at=None):
    """Bind history durations to real spawn endpoints, including restart gaps.

    The caller must independently validate those spawn/authentication receipts,
    frames and owners. This only verifies the reviewed timing subset.
    """
    if type(attached) is not dict or set(attached) != {
        "actions", "history_frame_seconds", "history_completion_seconds", "detached",
    }:
        raise ValueError("history attach timing inventory mismatch")
    actions = attached["actions"]
    validate_managed_product_timings(actions, {
        name + "_seconds": attached[name + "_seconds"]
        for name in ("history_frame", "history_completion")
    }, "history")
    frame = actions["history_frame"]
    if (type(attach_started_at) not in (int, float)
            or attach_started_at != frame["started_at"]):
        raise ValueError("history frame must start at actual attach spawn")
    if restored is None:
        if service_started_at is not None or authenticated_at is not None:
            raise ValueError("warm history must not carry restart timing inputs")
        return
    if type(restored) is not dict or set(restored) != {"action", "restored_history_frame_seconds"}:
        raise ValueError("restored history timing inventory mismatch")
    action, duration = restored["action"], restored["restored_history_frame_seconds"]
    if type(action) is not dict or set(action) != {"started_at", "finished_at"}:
        raise ValueError("restored history action inventory mismatch")
    times = (service_started_at, authenticated_at, attach_started_at, frame["finished_at"],
             action["started_at"], action["finished_at"], duration)
    if (any(type(item) not in (int, float) or item < 0 or item > sys.float_info.max
            or not math.isfinite(item) for item in times)
            or not service_started_at <= authenticated_at <= attach_started_at
            or action["started_at"] != service_started_at
            or action["finished_at"] != frame["finished_at"]
            or duration != frame["finished_at"] - service_started_at):
        raise ValueError("restored history must include actual startup and authentication gap")


def validate_managed_product_timings(actions, milestones, scenario):
    """Validate only the reviewed timing subset, never whole-sample validity.

    Identity, terminal, snapshot, stop and outer-owner proofs are separate
    requirements. This does not promote diagnostic receipts to accepted samples.
    """
    inventories = {
        "reply": ("fixed_entry_through_visible_reply", "visible_reply"),
        "approval": ("approval_pending", "approval_details", "approved_tool_reply"),
        "interrupt": ("interrupt_through_idle_and_producer", "next_reply",
                      "interrupt_through_next_reply"),
        "history": ("history_frame", "history_completion"),
    }
    if type(scenario) is not str or scenario not in inventories:
        raise ValueError("unknown managed Product timing scenario")
    names = inventories[scenario]
    if (type(actions) is not dict or set(actions) != set(names)
            or type(milestones) is not dict
            or set(milestones) != {name + "_seconds" for name in names}):
        raise ValueError("managed Product timing inventory mismatch")
    for name in names:
        action, duration = actions[name], milestones[name + "_seconds"]
        if (type(action) is not dict or set(action) != {"started_at", "finished_at"}
                or any(type(item) not in (int, float) or item < 0
                       or item > sys.float_info.max or not math.isfinite(item)
                       for item in (*action.values(), duration))
                or action["finished_at"] < action["started_at"]
                or duration != action["finished_at"] - action["started_at"]):
            raise ValueError("managed Product action duration mismatch")
    intervals = [actions[name] for name in names]
    if scenario == "reply":
        cumulative, reply = intervals
        ordered = (cumulative["started_at"] <= reply["started_at"]
                   and cumulative["finished_at"] == reply["finished_at"])
    elif scenario in {"approval", "history"}:
        ordered = all(left["finished_at"] <= right["started_at"]
                      for left, right in zip(intervals, intervals[1:]))
    else:
        interrupted, reply, cumulative = intervals
        ordered = (interrupted["finished_at"] <= reply["started_at"]
                   and cumulative["started_at"] == interrupted["started_at"]
                   and cumulative["finished_at"] == reply["finished_at"])
    if not ordered:
        raise ValueError("managed Product action order or shared endpoint mismatch")


def validate_managed_product_terminals(child, scenario, *, prefix, workspace, instance, service):
    """Bind every normal foreground lifetime to its spawn and exact stop.

    The caller still owes authenticated identity/snapshot/effect validation and
    original outer-process settlement. A local stop is not outer settlement.
    """
    def timestamp(value):
        return (type(value) in (int, float) and 0 <= value <= sys.float_info.max
                and math.isfinite(value))

    if (scenario not in ("reply", "approval", "interrupt") or type(child) is not dict
            or child.get("status") != "observed" or child.get("valid") is not False
            or any(key in child for key in ("failure", "fixed_product_cleanup_failure",
                                           "diagnostic_instrumentation", "terminal_transport"))
            or child.get("measured_prefix") != str(prefix)
            or child.get("workspace") != str(workspace)
            or not timestamp(child.get("started_at")) or not timestamp(child.get("finished_at"))):
        raise ValueError("managed Product terminal scenario invalid")
    if (type(instance) is not str or re.fullmatch(r"[0-9a-f]{32}", instance) is None
            or type(service) is not str or re.fullmatch(r"[0-9a-f]{64}", service) is None):
        raise ValueError("managed Product stop identity invalid")
    spawns, terminals = child.get("spawns"), child.get("terminal_settlements")
    count = 2 if scenario == "interrupt" else 1
    if type(spawns) is not list or type(terminals) is not list or len(spawns) != count or len(terminals) != count:
        raise ValueError("managed Product terminal inventory mismatch")
    previous = child["started_at"]
    for index, (spawn, terminal) in enumerate(zip(spawns, terminals, strict=True)):
        cwd = workspace if index == 0 else workspace / "elsewhere"
        argv = ([str(prefix / "bin/python"), "-I",
                 str(inert.ROOT / "tests/coding/_lmux_product_entry.py"), "new", "-s", "perf"]
                if index == 0 else [str(prefix / "bin/lmux"), "attach", "-t", "perf"])
        if (type(spawn) is not dict or set(spawn) != {"pid", "start", "argv", "cwd"}
                or type(spawn["pid"]) is not int or spawn["pid"] <= 0
                or not timestamp(spawn["start"]) or spawn["argv"] != argv or spawn["cwd"] != str(cwd)
                or type(terminal) is not dict or set(terminal) != {
                    "pid", "argv", "cwd", "exit_status", "termios_restored_at", "settled_at",
                    "cursor_restored", "bracketed_paste_disabled", "reader_settled", "fallback"}
                or type(terminal["pid"]) is not int or terminal["pid"] != spawn["pid"]
                or terminal["argv"] != argv or terminal["cwd"] != str(cwd)
                or type(terminal["exit_status"]) is not int or terminal["exit_status"] != 0
                or any(terminal[key] is not True for key in (
                    "cursor_restored", "bracketed_paste_disabled", "reader_settled"))
                or terminal["fallback"] is not False
                or not timestamp(terminal["termios_restored_at"]) or not timestamp(terminal["settled_at"])
                or not previous <= spawn["start"] <= terminal["termios_restored_at"] <= terminal["settled_at"]):
            raise ValueError("managed Product foreground identity or settlement mismatch")
        previous = terminal["settled_at"]
    stop = child.get("fixed_product_stop")
    if (type(stop) is not dict or set(stop) != {
            "started_at", "observed_at", "local_owner_settled_at", "service_id", "result"}
            or stop["service_id"] != service
            or stop["result"] != {"status": "stopped", "instanceId": instance}
            or not all(timestamp(stop[key]) for key in (
                "started_at", "observed_at", "local_owner_settled_at"))
            or not previous <= stop["started_at"] <= stop["observed_at"]
            <= stop["local_owner_settled_at"] <= child["finished_at"]):
        raise ValueError("managed Product stop order or identity mismatch")


def validate_managed_product_confirmation(value, target, *, expected_reply, records, earliest, latest, pending=False):
    """Bind a post-detach snapshot to the original target and expected records.

    This validates trusted observer values, not a new authentication channel.
    Source/installation provenance and outer cleanup remain caller obligations.
    """
    def timestamp(item):
        return (type(item) in (int, float) and 0 <= item <= sys.float_info.max
                and math.isfinite(item))

    fields = {"stage", "observed_at", "instanceId", "serviceId", "muxId", "members"}
    flag = "pendingConfirmed" if pending else "replyConfirmed"
    if (type(pending) is not bool or type(value) is not dict or set(value) != fields | {flag, "snapshot"}
            or type(target) is not dict or set(target) != fields
            or target["stage"] != "first-member" or value["stage"] != "detached"
            or value[flag] is not True or not all(timestamp(item) for item in (
                earliest, latest, target["observed_at"], value["observed_at"]))
            or not target["observed_at"] <= earliest <= value["observed_at"] <= latest
            or any(value[key] != target[key] for key in ("instanceId", "serviceId", "muxId", "members"))):
        raise ValueError("managed Product confirmation target or order mismatch")
    for name, pattern in (("instanceId", r"[0-9a-f]{32}"), ("serviceId", r"[0-9a-f]{64}"),
                          ("muxId", r"[A-Za-z0-9][A-Za-z0-9._~-]{0,511}")):
        if type(target[name]) is not str or re.fullmatch(pattern, target[name]) is None:
            raise ValueError("managed Product original identity invalid")
    members = target["members"]
    if (type(members) is not list or len(members) != 1 or type(members[0]) is not dict
            or set(members[0]) != {"memberId", "sessionId"}
            or any(type(item) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,511}", item) is None
                   for item in members[0].values())):
        raise ValueError("managed Product member identity invalid")
    snapshot = value["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != {"confirmed_at", "running", "expected_reply", "identity", "records"}
            or snapshot["running"] is not pending or snapshot["expected_reply"] != expected_reply
            or snapshot["records"] != records or type(snapshot["records"]) is not list
            or not timestamp(snapshot["confirmed_at"])
            or not value["observed_at"] <= snapshot["confirmed_at"] <= latest):
        raise ValueError("managed Product snapshot records or order mismatch")
    identity = snapshot["identity"]
    if (type(identity) is not dict or set(identity) != {
            "product_id", "continuity_id", "session_id", "scope", "scope_fingerprint"}
            or identity["product_id"] != "coding" or identity["scope"] != "user_home"
            or identity["session_id"] != members[0]["sessionId"]
            or type(identity["continuity_id"]) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,511}", identity["continuity_id"]) is None
            or type(identity["scope_fingerprint"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", identity["scope_fingerprint"]) is None):
        raise ValueError("managed Product snapshot scope identity mismatch")


def validate_managed_product_scenario(child, scenario, *, prefix, workspace):
    """Combine timing, foreground, original-target and final-record checks.

    The outer collector must still validate all three fresh scenarios, frozen
    inputs and its original evidence owner's physical settlement.
    """
    result_keys = {"reply": "fixed_product_first_reply", "approval": "fixed_product_tool_approval",
                   "interrupt": "fixed_product_interrupt_next_turn"}
    if type(scenario) is not str or scenario not in result_keys:
        raise ValueError("unknown managed Product scenario")
    fields = {"measured_prefix", "workspace", "status", "valid", "spawns", "started_at", "finished_at",
              "terminal_settlements", "fixed_product_stop", "fixed_product_target", "fixed_product_detached",
              "actions", "milestones", "fixed_product_native", result_keys[scenario]}
    if type(child) is not dict or set(child) != fields:
        raise ValueError("managed Product scenario field inventory mismatch")
    natives = child["fixed_product_native"]
    stages = {"first-member", "detached", "stop"} | ({"reattached", "final-detached"} if scenario == "interrupt" else set())
    if type(natives) is not dict or set(natives) != stages:
        raise ValueError("managed Product native identity stages missing")
    native = natives["first-member"]
    if (type(native) is not dict or set(native) != {
            "pid", "start_ticks", "boot_id", "user_id", "pid_namespace_device", "pid_namespace_inode"}
            or type(native["pid"]) is not int or not 1 <= native["pid"] < 2**31
            or type(native["boot_id"]) is not str
            or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", native["boot_id"]) is None
            or any(type(native[key]) is not int or not 0 <= native[key] < 2**64
                   for key in ("start_ticks", "user_id", "pid_namespace_device", "pid_namespace_inode"))
            or native["pid_namespace_inode"] == 0
            or any(type(item) is not dict or item != native
                   or any(type(item[key]) is not type(native[key]) for key in native)
                   for item in natives.values())):
        raise ValueError("managed Product native identity differs or is malformed")
    try:
        target, result = child["fixed_product_target"], child[result_keys[scenario]]
        if type(target) is not dict or type(result) is not dict:
            raise ValueError("managed Product result or target invalid")
        validate_managed_product_timings(child["actions"], child["milestones"], scenario)
        validate_managed_product_terminals(child, scenario, prefix=prefix, workspace=workspace,
                                          instance=target.get("instanceId"), service=target.get("serviceId"))
        actions, terminals, stop = child["actions"], child["terminal_settlements"], child["fixed_product_stop"]
        timing = result["next_turn"] if scenario == "interrupt" else result
        duration_keys = {"spawn_through_visible_reply_seconds" if name == "fixed_entry_through_visible_reply_seconds" else name
                         for name in child["milestones"]}
        expected_result = (
            duration_keys | {"actions", "request_nonce", "confirmation", "stop", "composition"}
            if scenario == "reply" else duration_keys | {"actions", "approved_sent_ns", "confirmation", "stop",
                "tool_call_id", "tool_execution_count", "tool_effects"}
            if scenario == "approval" else {"request_nonce", "pending_confirmation", "stop", "producer",
                "producer_settled", "full_text_not_completed", "next_turn"}
        )
        if set(result) != expected_result:
            raise ValueError("managed Product raw result inventory mismatch")
        if scenario == "interrupt" and (type(timing) is not dict or set(timing) != duration_keys | {
                "actions", "next_reply_confirmation", "interrupted_nonce", "next_nonce", "interrupt_sent_ns",
                "producer_before", "producer_after", "reattached", "detached"}):
            raise ValueError("managed Product next-turn inventory mismatch")
        if timing["actions"] != actions or result["stop"] != stop["result"]:
            raise ValueError("managed Product duplicated evidence disagrees")
        for name, duration in child["milestones"].items():
            key = "spawn_through_visible_reply_seconds" if name == "fixed_entry_through_visible_reply_seconds" else name
            if type(timing[key]) not in (int, float) or timing[key] != duration:
                raise ValueError("managed Product raw duration disagrees")

        def observation(value, stage, earliest, latest):
            if (type(value) is not dict or set(value) != {"stage", "observed_at", "instanceId", "serviceId", "muxId", "members"}
                    or value["stage"] != stage or type(value["observed_at"]) not in (int, float)
                    or not earliest <= value["observed_at"] <= latest
                    or any(value[key] != target[key] for key in ("instanceId", "serviceId", "muxId", "members"))):
                raise ValueError("managed Product authenticated observation mismatch")

        def nonce(value):
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None:
                raise ValueError("managed Product request nonce invalid")
            return value

        def confirm(value, expected, records, terminal_index, latest, *, pending=False):
            validate_managed_product_confirmation(value, target, expected_reply=expected, records=records,
                earliest=terminals[terminal_index]["settled_at"], latest=latest, pending=pending)

        def record(kind, text):
            return {"kind": kind, "text": text}

        def trace(rows, phases):
            if type(rows) is not list or len(rows) != len(phases):
                raise ValueError("managed Product trace inventory mismatch")
            previous = -1
            for row, phase in zip(rows, phases, strict=True):
                keys = {"instance_id", "call_id", "monotonic_ns", "sequence"} | ({"phase"} if phase else set())
                if (type(row) is not dict or set(row) != keys or row["instance_id"] != target["instanceId"]
                        or row["call_id"] != "lmux-call-1" or (phase and row["phase"] != phase)
                        or type(row["sequence"]) is not int or not previous < row["sequence"]
                        or type(row["monotonic_ns"]) is not int or not 0 <= row["monotonic_ns"] < 2**64):
                    raise ValueError("managed Product original trace invalid")
                previous = row["sequence"]

        first_action = actions["visible_reply"] if scenario == "reply" else actions[
            "approval_pending" if scenario == "approval" else "interrupt_through_idle_and_producer"]
        last_action = actions["visible_reply" if scenario == "reply" else "approved_tool_reply" if scenario == "approval" else "next_reply"]
        observation(target, "first-member", child["spawns"][0]["start"], first_action["started_at"])
        if last_action["finished_at"] > terminals[-1]["termios_restored_at"]:
            raise ValueError("managed Product completion follows terminal restoration")
        if scenario == "reply":
            request = nonce(result["request_nonce"])
            expected = "LMUX_REPLY_" + request
            if (result["composition"] != "managed-infrastructure-with-fixed-test-product"
                    or actions["fixed_entry_through_visible_reply"]["started_at"] != child["spawns"][0]["start"]):
                raise ValueError("managed Product fixed-entry start mismatch")
            confirm(result["confirmation"], expected, [record("user", "reply " + request), record("assistant", expected)], 0, stop["started_at"])
        elif scenario == "approval":
            expected = "LMUX_TOOL_COMPLETED"
            confirm(result["confirmation"], expected, [record("user", "approval"), record("assistant", ""), record("assistant", expected)], 0, stop["started_at"])
            if type(result["tool_execution_count"]) is not int or result["tool_execution_count"] != 1 or result["tool_call_id"] != "lmux-call-1":
                raise ValueError("managed Product tool effect count invalid")
            trace(result["tool_effects"], [None])
            approved = result["approved_sent_ns"]
            if (type(approved) is not int or not actions["approved_tool_reply"]["started_at"]
                    <= approved / 1e9 <= result["tool_effects"][0]["monotonic_ns"] / 1e9 <= last_action["finished_at"]):
                raise ValueError("managed Product tool effect predates approval or follows completion")
        else:
            request, following = nonce(result["request_nonce"]), nonce(timing["next_nonce"])
            if (timing["interrupted_nonce"] != request or following == request or result["producer"] != "lmux-call-1"
                    or result["producer_settled"] is not True or result["full_text_not_completed"] is not True):
                raise ValueError("managed Product interrupted request identity invalid")
            before_reply = "LMUX_REPLY_" + request
            confirm(result["pending_confirmation"], before_reply, [record("user", "delayed " + request)], 0, child["spawns"][1]["start"], pending=True)
            observation(timing["reattached"], "reattached", child["spawns"][1]["start"], first_action["started_at"])
            trace(timing["producer_before"], ["producer_started"])
            trace(timing["producer_after"], ["producer_started", "producer_settled"])
            sent = timing["interrupt_sent_ns"]
            if (timing["producer_before"][0] != timing["producer_after"][0] or type(sent) is not int
                    or not first_action["started_at"] <= sent / 1e9
                    <= timing["producer_after"][1]["monotonic_ns"] / 1e9 <= first_action["finished_at"]
                    or timing["producer_before"][0]["monotonic_ns"] > sent):
                raise ValueError("managed Product producer settlement order invalid")
            expected = "LMUX_REPLY_" + following
            confirm(timing["next_reply_confirmation"], expected, [record("user", "delayed " + request), record("assistant", ""),
                    record("user", "reply " + following), record("assistant", expected)], 1, stop["started_at"])
            if result["pending_confirmation"]["snapshot"]["identity"] != timing["next_reply_confirmation"]["snapshot"]["identity"]:
                raise ValueError("managed Product interrupt changed Session identity")
            observation(timing["detached"], "detached", timing["next_reply_confirmation"]["snapshot"]["confirmed_at"], stop["started_at"])
        confirmation = result["pending_confirmation"] if scenario == "interrupt" else result["confirmation"]
        observation(child["fixed_product_detached"], "detached", confirmation["snapshot"]["confirmed_at"],
                    child["spawns"][1]["start"] if scenario == "interrupt" else stop["started_at"])
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError("malformed managed Product scenario evidence") from error


def validate_managed_product_collection(value, prefix, root):
    """Validate all three fresh scenarios inside a settled original observer."""
    children, outer = value.get("fixed_product_scenarios"), value.get("outer_settlement")
    if (type(children) is not dict or set(children) != {"reply", "approval", "interrupt"}
            or type(outer) is not dict or set(outer) != {"started_at", "settled_at"}
            or any(type(item) not in (int, float) or not 0 <= item <= sys.float_info.max or not math.isfinite(item)
                   for item in outer.values())
            or not outer["started_at"] < outer["settled_at"]
            or value.get("status") != "observed" or value.get("valid") is not False
            or value.get("seed") != "empty" or value.get("seed_setup") != []):
        raise ValueError("managed Product collection inventory or outer settlement invalid")
    previous, milestones, spawns = outer["started_at"], {}, []
    instances, services, sessions = set(), set(), set()
    for scenario in ("reply", "approval", "interrupt"):
        child = children[scenario]
        validate_managed_product_scenario(child, scenario, prefix=prefix, workspace=root / "workspace" / scenario)
        if not previous <= child["started_at"] <= child["finished_at"] <= outer["settled_at"]:
            raise ValueError("managed Product fresh scenarios overlap or outlive observer")
        previous = child["finished_at"]
        target = child["fixed_product_target"]
        result = child[{"reply": "fixed_product_first_reply", "approval": "fixed_product_tool_approval",
                        "interrupt": "fixed_product_interrupt_next_turn"}[scenario]]
        confirmation = result["pending_confirmation"] if scenario == "interrupt" else result["confirmation"]
        identity = confirmation["snapshot"]["identity"]
        session = tuple(identity[key] for key in ("product_id", "continuity_id", "session_id", "scope", "scope_fingerprint"))
        if target["instanceId"] in instances or target["serviceId"] in services or session in sessions:
            raise ValueError("managed Product scenarios did not use fresh service and Session identities")
        instances.add(target["instanceId"])
        services.add(target["serviceId"])
        sessions.add(session)
        if milestones.keys() & child["milestones"].keys():
            raise ValueError("managed Product scenario metrics overlap")
        milestones.update(child["milestones"])
        spawns.extend(child["spawns"])
    if type(value.get("milestones")) is not dict or value["milestones"] != milestones or value.get("spawns") != spawns:
        raise ValueError("managed Product summary differs from original child evidence")


def complete_managed_product(value, *, observer_started, owner_settled, prefix, root):
    """Call only after original owner.run_python succeeds; never set valid here."""
    if (type(value) is not dict or set(value) != OBSERVER_FIELDS | {"fixed_product_scenarios"}
            or value.get("case") != "managed-product-first-use" or value.get("schema_version") != 2
            or value.get("status") != "observed" or value.get("valid") is not False
            or value.get("measured_prefix") != str(prefix) or value.get("sample_id") != str(root.resolve())):
        raise ValueError("managed Product receipt cannot be completed")
    completed = {**value, "outer_settlement": {"started_at": observer_started, "settled_at": owner_settled}}
    validate_managed_product_collection(completed, prefix, root)
    return completed


def complete_managed_stop(value, *, observer_started, owner_settled):
    """Add the stop duration only after the original outer owner has settled.

    The trusted installed observer records the stop command's exact-instance
    success, not its own physical exit. The caller must invoke this only after
    owner.run_python returns successfully; this pure transform is not cleanup.
    Other provenance, frame and authenticated membership checks remain required.
    """
    if (
        type(value) is not dict
        or value.get("case") != "managed-mux"
        or value.get("status") != "observed"
        or value.get("valid") is not False
        or type(value.get("milestones")) is not dict
        or "stop_settlement_seconds" in value["milestones"]
    ):
        raise ValueError("managed stop must await outer settlement")
    stop = value.get("managed_stop")
    if (
        type(stop) is not dict
        or set(stop) != {"started_at", "result"}
        or type(stop["result"]) is not dict
        or set(stop["result"]) != {"status", "instanceId"}
        or stop["result"]["status"] != "stopped"
        or type(value.get("authenticated_instance_id")) is not str
        or re.fullmatch(r"[0-9a-f]{32}", value["authenticated_instance_id"]) is None
        or stop["result"]["instanceId"] != value["authenticated_instance_id"]
    ):
        raise ValueError("managed stop lacks exact authenticated instance success")
    times = (observer_started, stop["started_at"], owner_settled)
    if (
        any(type(item) not in (int, float) or not math.isfinite(item) or item <= 0 for item in times)
        or not observer_started <= stop["started_at"] < owner_settled
    ):
        raise ValueError("managed stop lies outside original observer lifetime")
    return {
        **value,
        "milestones": {
            **value["milestones"],
            "stop_settlement_seconds": owner_settled - stop["started_at"],
        },
    }


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
    if case in OPTIONAL_CASES:
        # mkdir(parents=True) applies mode only to the final workspace, not
        # its sample parent. Managed admission also checks ancestor modes.
        root.mkdir(mode=0o700, exist_ok=True)
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
        observer_started = time.perf_counter()
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
            # Three fresh scenarios retain existing inner deadlines.
            # History: original verification660 + 600 per generation for
            # serial terminal/auth/stop/read phases + 120 outer cleanup reserve.
            # No inner operation deadline is extended by this outer ceiling.
            timeout=(660 + 600 * (2 if case == HISTORY_CASES[1] else 1) + 120)
            if case in HISTORY_CASES
            else 3 * 240
            if case == "managed-product-first-use"
            else 360
            if case == "home-isolation"
            else 240
            if case.startswith("recovery-") or case in {"product-first-use", "managed-mux"}
            else 150,
        )
        owner_settled = time.perf_counter()
        observed = json.loads(receipt.read_text())
        if case == "managed-mux":
            observed = complete_managed_stop(
                observed, observer_started=observer_started, owner_settled=owner_settled,
            )
        elif case == "managed-product-first-use":
            observed = complete_managed_product(
                observed, observer_started=observer_started, owner_settled=owner_settled,
                prefix=prefix, root=root,
            )
        elif case in HISTORY_CASES:
            observed = complete_managed_history(
                observed, observer_started=observer_started, owner_settled=owner_settled,
                prefix=prefix, root=root,
            )
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
        if case == "managed-mux":
            for key in MANAGED_OBSERVER_FIELDS:
                attempt[key] = observed[key]
        elif case == "managed-product-first-use":
            for key in ("fixed_product_scenarios", "outer_settlement"):
                attempt[key] = observed[key]
        elif case in HISTORY_CASES:
            extras = HISTORY_WARM_FIELDS if case == HISTORY_CASES[0] else HISTORY_RESTORE_FIELDS
            for key in (extras - OBSERVER_FIELDS) | {"outer_settlement"}:
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
                *(["--failure-tree"] if report.get("seed_diagnostic") else []),
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

    if report.get("seed_diagnostic"):
        return  # The original seed/pins settled; final identity checks still run.

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
                        if case in OPTIONAL_CASES:
                            # Create the private ancestor before control's
                            # parents=True can apply the ambient umask to it.
                            root.mkdir(mode=0o700)
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
        "--seed-preparation-diagnostic",
        action="store_true",
        help="one warm A/A recovery-cwd seed preparation; no samples or comparison",
    )
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
    selection.add_argument("--cases", nargs="+", choices=(*CASES, *OPTIONAL_CASES), default=list(CASES))
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--pairs-per-block", type=int, default=10)
    args = parser.parse_args(argv)
    if args.seed_preparation_diagnostic and (
        not args.fixed_slot
        or args.cache_mode != "warm"
        or args.checkpoint
        or args.resume
        or args.pause_after is not None
    ):
        parser.error(
            "seed diagnostic requires warm fixed-slot without checkpoint/resume"
        )
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


def compare_selected_samples(args, samples, *, phase):
    """Select an existing frozen policy; partial diagnostics never pass."""
    if (
        args.fixed_slot and args.blocks == 2 and args.pairs_per_block == 10
        and (any(args.cases == [case] for case in OPTIONAL_CASES) or set(args.cases) == set(CASES))
    ):
        comparison = inert.comparison_module()
        if args.cases == ["managed-product-first-use"]:
            compare = comparison.compare_managed_product
        elif len(args.cases) == 1 and args.cases[0] in HISTORY_CASES:
            compare = partial(comparison.compare_managed_history, case=args.cases[0])
        else:
            compare = comparison.compare_managed if args.cases == ["managed-mux"] else comparison.compare_native
        return compare(samples, cache_mode=args.cache_mode, phase=phase,
                       blocks=args.blocks, pairs_per_block=args.pairs_per_block)
    return {
        "verdict": "not-evaluated",
        "reason": "requires all seven original cases or one explicit managed case, fixed-slot, and exactly two blocks of ten pairs",
    }


def collect_main(args, parser, campaign=None):
    if platform.system() != "Linux":
        parser.error("Linux native collection only")
    if (
        args.blocks < 1
        or args.pairs_per_block < 1
        or len(set(args.cases)) != len(args.cases)
    ):
        parser.error("positive counts and unique cases required")
    if set(OPTIONAL_CASES) & set(args.cases) and (
        len(args.cases) != 1 or args.home_isolation_only
        or args.seed_preparation_diagnostic or args.restored_recovery_preflight
    ):
        parser.error("managed cases require their own explicit native campaign")
    if args.home_isolation_only:
        args.cases, args.blocks, args.pairs_per_block = ["home-isolation"], 1, 1
    if args.seed_preparation_diagnostic:
        args.cases, args.blocks, args.pairs_per_block = ["recovery-cwd"], 1, 1
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
    if (
        args.restored_recovery_preflight or args.seed_preparation_diagnostic
    ) and mode != "aa":
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
    if args.seed_preparation_diagnostic:
        report.update(scope="linux-seed-startup-diagnostic", seed_diagnostic=True)
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
        report["comparison"] = compare_selected_samples(args, report["samples"], phase=mode)
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
