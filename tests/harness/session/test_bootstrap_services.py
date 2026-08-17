from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.bootstrap import (
    ResourceBootstrapPorts,
    ResourceBootstrapRuntime,
)
from loushang.harness.session import (
    build_agent_product_session_runtime,
    prepare_agent_session_services,
)


def test_prepare_agent_session_services_uses_existing_resource_runtime(
    tmp_path: Path,
) -> None:
    created_for: list[Path] = []
    loader_options: list[dict[str, object]] = []
    loader = object()
    services = SimpleNamespace(resource_loader=loader)
    runtime = ResourceBootstrapRuntime(
        ResourceBootstrapPorts[
            object,
            dict[str, object],
            dict[str, object],
            str,
            str,
        ](
            discover_resources=lambda _loader, cwd: {"cwd": str(cwd)},
            create_extension_runtime=lambda bundle: {"bundle": bundle},
            apply_extension_flags=lambda _runtime, values: (
                f"flags:{dict(values or {})}",
            ),
            rediscover_resources=lambda _runtime, bundle: bundle,
            bundle_diagnostics=lambda _bundle: ("loader-diagnostic",),
            extension_diagnostics=lambda _runtime: ("extension-diagnostic",),
            normalize_diagnostic=lambda diagnostic, phase, source: (
                f"{phase}:{source}:{diagnostic}"
            ),
        )
    )

    result = prepare_agent_session_services(
        cwd=tmp_path / "product" / ".." / "product",
        create_services=lambda cwd: created_for.append(cwd) or services,
        build_resource_bootstrap=lambda _services: runtime,
        get_resource_loader=lambda value: value.resource_loader,
        resource_loader_options={"project_mode": "research"},
        configure_resource_loader=lambda _loader, options: loader_options.append(
            dict(options)
        ),
        extension_flag_values={"review": True},
    )

    resolved_cwd = (tmp_path / "product").resolve()
    assert created_for == [resolved_cwd]
    assert loader_options == [{"project_mode": "research"}]
    assert result.cwd == str(resolved_cwd)
    assert result.services is services
    assert result.resource_bundle == {"cwd": str(resolved_cwd)}
    assert result.extension_runner == {"bundle": {"cwd": str(resolved_cwd)}}
    assert result.diagnostics == (
        "resource_loading:loader:loader-diagnostic",
        "resource_loading:extensions:extension-diagnostic",
        "resource_loading:bootstrap:flags:{'review': True}",
    )


def test_prepare_agent_session_services_rejects_component_overrides(
    tmp_path: Path,
) -> None:
    services = SimpleNamespace(resource_loader=object())

    with pytest.raises(
        ValueError,
        match="service components cannot be overridden",
    ):
        prepare_agent_session_services(
            cwd=tmp_path,
            services=services,
            create_services=lambda _cwd: services,
            service_overrides={"settings_manager": object()},
            build_resource_bootstrap=lambda _services: None,  # type: ignore[arg-type]
            get_resource_loader=lambda value: value.resource_loader,
        )


def test_build_agent_product_session_runtime_binds_cwd_services_and_persistence(
    tmp_path: Path,
) -> None:
    fixed_services = SimpleNamespace(name="fixed")
    resolved_services: list[str] = []
    detached: list[object] = []

    class Runtime:
        def __init__(self, **kwargs: object) -> None:
            self.options = kwargs

    runtime = build_agent_product_session_runtime(
        session_dir=tmp_path,
        runtime_factory=Runtime,
        fixed_services=fixed_services,
        services_factory=lambda cwd: (
            resolved_services.append(cwd) or SimpleNamespace(name=cwd)
        ),
        session_cwd=lambda manager: manager.cwd,
        build_session=lambda manager, services, event: SimpleNamespace(
            manager=manager,
            services=services,
            event=event,
        ),
        persist=False,
        diagnostics_service="diagnostics",
        on_non_persistent_session=detached.append,
    )
    manager = SimpleNamespace(cwd="/research")
    session = runtime.options["session_factory"](
        manager,
        session_start_event="startup",
    )

    assert runtime.options["session_dir"] == tmp_path
    assert runtime.options["persist"] is False
    assert runtime.options["diagnostics_service"] == "diagnostics"
    assert resolved_services == ["/research"]
    assert session.services.name == "/research"
    assert session.event == "startup"
    assert detached == [session]
