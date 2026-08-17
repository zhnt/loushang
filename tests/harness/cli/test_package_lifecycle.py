from __future__ import annotations

import asyncio

import pytest

from loushang.harness.cli import (
    PackageLifecycleError,
    PackageLifecycleRequest,
    package_lifecycle_failure,
    run_package_lifecycle,
)


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    async def install_package(self, source: str, *, scope: str) -> dict[str, object]:
        self.calls.append(("install_package", source, scope))
        return {"lifecycle": "installed", "source": source}

    async def check_package_updates(self) -> list[dict[str, object]]:
        self.calls.append(("check_package_updates", "", None))
        return [{"lifecycle": "checked"}]

    async def update_packages(self) -> list[dict[str, object]]:
        self.calls.append(("update_packages", "", None))
        return [{"lifecycle": "updated"}]

    async def uninstall_package(self, source: str, *, scope: str) -> dict[str, object]:
        self.calls.append(("uninstall_package", source, scope))
        return {"lifecycle": "uninstalled", "source": source}


def test_package_lifecycle_preserves_standard_order_and_scope() -> None:
    session = _Session()
    result = asyncio.run(
        run_package_lifecycle(
            session,
            PackageLifecycleRequest(
                install=("one",),
                check_updates=True,
                update_all=True,
                uninstall=("one",),
                scope="project",
            ),
        )
    )

    assert [output["command"] for output in result.outputs] == [
        "install_package",
        "check_package_updates",
        "update_packages",
        "uninstall_package",
    ]
    assert session.calls == [
        ("install_package", "one", "project"),
        ("check_package_updates", "", None),
        ("update_packages", "", None),
        ("uninstall_package", "one", "project"),
    ]


def test_package_lifecycle_injects_policy_and_keeps_prior_outputs() -> None:
    session = _Session()
    with pytest.raises(PackageLifecycleError) as raised:
        asyncio.run(
            run_package_lifecycle(
                session,
                PackageLifecycleRequest(
                    install=("allowed", "denied"),
                ),
                evaluate_install_source=lambda source: (
                    "denied" if source == "denied" else None
                ),
            )
        )

    assert len(raised.value.outputs) == 1
    assert raised.value.outputs[0]["command"] == "install_package"
    assert session.calls == [("install_package", "allowed", "global")]


def test_package_lifecycle_failure_supports_wire_name_variants() -> None:
    assert package_lifecycle_failure(
        {"lifecycle": "failed", "error_message": "broken"}
    ) == "broken"
    assert package_lifecycle_failure({"lifecycle": "installed"}) is None
