from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Thread, current_thread

import pytest

from loushang.harness.config import ConfigApplyResult, ConfigIssue


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
                    raise TypeError(f"invalid config field: {key}")
            except Exception as exc:
                issues.append(ConfigIssue(layer=layer, message=str(exc), error=exc))
        return ConfigApplyResult(next_value, tuple(issues))


def _engine(tmp_path: Path, *, initial=None):
    from loushang.harness.config import ConfigLayer, LayeredConfig

    return LayeredConfig(
        codec=_Codec(),
        layers=(
            ConfigLayer("global", tmp_path / "global.json", persistent=True),
            ConfigLayer("project", tmp_path / "project.json", persistent=True),
            ConfigLayer("session"),
        ),
        initial=initial,
    )


def test_layered_config_loads_precedence_updates_and_notifies(tmp_path: Path) -> None:
    (tmp_path / "global.json").write_text(
        json.dumps({"name": "global", "limit": 20}),
        encoding="utf-8",
    )
    (tmp_path / "project.json").write_text(
        json.dumps({"name": "project"}),
        encoding="utf-8",
    )
    engine = _engine(tmp_path, initial={"session": {"enabled": False}})
    seen: list[_Config] = []
    unsubscribe = engine.subscribe(seen.append)

    assert engine.value == _Config(name="project", enabled=False, limit=20)

    engine.update("project", {"limit": 30})

    assert engine.value == _Config(name="project", enabled=False, limit=30)
    assert seen == [engine.value]
    assert json.loads((tmp_path / "project.json").read_text(encoding="utf-8")) == {
        "name": "project",
        "limit": 30,
    }
    unsubscribe()
    engine.update("session", {"name": "session"})
    assert len(seen) == 1


def test_layered_config_deep_merges_patch_snapshots(tmp_path: Path) -> None:
    from loushang.harness.config.engine import merge_config_patch

    merged = merge_config_patch(
        {"context": {"enabled": True, "reserve": 10}},
        {"context": {"reserve": 20}, "tools": ["read"]},
    )

    assert merged == {
        "context": {"enabled": True, "reserve": 20},
        "tools": ["read"],
    }

    engine = _engine(tmp_path)
    engine.update("session", {"name": "local"})
    snapshot = engine.snapshot()
    snapshot.patches["session"]["name"] = "mutated"  # type: ignore[index]
    assert engine.patch("session") == {"name": "local"}


def test_layered_config_preserves_previous_layer_on_reload_error(
    tmp_path: Path,
) -> None:
    global_path = tmp_path / "global.json"
    global_path.write_text(json.dumps({"name": "working"}), encoding="utf-8")
    engine = _engine(tmp_path)
    assert engine.value.name == "working"

    global_path.write_text("{not-json}", encoding="utf-8")
    engine.reload()

    assert engine.value.name == "working"
    issues = engine.drain_issues()
    assert len(issues) == 1
    assert issues[0].layer == "global"


def test_layered_config_reports_codec_issues_without_dropping_valid_fields(
    tmp_path: Path,
) -> None:
    (tmp_path / "global.json").write_text(
        json.dumps({"name": "valid", "unknown": True}),
        encoding="utf-8",
    )

    engine = _engine(tmp_path)

    assert engine.value.name == "valid"
    issues = engine.drain_issues()
    assert len(issues) == 1
    assert issues[0].layer == "global"
    assert "unknown" in issues[0].message


def test_layered_config_persistence_failure_does_not_publish_patch(
    tmp_path: Path,
) -> None:
    from loushang.harness.config import ConfigLayer, LayeredConfig

    class _FailingStore:
        def load(self, path: Path):
            del path
            return {}

        def save(self, path: Path, patch: Mapping[str, object]) -> None:
            del path, patch
            raise OSError("disk full")

    engine = LayeredConfig(
        codec=_Codec(),
        layers=(
            ConfigLayer(
                "global",
                tmp_path / "global.json",
                persistent=True,
            ),
        ),
        store=_FailingStore(),
    )

    import pytest

    with pytest.raises(OSError, match="disk full"):
        engine.update("global", {"name": "unpublished"})

    assert engine.value == _Config()
    assert engine.patch("global") == {}


def test_layered_config_update_codec_failure_is_transactional(tmp_path: Path) -> None:
    from loushang.harness.config import ConfigLayer, LayeredConfig

    class _ExplodingCodec(_Codec):
        def apply(self, value, patch, *, layer):
            if patch.get("name") == "explode":
                raise RuntimeError("invalid update")
            return super().apply(value, patch, layer=layer)

    path = tmp_path / "global.json"
    path.write_text(json.dumps({"name": "before"}), encoding="utf-8")
    engine = LayeredConfig(
        codec=_ExplodingCodec(),
        layers=(ConfigLayer("global", path, persistent=True),),
    )
    seen: list[_Config] = []
    engine.subscribe(seen.append)

    import pytest

    with pytest.raises(RuntimeError):
        engine.update("global", {"name": "explode"})

    assert engine.value == _Config(name="before")
    assert engine.patch("global") == {"name": "before"}
    assert json.loads(path.read_text(encoding="utf-8")) == {"name": "before"}
    assert seen == []


def test_layered_config_replace_codec_failure_is_transactional(tmp_path: Path) -> None:
    from loushang.harness.config import ConfigLayer, LayeredConfig

    class _ExplodingCodec(_Codec):
        def apply(self, value, patch, *, layer):
            if patch.get("name") == "explode":
                raise RuntimeError("invalid replacement")
            return super().apply(value, patch, layer=layer)

    path = tmp_path / "global.json"
    path.write_text(
        json.dumps({"name": "before", "limit": 20}),
        encoding="utf-8",
    )
    engine = LayeredConfig(
        codec=_ExplodingCodec(),
        layers=(ConfigLayer("global", path, persistent=True),),
    )
    seen: list[_Config] = []
    engine.subscribe(seen.append)

    import pytest

    with pytest.raises(RuntimeError):
        engine.replace("global", {"name": "explode"})

    assert engine.value == _Config(name="before", limit=20)
    assert engine.patch("global") == {"name": "before", "limit": 20}
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "name": "before",
        "limit": 20,
    }
    assert seen == []


def test_layered_config_reload_codec_failure_preserves_previous_layer(
    tmp_path: Path,
) -> None:
    from loushang.harness.config import ConfigLayer, LayeredConfig

    class _ExplodingCodec(_Codec):
        def apply(self, value, patch, *, layer):
            if patch.get("name") == "explode":
                raise RuntimeError("invalid reload")
            return super().apply(value, patch, layer=layer)

    path = tmp_path / "global.json"
    path.write_text(json.dumps({"name": "before"}), encoding="utf-8")
    engine = LayeredConfig(
        codec=_ExplodingCodec(),
        layers=(ConfigLayer("global", path, persistent=True),),
    )
    path.write_text(json.dumps({"name": "explode"}), encoding="utf-8")
    engine.reload()

    assert engine.value == _Config(name="before")
    assert engine.patch("global") == {"name": "before"}
    issues = engine.drain_issues()
    assert len(issues) == 1
    assert issues[0].layer == "global"
    assert isinstance(issues[0].error, RuntimeError)


def test_path_backed_nonpersistent_layer_serializes_explicit_persistence(
    tmp_path: Path,
) -> None:
    from loushang.harness.config import ConfigLayer, LayeredConfig

    path = tmp_path / "explicit.json"

    def build() -> LayeredConfig[_Config]:
        return LayeredConfig(
            codec=_Codec(),
            layers=(ConfigLayer("explicit", path, persistent=False),),
        )

    first = build()
    preloaded_peer = build()

    first.update("explicit", {"name": "first"}, persist=True)
    preloaded_peer.update("explicit", {"limit": 42}, persist=True)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "limit": 42,
        "name": "first",
    }


def test_layered_config_persistent_listener_can_reenter_after_unlock(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    seen: list[str] = []
    errors: list[BaseException] = []

    def reenter(value: _Config) -> None:
        seen.append(value.name)
        if value.name == "outer":
            engine.update("session", {"name": "nested"})

    engine.subscribe(reenter)

    def mutate() -> None:
        try:
            engine.update("global", {"name": "outer"})
        except BaseException as exc:
            errors.append(exc)

    worker = Thread(target=mutate, daemon=True)
    worker.start()
    worker.join(timeout=3)

    assert worker.is_alive() is False
    assert errors == []
    assert seen == ["outer", "nested"]
    assert engine.value.name == "nested"


@pytest.mark.parametrize("reader_kind", ["reload", "construct"])
def test_layered_config_readers_wait_for_cross_file_transaction(
    tmp_path: Path,
    reader_kind: str,
) -> None:
    writer = _engine(tmp_path)
    peer = _engine(tmp_path) if reader_kind == "reload" else None
    first_file_written = Event()
    release_writer = Event()
    reader_done = Event()
    observed: list[_Config] = []
    errors: list[BaseException] = []

    def write() -> None:
        try:
            with writer.transaction():
                writer.replace("global", {"name": "committed"})
                first_file_written.set()
                if not release_writer.wait(timeout=3):
                    raise TimeoutError("reader did not reach the transaction barrier")
                writer.replace("project", {"limit": 42})
        except BaseException as exc:
            errors.append(exc)

    def read() -> None:
        try:
            if not first_file_written.wait(timeout=3):
                raise TimeoutError("writer did not reach the transaction barrier")
            if peer is None:
                current = _engine(tmp_path)
            else:
                peer.reload()
                current = peer
            observed.append(current.value)
        except BaseException as exc:
            errors.append(exc)
        finally:
            reader_done.set()

    writer_thread = Thread(target=write, daemon=True)
    reader_thread = Thread(target=read, daemon=True)
    writer_thread.start()
    reader_thread.start()
    assert first_file_written.wait(timeout=3)
    assert reader_done.wait(timeout=0.1) is False
    release_writer.set()
    writer_thread.join(timeout=3)
    reader_thread.join(timeout=3)

    assert writer_thread.is_alive() is False
    assert reader_thread.is_alive() is False
    assert errors == []
    assert observed == [_Config(name="committed", limit=42)]


def test_layered_config_publications_keep_captured_commit_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine(tmp_path)
    first_drain_entered = Event()
    release_first_drain = Event()
    seen: list[str] = []
    errors: list[BaseException] = []
    original_drain = engine._drain_publications

    def delayed_drain() -> None:
        if current_thread().name == "first-commit":
            first_drain_entered.set()
            if not release_first_drain.wait(timeout=3):
                raise TimeoutError("second commit did not reach the publication queue")
        original_drain()

    monkeypatch.setattr(engine, "_drain_publications", delayed_drain)
    engine.subscribe(lambda value: seen.append(value.name))

    def mutate(name: str) -> None:
        try:
            engine.update("session", {"name": name})
        except BaseException as exc:
            errors.append(exc)

    first = Thread(target=mutate, args=("first",), name="first-commit", daemon=True)
    second = Thread(target=mutate, args=("second",), name="second-commit", daemon=True)
    first.start()
    assert first_drain_entered.wait(timeout=3)
    second.start()
    second.join(timeout=3)
    release_first_drain.set()
    first.join(timeout=3)

    assert first.is_alive() is False
    assert second.is_alive() is False
    assert errors == []
    assert seen == ["first", "second"]
