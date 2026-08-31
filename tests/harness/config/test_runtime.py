from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Thread

import pytest

from loushang.harness.config import (
    ConfigApplyResult,
    ConfigIssue,
    ConfigLayer,
    LayeredConfig,
    ScopedConfigRuntime,
)


@dataclass(frozen=True)
class _Config:
    name: str = "default"
    enabled: bool = True
    limit: int = 10


class _Codec:
    def default(self) -> _Config:
        return _Config()

    def encode(self, value: _Config) -> Mapping[str, object]:
        return {
            "name": value.name,
            "enabled": value.enabled,
            "limit": value.limit,
        }

    def apply(
        self,
        value: _Config,
        patch: Mapping[str, object],
        *,
        layer: str,
    ) -> ConfigApplyResult[_Config]:
        next_value = value
        issues: list[ConfigIssue] = []
        for key, raw in patch.items():
            try:
                if key == "name" and isinstance(raw, str):
                    next_value = replace(next_value, name=raw)
                elif key == "enabled" and isinstance(raw, bool):
                    next_value = replace(next_value, enabled=raw)
                elif key == "limit" and isinstance(raw, int):
                    next_value = replace(next_value, limit=raw)
                else:
                    raise TypeError("invalid config field")
            except Exception as exc:
                issues.append(ConfigIssue(layer=layer, message=str(exc), error=exc))
        return ConfigApplyResult(next_value, tuple(issues))


def _runtime(tmp_path: Path) -> ScopedConfigRuntime[_Config]:
    return ScopedConfigRuntime(
        LayeredConfig(
            codec=_Codec(),
            layers=(
                ConfigLayer(
                    "global",
                    tmp_path / "global.json",
                    persistent=True,
                ),
                ConfigLayer(
                    "project",
                    tmp_path / "project.json",
                    persistent=True,
                ),
                ConfigLayer("session"),
            ),
        )
    )


def test_scoped_config_runtime_exposes_layer_views(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    global_scope = runtime.scope("global")
    session_scope = runtime.scope("session")

    assert runtime.value == _Config()
    assert runtime.revision == 0
    assert global_scope.name == "global"
    assert global_scope.path == tmp_path / "global.json"
    assert global_scope.base_dir == tmp_path
    assert global_scope.persistent is True
    assert global_scope.patch == {}
    assert session_scope.name == "session"
    assert session_scope.path is None
    assert session_scope.base_dir is None
    assert session_scope.persistent is False


def test_scoped_config_runtime_publishes_update_and_replace_changes(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    changes = []
    values: list[_Config] = []
    unsubscribe_changes = runtime.subscribe_change(changes.append)
    unsubscribe_values = runtime.subscribe(values.append)

    update = runtime.scope("global").update({"name": "global", "limit": 20})

    assert update.revision == 1
    assert update.operation == "update"
    assert update.layer == "global"
    assert update.previous == _Config()
    assert update.current == _Config(name="global", limit=20)
    assert not hasattr(update, "patch")
    assert runtime.revision == 1
    assert runtime.value == update.current
    assert changes == [update]
    assert values == [update.current]
    assert json.loads((tmp_path / "global.json").read_text(encoding="utf-8")) == {
        "name": "global",
        "limit": 20,
    }

    replacement = runtime.scope("global").replace({"enabled": False})

    assert replacement.revision == 2
    assert replacement.operation == "replace"
    assert replacement.layer == "global"
    assert replacement.previous == update.current
    assert replacement.current == _Config(enabled=False)
    assert runtime.scope("global").patch == {"enabled": False}
    assert changes == [update, replacement]
    assert values == [update.current, replacement.current]

    unsubscribe_changes()
    unsubscribe_values()
    runtime.scope("session").update({"name": "local"})
    assert changes == [update, replacement]
    assert values == [update.current, replacement.current]


def test_scoped_config_runtime_scope_patch_is_a_defensive_copy(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.scope("session").update({"nested": {"enabled": True}})

    patch = runtime.scope("session").patch
    patch["nested"]["enabled"] = False  # type: ignore[index]

    assert runtime.scope("session").patch == {"nested": {"enabled": True}}


def test_scoped_config_runtime_reload_and_issue_drain(tmp_path: Path) -> None:
    path = tmp_path / "global.json"
    path.write_text(json.dumps({"name": "before"}), encoding="utf-8")
    runtime = _runtime(tmp_path)
    changes = []
    runtime.subscribe_change(changes.append)

    path.write_text(
        json.dumps({"name": "after", "limit": "invalid"}),
        encoding="utf-8",
    )
    change = runtime.reload()

    assert change.revision == 1
    assert change.operation == "reload"
    assert change.layer is None
    assert change.previous == _Config(name="before")
    assert change.current == _Config(name="after")
    assert runtime.value == change.current
    assert runtime.revision == 1
    assert changes == [change]
    issues = runtime.drain_issues()
    assert len(issues) == 1
    assert issues[0].layer == "global"
    assert isinstance(issues[0].error, TypeError)
    assert runtime.drain_issues() == ()


def test_scoped_config_runtime_queues_reentrant_publication_in_revision_order(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    first_seen: list[tuple[int, str]] = []
    second_seen: list[tuple[int, str]] = []
    values: list[_Config] = []

    def first_listener(change) -> None:
        first_seen.append((change.revision, change.current.name))
        if change.revision == 1:
            runtime.scope("session").update({"name": "two"})

    runtime.subscribe_change(first_listener)
    runtime.subscribe_change(
        lambda change: second_seen.append((change.revision, change.current.name))
    )
    runtime.subscribe(values.append)

    runtime.scope("session").update({"name": "one"})

    assert first_seen == [(1, "one"), (2, "two")]
    assert second_seen == [(1, "one"), (2, "two")]
    assert values == [_Config(name="one"), _Config(name="two")]
    assert runtime.revision == 2
    assert runtime.value == _Config(name="two")


def test_scoped_config_runtime_listener_failure_is_post_commit(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    def fail(_change) -> None:
        raise RuntimeError("listener failed")

    runtime.subscribe_change(fail)

    with pytest.raises(RuntimeError, match="listener failed"):
        runtime.scope("session").update({"name": "committed"})

    assert runtime.revision == 1
    assert runtime.value == _Config(name="committed")


def test_scoped_config_runtime_rejects_reentrant_writes_inside_transform(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    scope = runtime.scope("session")

    def reentrant_transform(patch: dict[str, object]) -> dict[str, object]:
        scope.update({"enabled": False})
        return {**patch, "name": "outer"}

    with pytest.raises(RuntimeError, match="cannot perform re-entrant writes"):
        scope.transform(reentrant_transform)

    assert runtime.revision == 0
    assert runtime.value == _Config()
    assert scope.patch == {}


def test_scoped_config_runtime_drains_reentrant_changes_before_listener_error(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    seen: list[tuple[int, str]] = []
    values: list[_Config] = []

    def update_again(change) -> None:
        if change.revision == 1:
            runtime.scope("session").update({"name": "two"})

    def fail_first(change) -> None:
        if change.revision == 1:
            raise RuntimeError("listener failed")

    runtime.subscribe_change(update_again)
    runtime.subscribe_change(fail_first)
    runtime.subscribe_change(
        lambda change: seen.append((change.revision, change.current.name))
    )
    runtime.subscribe(values.append)

    with pytest.raises(RuntimeError, match="listener failed"):
        runtime.scope("session").update({"name": "one"})

    assert seen == [(1, "one"), (2, "two")]
    assert values == [_Config(name="one"), _Config(name="two")]

    runtime.scope("session").update({"name": "three"})

    assert seen == [(1, "one"), (2, "two"), (3, "three")]
    assert runtime.revision == 3


def test_persistent_update_returns_the_exact_coalesced_published_change(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    preloaded_peer = _runtime(tmp_path)
    seen = []
    runtime.subscribe_change(seen.append)

    preloaded_peer.scope("global").update({"enabled": False})
    change = runtime.scope("global").update({"name": "local"})

    assert seen == [change]
    assert change is seen[0]
    assert change.previous == _Config()
    assert change.current == _Config(name="local", enabled=False)
    assert change.revision == 1


def test_transform_rejects_persistent_reentrant_write_before_file_lock(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    session = runtime.scope("session")
    errors: list[BaseException] = []

    def reentrant_transform(patch: dict[str, object]) -> dict[str, object]:
        runtime.scope("global").update({"enabled": False})
        return {**patch, "name": "outer"}

    def mutate() -> None:
        try:
            session.transform(reentrant_transform)
        except BaseException as exc:
            errors.append(exc)

    worker = Thread(target=mutate, daemon=True)
    worker.start()
    worker.join(timeout=3)

    assert worker.is_alive() is False
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "cannot perform re-entrant writes" in str(errors[0])
    assert runtime.revision == 0
    assert runtime.value == _Config()


def test_runtime_engine_listener_reenters_after_all_transaction_locks(
    tmp_path: Path,
) -> None:
    engine = LayeredConfig(
        codec=_Codec(),
        layers=(
            ConfigLayer("global", tmp_path / "global.json", persistent=True),
            ConfigLayer("session"),
        ),
    )
    runtime = ScopedConfigRuntime(engine)
    seen: list[str] = []
    errors: list[BaseException] = []

    def reenter(value: _Config) -> None:
        seen.append(value.name)
        if value.name == "outer":
            runtime.scope("session").update({"name": "nested"})

    engine.subscribe(reenter)

    def mutate() -> None:
        try:
            runtime.scope("global").update({"name": "outer"})
        except BaseException as exc:
            errors.append(exc)

    worker = Thread(target=mutate, daemon=True)
    worker.start()
    worker.join(timeout=3)

    assert worker.is_alive() is False
    assert errors == []
    assert seen == ["outer", "nested"]
    assert runtime.value.name == "nested"


def test_runtime_exclusively_owns_bound_engine_mutations(tmp_path: Path) -> None:
    engine = LayeredConfig(
        codec=_Codec(),
        layers=(ConfigLayer("session"),),
    )
    runtime = ScopedConfigRuntime(engine)

    with pytest.raises(RuntimeError, match="owned by its scoped runtime"):
        engine.update("session", {"name": "bypass"})

    change = runtime.scope("session").update({"name": "owned"})
    assert change.current.name == "owned"
    assert runtime.revision == 1


def test_explicit_transaction_returns_only_final_change_receipt(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    published = []
    runtime.subscribe_change(published.append)

    with runtime.transaction() as transaction:
        first = runtime.scope("global").update({"name": "first"})
        second = runtime.scope("project").update({"limit": 42})
        assert first is transaction
        assert second is transaction
        assert transaction.change is None

    assert transaction.change is not None
    assert transaction.change.operation == "transaction"
    assert transaction.change.layer is None
    assert transaction.change.current == _Config(name="first", limit=42)
    assert published == [transaction.change]
    assert published[0] is transaction.change
