"""Explicit frozen A173 registry observations; controlled policy ports and real threads/settings notifications. No default PR discovery claim."""

from __future__ import annotations

import gzip
import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from threading import Condition, Event, Thread

import pytest

import loushang.coding.plugin_enablement_compatibility as code
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.config.agent.manager import LegacyPluginCompatibilityProjectionV1

EXPECTED = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "plugin_compatibility_registry_v1.json.gz"
)
CACHE = "_loushang_coding_plugin_enablement_compatibility_writer"
CASES = (
    "aggregate",
    "stale-desired",
    "stale-migration",
    "equal-revisions",
    "cross-regression",
    "writer-identity",
    "publish-error-retry",
    "guard-snapshot",
    "guard-error",
    "thread-success",
    "thread-head-error",
    "thread-head-base",
    "thread-tail-error",
    "thread-both-errors",
    "thread-same-error",
    "settings-none",
    "settings-no-fence-empty",
    "settings-no-fence-migrated",
    "cache-same-settings",
    "cache-foreign-object",
    "cache-other-settings",
    "cache-attribute-error",
    "cache-type-error",
    "bind-error",
    "bind-base",
    "bind-uncallable",
    "rollback-delete-error",
    "rollback-replaced-cache",
    "actual-settings-reentrant",
)


class InputError(RuntimeError):
    __module__ = "__a173_input__"


class InputBase(BaseException):
    __module__ = "__a173_input__"


def error_value(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "args": list(error.args),
        "message": str(error),
        "notes": list(getattr(error, "__notes__", ())),
        "cause": error_value(error.__cause__, seen.copy()),
        "context": error_value(error.__context__, seen.copy()),
        "suppress": error.__suppress_context__,
    }


def projection(disabled=("a",), migrated=("a", "shared"), desired=5, migration=7):
    return LegacyPluginCompatibilityProjectionV1(disabled, migrated, desired, migration)


def observe(case, tmp_path, monkeypatch):
    trace = []
    layouts = [
        resolve_coding_plugin_lifecycle_state_layout(tmp_path / x)
        for x in ("a", "b", "c")
    ]
    roles = {value: name for value, name in zip(layouts, ("a", "b", "c"), strict=True)}

    class Settings:
        def bind_plugin_enablement_legacy_mutation_guard(self, authority, guard):
            self.authority = authority
            self.guard = guard
            trace.append(["bind", getattr(self, CACHE, None) is authority])
            return lambda value: trace.append(["sink", asdict(value)])

    settings = Settings()
    registry = code._CodingPluginEnablementCompatibilityRegistry(settings)
    registry.bind()
    wa, wb = [registry.writer(value) for value in layouts[:2]]
    result = None
    failure = None
    flags = {}
    try:
        if case.startswith("thread-"):
            entered = [Event(), Event()]
            release = [Event(), Event()]
            waiting = Event()
            done = [Event(), Event()]
            failures = {}
            faults = [None, None]
            if case in {"thread-head-error", "thread-both-errors"}:
                faults[0] = InputError("head")
            if case == "thread-head-base":
                faults[0] = InputBase("head base")
            if case in {"thread-tail-error", "thread-both-errors"}:
                faults[1] = InputError("tail")
            if case == "thread-same-error":
                faults = [InputBase("shared"), InputBase("unused")]
                faults[1] = faults[0]

            class WaitingCondition(Condition):
                def wait(self, timeout=None):
                    waiting.set()
                    return super().wait(timeout)

            registry._condition = WaitingCondition()
            calls = []

            def sink(value):
                index = len(calls)
                calls.append(asdict(value))
                entered[index].set()
                assert release[index].wait(5), "probe release missing"
                if faults[index] is not None:
                    raise faults[index]

            registry._publish = sink

            def run(index, writer, value):
                try:
                    registry.publish(writer, value)
                except BaseException as exc:
                    failures[index] = exc
                finally:
                    done[index].set()

            workers = [
                Thread(target=run, args=(0, wa, projection()), daemon=True),
                Thread(
                    target=run,
                    args=(1, wb, projection(("b",), ("b",), 8, 9)),
                    daemon=True,
                ),
            ]
            try:
                workers[0].start()
                assert entered[0].wait(5), "head sink not reached"
                workers[1].start()
                assert waiting.wait(5), "second caller did not wait"
                flags["second_waits_before_head_release"] = not done[1].is_set()
                release[0].set()
                assert entered[1].wait(5), "tail not drained"
                flags["drainer_stays_until_tail"] = not done[0].is_set()
                flags["tail_waits_own_sink"] = not done[1].is_set()
            finally:
                for gate in release:
                    gate.set()
                for worker in workers:
                    if worker.ident is not None:
                        worker.join(5)
            assert all(not worker.is_alive() for worker in workers), (
                "probe thread remains"
            )
            assert len(calls) == 2
            assert all(flags.values())
            result = {
                "calls": calls,
                "errors": [error_value(failures.get(i)) for i in range(2)],
                "same_error_objects": [
                    failures.get(i) is faults[i]
                    if faults[i] is not None
                    else failures.get(i) is None
                    for i in range(2)
                ],
            }
            assert all(result["same_error_objects"])
        elif case == "actual-settings-reentrant":
            from loushang.coding.control import SettingsManager
            from loushang.harness.config.agent.types import ControlConfig
            from loushang.harness.plugin_management import (
                PluginEnablementCompatibilityProjectionV1,
            )

            monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
            settings = SettingsManager(
                initial=ControlConfig(disabled_plugins=("a",)),
                project_settings_path=tmp_path / "settings.json",
            )
            writer = code.bind_coding_plugin_enablement_compatibility(
                layouts[0], settings
            )
            registry = getattr(settings, CACHE)
            wa = writer

            @contextmanager
            def capture(_layout):
                trace.append(["capture-enter"])
                yield object()
                trace.append(["capture-exit"])

            monkeypatch.setattr(
                code, "_capture_existing_plugin_enablement_state", capture
            )
            monkeypatch.setattr(
                code,
                "project_coding_plugin_enablement_compatibility",
                lambda *_args, **_kwargs: (
                    PluginEnablementCompatibilityProjectionV1(1, 1, ()),
                    frozenset({"a"}),
                ),
            )
            notifications = []

            def listener(value):
                notifications.append(list(value.disabled_plugins))
                trace.append(["listener", registry._publishing])
                writer.reconcile()

            settings.subscribe(listener)
            writer.reconcile()
            assert notifications == [[]]
            assert settings.get_settings().disabled_plugins == ()
            result = {
                "notifications": notifications,
                "disabled": list(settings.get_settings().disabled_plugins),
            }
        elif case in {
            "aggregate",
            "stale-desired",
            "stale-migration",
            "equal-revisions",
            "cross-regression",
        }:
            registry.publish(wa, projection())
            values = {
                "aggregate": (wb, projection(("b",), ("b", "shared"), 8, 3)),
                "stale-desired": (wa, projection(("b",), ("b",), 4, 8)),
                "stale-migration": (wa, projection(("b",), ("b",), 6, 6)),
                "equal-revisions": (wa, projection(("b",), ("b",), 5, 7)),
                "cross-regression": (wa, projection(("b",), ("b",), 8, 2)),
            }
            registry.publish(*values[case])
            result = {"writer_reuse": registry.writer(layouts[0]) is wa}
        elif case == "writer-identity":
            registry.publish(
                code.CodingPluginEnablementCompatibilityWriter(layouts[0], registry),
                projection(),
            )
        elif case == "publish-error-retry":
            fault = InputError("first publish")
            calls = []

            def sink(value):
                calls.append(asdict(value))
                if len(calls) == 1:
                    raise fault

            registry._publish = sink
            try:
                registry.publish(wa, projection())
            except BaseException as exc:
                assert exc is fault
                trace.append(
                    ["first-error", error_value(exc), len(registry.projections)]
                )
            registry.publish(wa, projection())
            result = {"calls": calls}
        elif case in {"guard-snapshot", "guard-error"}:
            calls = []

            def guard(writer, plugin_id):
                calls.append([roles[writer.layout], plugin_id])
                trace.append(["guard", roles[writer.layout], plugin_id])
                if writer is wa:
                    registry.writer(layouts[2])
                if writer is wb and case == "guard-error":
                    raise InputError("writer guard")

            monkeypatch.setattr(
                code.CodingPluginEnablementCompatibilityWriter,
                "_assert_legacy_mutation_allowed",
                guard,
            )
            registry._assert_legacy_mutation_allowed("plugin")
            registry._assert_legacy_mutation_allowed("again")
            result = calls
        else:
            from loushang.harness.plugin_management import (
                PluginEnablementCompatibilityProjectionV1,
            )

            if case == "settings-none":
                result = code.bind_coding_plugin_enablement_compatibility(
                    layouts[0], None
                )
            elif case.startswith("settings-no-fence"):
                settings = object()
                migrated = (
                    frozenset({"a"}) if case.endswith("migrated") else frozenset()
                )
                monkeypatch.setattr(
                    code,
                    "project_coding_plugin_enablement_compatibility",
                    lambda _layout: (
                        PluginEnablementCompatibilityProjectionV1(0, 0, ()),
                        migrated,
                    ),
                )
                result = code.bind_coding_plugin_enablement_compatibility(
                    layouts[0], settings
                )
            else:

                class BindingSettings(Settings):
                    def __setattr__(self, name, value):
                        if name == CACHE and case in {
                            "cache-attribute-error",
                            "cache-type-error",
                        }:
                            error_type = (
                                AttributeError
                                if case == "cache-attribute-error"
                                else TypeError
                            )
                            raise error_type("cache rejected")
                        object.__setattr__(self, name, value)

                    def __delattr__(self, name):
                        if name == CACHE and case == "rollback-delete-error":
                            raise AttributeError("delete rejected")
                        object.__delattr__(self, name)

                    def bind_plugin_enablement_legacy_mutation_guard(
                        self, authority, guard
                    ):
                        self.authority = authority
                        trace.append(["bind", getattr(self, CACHE, None) is authority])
                        if case == "rollback-replaced-cache":
                            object.__setattr__(self, CACHE, foreign)
                        if case in {
                            "bind-error",
                            "rollback-delete-error",
                            "rollback-replaced-cache",
                        }:
                            raise InputError("binding failure")
                        if case == "bind-base":
                            raise InputBase("binding base failure")
                        if case == "bind-uncallable":
                            return None
                        return lambda value: trace.append(["sink", asdict(value)])

                settings = BindingSettings()
                foreign = object()
                if case == "cache-foreign-object":
                    setattr(settings, CACHE, foreign)
                if case == "cache-other-settings":
                    setattr(settings, CACHE, registry)
                writer = code.bind_coding_plugin_enablement_compatibility(
                    layouts[0], settings
                )
                cached = getattr(settings, CACHE)
                result = {
                    "same_writer": code.bind_coding_plugin_enablement_compatibility(
                        layouts[0], settings
                    )
                    is writer,
                    "second_writer_distinct": code.bind_coding_plugin_enablement_compatibility(
                        layouts[1], settings
                    )
                    is not writer,
                    "registry_identity": cached.settings_manager is settings,
                }
    except BaseException as exc:
        if isinstance(exc, code.CodingPluginEnablementCompatibilityError):
            expected_codes = {
                "settings-no-fence-migrated": "coding_plugin_compatibility_fence_unavailable",
                "cache-foreign-object": "coding_plugin_compatibility_authority_conflict",
                "cache-other-settings": "coding_plugin_compatibility_authority_conflict",
                "cache-attribute-error": "coding_plugin_compatibility_authority_unavailable",
                "cache-type-error": "coding_plugin_compatibility_authority_unavailable",
            }
            assert exc.code == expected_codes[case]
        failure = error_value(exc)
    cache = getattr(settings, CACHE, None)
    authority = getattr(
        settings, "authority", getattr(settings, "_legacy_plugin_guard_authority", None)
    )
    return {
        "case": case,
        "result": result,
        "error": failure,
        "trace": trace,
        "flags": flags,
        "registry": {
            "writers": [roles[x] for x in registry.writers],
            "projections": [
                [roles[x], asdict(value)] for x, value in registry.projections.items()
            ],
            "pending": len(registry._pending),
            "publishing": registry._publishing,
        },
        "cache": {
            "present": cache is not None,
            "ours": cache is registry,
            "settings_match": getattr(cache, "settings_manager", None) is settings,
            "bound_authority_present": authority is not None,
            "bound_authority_is_cache": authority is not None and authority is cache,
            "bound_authority_settings_match": getattr(
                authority, "settings_manager", None
            )
            is settings,
        },
    }


@pytest.mark.parametrize("case", CASES)
def test_registry(case, tmp_path, monkeypatch):
    observed = json.loads(json.dumps(observe(case, tmp_path, monkeypatch)))
    rejects = {
        "writer-identity": "builtins.RuntimeError",
        "guard-error": "__a173_input__.InputError",
        "settings-no-fence-migrated": "loushang.coding.plugin_enablement_compatibility.CodingPluginEnablementCompatibilityError",
        "cache-foreign-object": "loushang.coding.plugin_enablement_compatibility.CodingPluginEnablementCompatibilityError",
        "cache-other-settings": "loushang.coding.plugin_enablement_compatibility.CodingPluginEnablementCompatibilityError",
        "cache-attribute-error": "loushang.coding.plugin_enablement_compatibility.CodingPluginEnablementCompatibilityError",
        "cache-type-error": "loushang.coding.plugin_enablement_compatibility.CodingPluginEnablementCompatibilityError",
        "bind-error": "__a173_input__.InputError",
        "bind-base": "__a173_input__.InputBase",
        "bind-uncallable": "builtins.TypeError",
        "rollback-delete-error": "__a173_input__.InputError",
        "rollback-replaced-cache": "__a173_input__.InputError",
    }
    if case in rejects:
        assert (
            observed["error"] is not None and observed["error"]["type"] == rejects[case]
        ), observed
    else:
        assert observed["error"] is None, observed
    assert observed == json.loads(gzip.decompress(EXPECTED.read_bytes()))[case]
