"""Independent canonical evidence checks; not whole-sample promotion."""

import pytest

from .test_measure_g18_native import runner


def evidence(tmp_path):
    identity = dict(product_id="coding", continuity_id="continuity", session_id="session",
                    scope="user_home", scope_fingerprint="a" * 64)
    value = dict(started_at=2.0, completed_at=3.0, root=str(tmp_path),
                 path=str(tmp_path / "hosted-session.jsonl"), workspace=str(tmp_path),
                 identity=dict(identity), canonical={
                     "recipe": "lmux-history-128x2048/v1", "rounds": 128,
                     "records": 256, "text_bytes": 263680,
                     "sha256": "00e1c01bb0a4603b94f5fbd70ea802f24a9389471893e5883310ba7c0c0fbb41"})
    return value, dict(root=tmp_path, workspace=tmp_path, identity=identity,
                       owner_settled_at=1.0, next_started_at=4.0)


def test_exact_canonical_receipt(tmp_path):
    value, bounds = evidence(tmp_path)
    runner.validate_managed_history_canonical(value, **bounds)


@pytest.mark.parametrize("field", ["product_id", "continuity_id", "session_id", "scope", "scope_fingerprint"])
def test_every_authenticated_identity_field_is_bound(tmp_path, field):
    value, bounds = evidence(tmp_path)
    value["identity"][field] = "other"
    with pytest.raises(ValueError):
        runner.validate_managed_history_canonical(value, **bounds)


@pytest.mark.parametrize("field", ["root", "path", "workspace"])
def test_exact_read_arguments_are_bound(tmp_path, field):
    value, bounds = evidence(tmp_path)
    value[field] += ".other"
    with pytest.raises(ValueError):
        runner.validate_managed_history_canonical(value, **bounds)


@pytest.mark.parametrize("field", ["recipe", "rounds", "records", "text_bytes", "sha256"])
def test_full_recipe_is_required_not_a_recent_tail(tmp_path, field):
    value, bounds = evidence(tmp_path)
    value["canonical"][field] = 15
    with pytest.raises(ValueError):
        runner.validate_managed_history_canonical(value, **bounds)


@pytest.mark.parametrize("field", ["started_at", "completed_at", "owner_settled_at", "next_started_at"])
@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1, 10**400, "2", None])
def test_all_timestamps_fail_closed(tmp_path, field, bad):
    value, bounds = evidence(tmp_path)
    (value if field in value else bounds)[field] = bad
    with pytest.raises(ValueError):
        runner.validate_managed_history_canonical(value, **bounds)


@pytest.mark.parametrize("fault", ["read-before-stop", "reversed-read", "restart-before-read",
                                  "missing", "extra", "float-count", "extra-recipe"])
def test_order_and_exact_inventories(tmp_path, fault):
    value, bounds = evidence(tmp_path)
    if fault == "read-before-stop":
        bounds["owner_settled_at"] = 2.5
    elif fault == "reversed-read":
        value["completed_at"] = 1.5
    elif fault == "restart-before-read":
        bounds["next_started_at"] = 2.5
    elif fault == "missing":
        value.pop("completed_at")
    elif fault == "extra":
        value["accepted"] = True
    elif fault == "float-count":
        value["canonical"]["records"] = 256.0
    else:
        value["canonical"]["extra"] = True
    with pytest.raises(ValueError):
        runner.validate_managed_history_canonical(value, **bounds)
