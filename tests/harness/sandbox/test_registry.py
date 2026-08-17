from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from loushang.harness.environment import HostEnvironment
from loushang.harness.sandbox import (
    SandboxBackendRegistration,
    SandboxBackendRegistry,
    SandboxBackendStatus,
)


@dataclass
class _ProbeBackend:
    backend_id: str
    state: str = "available"
    probed: list[HostEnvironment] = field(default_factory=list)

    def probe(self, environment: HostEnvironment) -> SandboxBackendStatus:
        self.probed.append(environment)
        return SandboxBackendStatus(
            backend_id=self.backend_id,
            state=self.state,
            reason="missing dependency" if self.state != "available" else None,
        )

    async def open_scope(self, request):
        raise AssertionError(f"unexpected scope request: {request}")

    async def close(self) -> None:
        return None


@pytest.mark.parametrize(
    ("environment", "expected_backend"),
    [
        (HostEnvironment("linux", "linux", "x86_64"), "linux"),
        (HostEnvironment("linux", "linux", "x86_64", is_wsl=True), "linux"),
        (HostEnvironment("macos", "darwin", "arm64"), "macos"),
        (HostEnvironment("windows", "win32", "amd64"), "windows"),
    ],
)
def test_registry_selects_only_the_platform_applicable_backend(
    environment: HostEnvironment,
    expected_backend: str,
) -> None:
    created: list[str] = []

    def registration(
        backend_id: str,
        family: str,
        *,
        platform_names: frozenset[str] | None = None,
    ) -> SandboxBackendRegistration:
        def factory() -> _ProbeBackend:
            created.append(backend_id)
            return _ProbeBackend(backend_id)

        return SandboxBackendRegistration(
            backend_id=backend_id,
            os_families=frozenset({family}),
            platform_names=platform_names,
            factory=factory,
        )

    registry = SandboxBackendRegistry(
        (
            registration("linux", "linux"),
            registration("macos", "macos"),
            registration(
                "windows",
                "windows",
                platform_names=frozenset({"win32"}),
            ),
        )
    )

    resolution = registry.resolve(environment)

    assert resolution.backend is not None
    assert resolution.backend.backend_id == expected_backend
    assert created == [expected_backend]
    assert resolution.selected_status is not None
    assert resolution.selected_status.state == "available"


def test_registry_distinguishes_not_applicable_from_unavailable() -> None:
    unavailable = _ProbeBackend("linux", state="unavailable")
    registry = SandboxBackendRegistry(
        (
            SandboxBackendRegistration(
                backend_id="macos",
                os_families=frozenset({"macos"}),
                factory=lambda: _ProbeBackend("macos"),
            ),
            SandboxBackendRegistration(
                backend_id="linux",
                os_families=frozenset({"linux"}),
                factory=lambda: unavailable,
            ),
        )
    )

    resolution = registry.resolve(HostEnvironment("linux", "linux", "x86_64"))

    assert resolution.backend is None
    assert [status.state for status in resolution.statuses] == [
        "not_applicable",
        "unavailable",
    ]
    assert resolution.unavailable_reason() == "linux: missing dependency"
    assert len(unavailable.probed) == 1


def test_native_windows_registration_does_not_claim_cygwin() -> None:
    created = False

    def factory() -> _ProbeBackend:
        nonlocal created
        created = True
        return _ProbeBackend("windows")

    registry = SandboxBackendRegistry(
        (
            SandboxBackendRegistration(
                backend_id="windows",
                os_families=frozenset({"windows"}),
                platform_names=frozenset({"win32"}),
                factory=factory,
            ),
        )
    )

    resolution = registry.resolve(HostEnvironment("windows", "cygwin", "x86_64"))

    assert resolution.backend is None
    assert resolution.statuses[0].state == "not_applicable"
    assert created is False


def test_registry_rejects_duplicate_ids() -> None:
    registration = SandboxBackendRegistration(
        backend_id="duplicate",
        os_families=frozenset({"linux"}),
        factory=lambda: _ProbeBackend("duplicate"),
    )

    with pytest.raises(ValueError, match="must be unique"):
        SandboxBackendRegistry((registration, registration))


def test_registry_projects_factory_and_probe_errors_as_unavailable() -> None:
    class _FailingProbeBackend(_ProbeBackend):
        def probe(self, environment: HostEnvironment) -> SandboxBackendStatus:
            del environment
            raise RuntimeError("probe boom")

    def failing_factory() -> _ProbeBackend:
        raise RuntimeError("factory boom")

    registry = SandboxBackendRegistry(
        (
            SandboxBackendRegistration(
                backend_id="factory",
                os_families=frozenset({"linux"}),
                factory=failing_factory,
            ),
            SandboxBackendRegistration(
                backend_id="probe",
                os_families=frozenset({"linux"}),
                factory=lambda: _FailingProbeBackend("probe"),
            ),
        )
    )

    resolution = registry.resolve(HostEnvironment("linux", "linux", "x86_64"))

    assert resolution.backend is None
    assert [status.state for status in resolution.statuses] == [
        "unavailable",
        "unavailable",
    ]
    assert resolution.unavailable_reason() == (
        "factory: backend factory failed: factory boom; "
        "probe: backend probe failed: probe boom"
    )
