from __future__ import annotations

import pytest

from loushang.harness.environment import (
    HostEnvironment,
    LocalHostEnvironmentProbe,
    operating_system_family,
)


@pytest.mark.parametrize(
    ("platform_name", "expected"),
    [
        ("linux", "linux"),
        ("linux2", "linux"),
        ("darwin", "macos"),
        ("win32", "windows"),
        ("cygwin", "windows"),
        ("msys", "windows"),
        ("freebsd14", "other"),
    ],
)
def test_operating_system_family_uses_existing_sys_platform_vocabulary(
    platform_name: str,
    expected: str,
) -> None:
    assert operating_system_family(platform_name) == expected


def test_local_host_environment_probe_is_fully_injectable() -> None:
    environment = LocalHostEnvironmentProbe(
        platform_name="linux",
        architecture="X86_64",
        environ={"WSL_INTEROP": "/run/WSL/1_interop"},
    ).detect()

    assert environment == HostEnvironment(
        os_family="linux",
        platform_name="linux",
        architecture="x86_64",
        is_wsl=True,
    )


def test_local_host_environment_probe_ignores_wsl_markers_off_linux() -> None:
    environment = LocalHostEnvironmentProbe(
        platform_name="darwin",
        architecture="arm64",
        environ={"WSL_DISTRO_NAME": "not-really-wsl"},
    ).detect()

    assert environment.os_family == "macos"
    assert environment.is_wsl is False


def test_host_environment_rejects_inconsistent_wsl_fact() -> None:
    with pytest.raises(ValueError, match="is_wsl requires"):
        HostEnvironment(
            os_family="windows",
            platform_name="win32",
            architecture="amd64",
            is_wsl=True,
        )
