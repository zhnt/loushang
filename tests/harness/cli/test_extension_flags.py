from __future__ import annotations

from argparse import ArgumentParser
from types import SimpleNamespace

from loushang.harness.cli import (
    apply_extension_flag_values,
    collect_extension_flags,
    extract_unknown_long_options,
    project_extension_flag_values,
    register_extension_flag_arguments,
)


class _Runner:
    def __init__(self) -> None:
        self.values: dict[str, bool | str] = {}

    def get_flags(self):
        return [type("Flag", (), {"name": "plan"})(), type("Flag", (), {})()]

    def set_flag_value(self, name: str, value: bool | str) -> None:
        self.values[name] = value


def test_extension_flag_runtime_collects_named_flags_and_applies_values() -> None:
    session = type("Session", (), {"extension_runner": _Runner()})()

    flags = collect_extension_flags(session)
    apply_extension_flag_values(session, {"plan": True})

    assert tuple(flags) == ("plan",)
    assert session.extension_runner.values == {"plan": True}


def test_extension_flag_runtime_is_best_effort_for_missing_runner() -> None:
    assert collect_extension_flags(object()) == {}
    apply_extension_flag_values(object(), {"plan": True})


def test_extension_flag_parser_filters_reserved_and_projects_values() -> None:
    parser = ArgumentParser()
    registered = register_extension_flag_arguments(
        parser,
        {
            "plan": SimpleNamespace(type="boolean"),
            "label": SimpleNamespace(type="string"),
            "model": SimpleNamespace(type="string"),
        },
        reserved_names=frozenset({"model"}),
    )

    namespace = parser.parse_args(["--plan", "--label", "review"])

    assert tuple(registered) == ("plan", "label")
    assert project_extension_flag_values(namespace, registered) == {
        "plan": True,
        "label": "review",
    }


def test_unknown_extension_bootstrap_options_are_preserved_outside_argv() -> None:
    filtered, unknown = extract_unknown_long_options(
        ["--known", "value", "message", "--future=enabled", "--toggle"],
        known_names=frozenset({"known"}),
    )

    assert filtered == ["--known", "value", "message"]
    assert unknown == {"future": "enabled", "toggle": True}
