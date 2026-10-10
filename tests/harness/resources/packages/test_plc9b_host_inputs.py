"""Host resolution facts remain valid under a scrubbed Windows environment."""

from __future__ import annotations

import platform

import pytest
from packaging.markers import default_environment

from loushang.harness.package_product.product_local_wheel_runtime import (
    _host_marker_environment,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    PackageResolutionEnvironmentV1,
)


@pytest.mark.parametrize(
    ("python_platform", "expected_machine"),
    (("win-amd64", "AMD64"), ("win-arm64", "ARM64")),
)
def test_windows_host_marker_uses_interpreter_architecture_when_env_is_scrubbed(
    python_platform: str, expected_machine: str
) -> None:
    raw = {key: str(value) for key, value in default_environment().items()}
    raw["platform_machine"] = ""
    marker = _host_marker_environment(
        raw, native_platform="win32", python_platform=python_platform
    )
    assert marker["platform_machine"] == expected_machine
    assert raw["platform_machine"] == ""
    assert (
        PackageResolutionEnvironmentV1.from_mapping(
            marker, supported_tags=("cp311-cp311-win_amd64",)
        ).as_marker_mapping()["platform_machine"]
        == expected_machine
    )


def test_unknown_windows_architecture_still_refuses_empty_marker() -> None:
    raw = {key: str(value) for key, value in default_environment().items()}
    raw["platform_machine"] = ""
    marker = _host_marker_environment(
        raw, native_platform="win32", python_platform="win32"
    )
    with pytest.raises(ValueError, match="values cannot be empty"):
        PackageResolutionEnvironmentV1.from_mapping(
            marker, supported_tags=("cp311-cp311-win32",)
        )
    assert _host_marker_environment(
        raw, native_platform="linux", python_platform="win-amd64"
    )["platform_machine"] == ""


def test_windows_host_marker_reopens_cached_empty_release_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {key: str(value) for key, value in default_environment().items()}
    raw["platform_release"] = ""
    raw["platform_version"] = ""
    monkeypatch.setattr(
        platform, "win32_ver", lambda: ("10", "10.0.20348", "", "")
    )
    marker = _host_marker_environment(
        raw, native_platform="win32", python_platform="win-amd64"
    )
    assert marker["platform_release"] == "10"
    assert marker["platform_version"] == "10.0.20348"
    assert raw["platform_release"] == raw["platform_version"] == ""
    PackageResolutionEnvironmentV1.from_mapping(
        marker, supported_tags=("cp311-cp311-win_amd64",)
    )


def test_unknown_windows_release_still_refuses_with_named_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {key: str(value) for key, value in default_environment().items()}
    raw["platform_release"] = ""
    monkeypatch.setattr(platform, "win32_ver", lambda: ("", "10.0.20348", "", ""))
    marker = _host_marker_environment(
        raw, native_platform="win32", python_platform="win-amd64"
    )
    with pytest.raises(ValueError, match="platform_release"):
        PackageResolutionEnvironmentV1.from_mapping(
            marker, supported_tags=("cp311-cp311-win_amd64",)
        )
