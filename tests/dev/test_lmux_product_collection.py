"""Three-child receipt aggregation, not a substitute for installed runs."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from .test_lmux_product_scenario import scenario_value
from .test_measure_g18_native import runner


def collection(tmp_path):
    children = {}
    for index, name in enumerate(("reply", "approval", "interrupt")):
        child, parameters = scenario_value(tmp_path / "workspace", name)
        replacements = {"a" * 32: str(index + 1) * 32, "b" * 64: str(index + 4) * 64,
                        "d" * 64: str(index + 7) * 64}

        def shift(value, key="", replacements=replacements, index=index):
            if isinstance(value, dict):
                return {key: shift(item, key) for key, item in value.items()}
            if isinstance(value, list):
                return [shift(item) for item in value]
            if isinstance(value, str):
                return replacements.get(value, value)
            if key.endswith("_at") or key == "start":
                return value + index * 20
            if key.endswith("_ns"):
                return value + index * 20_000_000_000
            return value

        shifted = shift(child)
        # Recompute from shifted endpoints just as the producer does; floating
        # subtraction at a new clock origin need not retain the old bit pattern.
        result = shifted[{"reply": "fixed_product_first_reply", "approval": "fixed_product_tool_approval",
                          "interrupt": "fixed_product_interrupt_next_turn"}[name]]
        timing = result["next_turn"] if name == "interrupt" else result
        shifted["milestones"] = {key + "_seconds": action["finished_at"] - action["started_at"]
                                 for key, action in shifted["actions"].items()}
        for key, duration in shifted["milestones"].items():
            timing["spawn_through_visible_reply_seconds" if key == "fixed_entry_through_visible_reply_seconds" else key] = duration
        children[name] = shifted
    prefix = parameters["prefix"]
    value = dict.fromkeys(runner.OBSERVER_FIELDS)
    value.update(schema_version=2, case="managed-product-first-use", status="observed", valid=False,
                 measured_prefix=str(prefix), sample_id=str(tmp_path.resolve()), seed="empty", seed_setup=[],
                 fixed_product_scenarios=children,
                 spawns=[spawn for child in children.values() for spawn in child["spawns"]],
                 milestones={key: item for child in children.values() for key, item in child["milestones"].items()})
    return value, dict(prefix=prefix, root=tmp_path, observer_started=0.5, owner_settled=60.0)


def test_collection_completion_keeps_original_and_does_not_promote_valid(tmp_path):
    value, parameters = collection(tmp_path)
    original = copy.deepcopy(value)
    completed = runner.complete_managed_product(value, **parameters)
    assert value == original
    assert completed["valid"] is False
    assert completed["outer_settlement"] == {"started_at": 0.5, "settled_at": 60.0}
    assert len(completed["spawns"]) == 4
    assert len(completed["milestones"]) == 8


@pytest.mark.parametrize("outcome", ["complete", "deferred", "failure", "cancel", "wrong-install"])
def test_original_owner_must_return_before_receipt_completion(tmp_path, monkeypatch, outcome):
    root = tmp_path / "sample"
    value, parameters = collection(root)
    prefix, observer = parameters["prefix"], tmp_path / "observer"
    value.update(observer_prefix=str(observer), observer_origin=str(observer / "lib/loushang/coding/__init__.py"))
    if outcome == "wrong-install":
        value["observer_prefix"] = str(tmp_path / "unrelated")
    failure = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("owner cleanup failed")
    events, clock = [], iter((0.5, 60.0))
    monkeypatch.setattr(runner, "time", SimpleNamespace(perf_counter=lambda: next(clock)))

    def supervise(argv, **kwargs):
        assert argv[4] == "managed-product-first-use"
        assert kwargs["timeout"] == 720
        runner.inert.write_report(root / "native.json", value)
        if outcome in {"failure", "cancel"}:
            raise failure  # Even a complete-looking file cannot override failure.
        events.append("owner-return")

    complete = runner.complete_managed_product

    def after_owner(*args, **kwargs):
        assert events == ["owner-return"]
        events.append("complete-receipt")
        return complete(*args, **kwargs)

    monkeypatch.setattr(runner.owner, "run_python", supervise)
    monkeypatch.setattr(runner, "complete_managed_product", after_owner)
    report, path = {"samples": []}, tmp_path / "report.json"

    def run():
        runner.run_sample(prefix, "managed-product-first-use", root, tmp_path / "pyc", report, path,
                          dict(side="a", block=0, pair=0), observer_prefix=observer,
                          defer_validation=outcome == "deferred")

    if outcome in {"failure", "cancel", "wrong-install"}:
        with pytest.raises(ValueError if outcome == "wrong-install" else type(failure)):
            run()
    else:
        run()
    (sample,) = json.loads(path.read_text())["samples"]
    assert sample["valid"] is (outcome == "complete")
    if outcome in {"failure", "cancel"}:
        assert events == []
        assert sample["status"] == "failed"
        assert "outer_settlement" not in sample
        assert sample["partial_observation"] == value
    elif outcome == "wrong-install":
        assert sample["status"] == "failed"
    else:
        assert sample["status"] == ("observed" if outcome == "deferred" else "complete")
        assert sample["fixed_product_scenarios"] == value["fixed_product_scenarios"]
        assert sample["outer_settlement"] == {"started_at": 0.5, "settled_at": 60.0}


@pytest.mark.parametrize("identity", ["instance", "service", "session"])
def test_collection_rejects_reused_identity_even_when_child_is_valid(tmp_path, identity):
    value, parameters = collection(tmp_path)
    old, new = {"instance": ("2" * 32, "1" * 32),
                "service": ("5" * 64, "4" * 64),
                "session": ("8" * 64, "7" * 64)}[identity]

    def replace(item):
        if isinstance(item, dict):
            return {key: replace(part) for key, part in item.items()}
        if isinstance(item, list):
            return [replace(part) for part in item]
        return new if isinstance(item, str) and item == old else item

    child = replace(value["fixed_product_scenarios"]["approval"])
    value["fixed_product_scenarios"]["approval"] = child
    runner.validate_managed_product_scenario(child, "approval", prefix=parameters["prefix"],
                                             workspace=tmp_path / "workspace" / "approval")
    with pytest.raises(ValueError, match="fresh service and Session identities"):
        runner.complete_managed_product(value, **parameters)


@pytest.mark.parametrize("fault", ["missing", "extra", "valid", "self-settlement", "failed-child",
                                  "summary", "spawns", "outer-early", "outer-late", "outer-bool",
                                  "outer-nan", "seed", "overlap"])
def test_collection_rejects_incomplete_or_premature_receipts(tmp_path, fault):
    value, parameters = collection(tmp_path)
    if fault == "missing":
        del value["fixed_product_scenarios"]["approval"]
    elif fault == "extra":
        value["failure"] = "late failure"
    elif fault == "valid":
        value["valid"] = True
    elif fault == "self-settlement":
        value["outer_settlement"] = {"started_at": 0, "settled_at": 60}
    elif fault == "failed-child":
        value["fixed_product_scenarios"]["approval"]["status"] = "failed"
    elif fault == "summary":
        value["milestones"]["visible_reply_seconds"] += 1
    elif fault == "spawns":
        value["spawns"] = value["spawns"][:-1]
    elif fault == "outer-early":
        parameters["owner_settled"] = 52
    elif fault == "outer-late":
        parameters["observer_started"] = 2
    elif fault == "outer-bool":
        parameters["observer_started"] = False
    elif fault == "outer-nan":
        parameters["owner_settled"] = float("nan")
    elif fault == "seed":
        value["seed"] = "history"
    elif fault == "overlap":
        value["fixed_product_scenarios"]["approval"]["started_at"] = 12
    with pytest.raises(ValueError):
        runner.complete_managed_product(value, **parameters)
