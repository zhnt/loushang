"""Shared discovery and application of extension-provided CLI flags."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from collections.abc import Mapping


def register_extension_flag_arguments(
    parser: ArgumentParser,
    flags: Mapping[str, object],
    *,
    reserved_names: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Register non-conflicting extension flags on an existing parser."""

    registered: dict[str, object] = {}
    for name, flag in flags.items():
        if name in reserved_names:
            continue
        flag_type = getattr(flag, "type", None)
        if flag_type not in {"boolean", "string"}:
            continue
        registered[name] = flag
        if flag_type == "boolean":
            parser.add_argument(
                f"--{name}",
                dest=extension_flag_dest(name),
                default=None,
                action="store_true",
            )
        else:
            parser.add_argument(
                f"--{name}",
                dest=extension_flag_dest(name),
                default=None,
            )
    return registered


def project_extension_flag_values(
    namespace: Namespace,
    flags: Mapping[str, object],
) -> dict[str, bool | str]:
    """Read registered extension values from an argparse namespace."""

    values: dict[str, bool | str] = {}
    for name, flag in flags.items():
        value = getattr(namespace, extension_flag_dest(name))
        if value is None:
            continue
        if getattr(flag, "type", None) == "boolean":
            values[name] = bool(value)
        elif isinstance(value, str):
            values[name] = value
    return values


def extract_unknown_long_options(
    argv: list[str],
    *,
    known_names: frozenset[str],
) -> tuple[list[str], dict[str, bool | str]]:
    """Remove unknown long options while preserving their bootstrap values."""

    filtered: list[str] = []
    unknown: dict[str, bool | str] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith("--"):
            filtered.append(token)
            index += 1
            continue
        if "=" in token:
            name, value = token[2:].split("=", 1)
            if name in known_names:
                filtered.append(token)
            else:
                unknown[name] = value
            index += 1
            continue
        name = token[2:]
        if name in known_names:
            filtered.append(token)
            index += 1
            continue
        if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
            unknown[name] = argv[index + 1]
            index += 2
            continue
        unknown[name] = True
        index += 1
    return filtered, unknown


def extension_flag_dest(name: str) -> str:
    return f"extension_flag_{name.replace('-', '_')}"


def collect_extension_flags(session: object) -> dict[str, object]:
    """Collect named flags from an injected extension runner."""

    runner = getattr(session, "extension_runner", None)
    getter = getattr(runner, "get_flags", None)
    if not callable(getter):
        return {}
    try:
        flags = getter()
    except Exception:
        return {}
    collected: dict[str, object] = {}
    for flag in flags:
        name = getattr(flag, "name", None)
        if isinstance(name, str) and name:
            collected[name] = flag
    return collected


def apply_extension_flag_values(
    session: object,
    values: Mapping[str, bool | str],
) -> None:
    """Apply parsed values through the extension runner, if available."""

    if not values:
        return
    runner = getattr(session, "extension_runner", None)
    setter = getattr(runner, "set_flag_value", None)
    if not callable(setter):
        return
    for name, value in values.items():
        setter(name, value)


__all__ = [
    "apply_extension_flag_values",
    "collect_extension_flags",
    "extension_flag_dest",
    "extract_unknown_long_options",
    "project_extension_flag_values",
    "register_extension_flag_arguments",
]
