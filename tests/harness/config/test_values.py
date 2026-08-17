from __future__ import annotations


def test_config_value_resolver_handles_literal_environment_and_none() -> None:
    from loushang.harness.config import ConfigValueResolver

    resolver = ConfigValueResolver(env={"RESEARCH_TOKEN": "from-env"})

    assert resolver.resolve(None) is None
    assert resolver.resolve("RESEARCH_TOKEN") == "from-env"
    assert resolver.resolve("literal-value") == "literal-value"
    assert resolver.resolve("!printf unavailable") is None


def test_config_value_resolver_caches_command_results_and_can_clear() -> None:
    from loushang.harness.config import ConfigCommandResult, ConfigValueResolver

    calls: list[str] = []

    def run(command: str, *, timeout_seconds: float) -> ConfigCommandResult:
        calls.append(f"{command}:{timeout_seconds:g}")
        return ConfigCommandResult(ok=True, stdout=b" token-\xff \n")

    resolver = ConfigValueResolver(runner=run, timeout_seconds=3)

    assert resolver.resolve("!load-token") == "token-\ufffd"
    assert resolver.resolve("!load-token") == "token-\ufffd"
    assert calls == ["load-token:3"]

    resolver.clear()
    assert resolver.resolve("!load-token") == "token-\ufffd"
    assert calls == ["load-token:3", "load-token:3"]


def test_config_value_resolver_caches_empty_and_failed_results() -> None:
    from loushang.harness.config import ConfigCommandResult, ConfigValueResolver

    calls: list[str] = []

    def run(command: str, *, timeout_seconds: float) -> ConfigCommandResult:
        del timeout_seconds
        calls.append(command)
        if command == "fail":
            return ConfigCommandResult(ok=False, stdout="ignored")
        return ConfigCommandResult(ok=True, stdout="  \n")

    resolver = ConfigValueResolver(runner=run)

    assert resolver.resolve("!") is None
    assert resolver.resolve("!fail") is None
    assert resolver.resolve("!fail") is None
    assert resolver.resolve("!empty") is None
    assert resolver.resolve("!empty") is None
    assert calls == ["fail", "empty"]


def test_subprocess_resolver_uses_shared_explicit_runner() -> None:
    from loushang.harness.config import (
        ConfigCommandResult,
        SubprocessConfigValueResolver,
    )

    calls: list[str] = []

    def runner(command: str, *, timeout_seconds: float) -> ConfigCommandResult:
        calls.append(f"{command}:{timeout_seconds:g}")
        return ConfigCommandResult(ok=True, stdout=" token-from-command \n")

    resolver = SubprocessConfigValueResolver(
        env={"API_KEY": "env-token"},
        runner=runner,
    )

    assert resolver.resolve("API_KEY") == "env-token"
    assert resolver.resolve("literal-token") == "literal-token"
    assert resolver.resolve("!printf token") == "token-from-command"
    assert resolver.resolve("!printf token") == "token-from-command"
    assert calls == ["printf token:10"]
