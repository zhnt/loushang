"""Explicit local-shell adapter for command-backed configuration values."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, MutableMapping

from loushang.harness.config.values import (
    ConfigCommandResult,
    ConfigCommandRunner,
    ConfigValueResolver,
)

_SUBPROCESS_CONFIG_VALUE_CACHE: dict[str, str | None] = {}


class SubprocessConfigValueResolver(ConfigValueResolver):
    """Resolve explicit ``!command`` values through a local shell subprocess."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        runner: ConfigCommandRunner | None = None,
        cache: MutableMapping[str, str | None] | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        super().__init__(
            env=env,
            runner=run_subprocess_config_command if runner is None else runner,
            cache=cache,
            timeout_seconds=timeout_seconds,
        )


def resolve_subprocess_config_value(
    value: str | None,
    *,
    env: Mapping[str, str] | None = None,
    runner: ConfigCommandRunner | None = None,
    timeout_seconds: float = 10,
) -> str | None:
    """Resolve a value with the opt-in process-wide subprocess cache."""

    return SubprocessConfigValueResolver(
        env=env,
        runner=runner,
        cache=_SUBPROCESS_CONFIG_VALUE_CACHE,
        timeout_seconds=timeout_seconds,
    ).resolve(value)


def clear_subprocess_config_value_cache() -> None:
    _SUBPROCESS_CONFIG_VALUE_CACHE.clear()


def run_subprocess_config_command(
    command: str,
    *,
    timeout_seconds: float = 10,
) -> ConfigCommandResult:
    """Execute one explicitly requested config command through the local shell."""

    try:
        result = subprocess.run(
            command,
            check=False,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        return ConfigCommandResult(ok=False)
    return ConfigCommandResult(ok=result.returncode == 0, stdout=result.stdout)


__all__ = [
    "SubprocessConfigValueResolver",
    "clear_subprocess_config_value_cache",
    "resolve_subprocess_config_value",
    "run_subprocess_config_command",
]
