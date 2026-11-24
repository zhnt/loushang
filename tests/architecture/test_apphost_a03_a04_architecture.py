from __future__ import annotations

import sys
from pathlib import Path

from tests.architecture._source_imports import resolved_imports

APPHOST = Path("src/loushang/apphost")
APPSERVER = Path("src/loushang/appserver")
CORE = {
    APPHOST / "__init__.py",
    APPHOST / "_ownership.py",
    APPHOST / "catalog.py",
    APPHOST / "contracts.py",
    APPHOST / "errors.py",
    APPHOST / "router.py",
    APPHOST / "runtime.py",
}
HOSTED = APPHOST / "hosted.py"
APPLICATION = APPHOST / "application.py"
CONTINUITY = APPHOST / "continuity.py"
FOREGROUND = APPHOST / "foreground.py"
SCOPE = Path("docs/internals/architecture/apphost/README.md")
CONTRACT = Path("docs/internals/architecture/apphost/contract-model-a0.md")
APPSERVER_SCOPE = Path("docs/internals/architecture/appserver/README.md")
WORKFLOW = Path(".github/workflows/apphost-quality.yml")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    return resolved_imports(path, reject_invalid_relative=False)


def test_a0_3_core_is_stdlib_only_and_facade_exposes_no_optional_edge() -> None:
    assert {path for path in APPHOST.glob("*.py")} == CORE | {
        APPHOST / "client_preferences.py",
        HOSTED,
        APPLICATION,
        CONTINUITY,
        FOREGROUND,
        APPHOST / "local.py",
        APPHOST / "launcher.py",
        APPHOST / "workspace_registry.py",
    }
    for path in CORE:
        for imported in _imports(path):
            if imported == "loushang.apphost" or imported.startswith(
                "loushang.apphost."
            ):
                continue
            assert imported.partition(".")[0] in sys.stdlib_module_names, (
                path,
                imported,
            )
    facade = _source(APPHOST / "__init__.py")
    facade_imports = _imports(APPHOST / "__init__.py")
    assert '"AppHostRuntimeV1"' in facade
    assert '"AppHostSessionLeaseV1"' in facade
    assert "loushang.apphost.hosted" not in facade_imports
    assert "loushang.apphost.application" not in facade_imports
    assert not any(item.startswith("loushang.appserver") for item in facade_imports)


def test_a0_3_has_one_private_runtime_route_and_catalog_execution_seam() -> None:
    router = _source(APPHOST / "router.py")
    catalog = _source(APPHOST / "catalog.py")
    runtime = _source(APPHOST / "runtime.py")
    assert "async def _prepare_runtime_resume_candidate(" in router
    assert "async def _prepare_runtime_create_candidate(" in router
    assert "async def _acquire_runtime_product(" in catalog
    assert "async def acquire_runtime_product(" not in catalog
    assert "self._router._prepare_runtime_resume_candidate(" in runtime
    assert "self._router._prepare_runtime_create_candidate(" in runtime
    assert "self._catalog._acquire_runtime_product(" not in runtime
    consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if "._acquire_runtime_product(" in _source(path)
    }
    assert consumers == {APPHOST / "router.py"}


def test_a0_3_registry_owns_single_flight_and_dependency_ordered_close() -> None:
    source = _source(APPHOST / "runtime.py")
    for proof in (
        "self._slots: dict[SessionBindingKeyV1, _LiveSlot]",
        "task = asyncio.create_task(self._build(route))",
        "await route.discard_current()",
        "await route.open_with(binding._admission)",
        "DependentCloseChain(",
        "await self._inflight_drained.wait()",
        "await self._all_drained.wait()",
        "await self._owner_chain.close()",
        "_ACTIVE_RUNTIME_CALLBACKS",
    ):
        assert proof in source
    assert "default_product" not in source
    assert "importlib" not in source
    assert "entry_points" not in source


def test_a0_4_hosted_binder_stays_wiring_only_after_g11_consumers() -> None:
    hosted_imports = _imports(HOSTED)
    assert "loushang.appserver.ports" in hosted_imports
    # AppHost's optional Session integrations use only these protocol values.
    integration_protocol_values = {
        APPHOST / "integrations/_canonical_transcript_catalog.py": {
            "AppErrorCodeV1",
            "AppServiceError",
            "SessionAvailabilityV1",
            "SessionCompatibilityV1",
            "SessionDiscoveryCandidateV1",
            "SessionIdentityV1",
            "SessionOpenSpecV1",
            "SessionScopeV1",
            # Existing Workspace wire values now projected by the same catalog.
            "WorkspaceInfoV1",
            "WorkspaceRequestV1",
            "WorkspaceResultV1",
            "workspace_preview",
            "workspace_preview.WorkspaceDirectoryPreviewV1",
            "workspace_preview.WorkspaceFilePreviewV1",
            "workspace_preview.WorkspacePreviewEntryV1",
            "workspace_preview.WorkspacePreviewRequestV1",
            "workspace_preview.WorkspacePreviewV1",
        },
        APPHOST / "integrations/_session_projection.py": {
            "SessionEventKindV1",
            "TranscriptRecordKindV1",
            "TranscriptRecordV1",
        },
        APPHOST / "integrations/session_product.py": {
            "SessionIdentityV1",
            "SessionOpenSpecV1",
        },
    }
    hosted_contract_values = {
        APPHOST / "integrations/resource_tools.py": {
            "protocol": {"AppServiceError"},
        },
        APPHOST / "integrations/user_choice.py": {
            "protocol": {"UserChoiceOptionV1", "UserChoicePromptV1"},
            "protocol.model": {
                "USER_CHOICE_DESCRIPTION_CHARS", "USER_CHOICE_ID_CHARS",
                "USER_CHOICE_LABEL_CHARS", "USER_CHOICE_MAX_OPTIONS",
                "USER_CHOICE_QUESTION_CHARS",
            },
        },
        APPHOST / "integrations/resource_access.py": {
            "execution.model": {"ResourceRefV1"},
            "execution.resources": {
                "RESOURCE_CHUNK_BYTES", "ResourceV1", "SessionResourceQueryV1",
                "SessionResourceResultV1", "TEXT_MEDIA_TYPE",
            },
            "protocol": {"AppErrorCodeV1", "AppServiceError"},
        },
        APPHOST / "integrations/_resource_client_reference.py": {
            "execution.resources": {"ClientResourceRequestV1", "ResourceV1"},
            "protocol": {"AppErrorCodeV1", "AppServiceError"},
        },
        APPHOST / "integrations/_resource_host_reference.py": {
            "execution.resources": {"ResourceV1"},
            "protocol": {"AppErrorCodeV1", "AppServiceError"},
        },
        APPHOST / "integrations/_session_commands.py": {
            "execution.session_commands": {
                "SessionCommandCatalogV1", "SessionCommandChoiceV1",
                "SessionCommandInvocationV1", "SessionCommandResultV1",
            },
            "protocol": {"AppErrorCodeV1", "AppServiceError"},
        },
    }
    hosted_contract_imports = {
        path: {
            f"loushang.appserver.{item}"
            for module, values in modules.items()
            for item in (module, *(f"{module}.{value}" for value in values))
        }
        for path, modules in hosted_contract_values.items()
    }
    appserver_consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if path != HOSTED and not path.is_relative_to(APPSERVER)
        and any(
            item == "loushang.appserver"
            or item.startswith("loushang.appserver.")
            for item in _imports(path)
        )
    }
    for consumer in appserver_consumers:
        if consumer in hosted_contract_imports:
            assert {
                name for name in _imports(consumer)
                if name == "loushang.appserver" or name.startswith("loushang.appserver.")
            } == hosted_contract_imports[consumer]
            continue
        assert (
            consumer == Path('src/loushang/coding/hosted/service_adapter.py')
            or consumer == Path('src/loushang/coding/hosted/managed/service.py')
            or consumer == Path('src/loushang/coding/hosted/macos_service.py')
            or consumer == Path('src/loushang/coding/hosted/foreground.py')
            or consumer == Path('src/loushang/coding/hosted/tunnel.py')
            or consumer == Path('src/loushang/coding/hosted/application.py')
            or consumer == Path('src/loushang/coding/hosted/catalog.py')
            or consumer == Path('src/loushang/coding/hosted/resume.py')
            or consumer == Path('src/loushang/coding/hosted/managed/catalog.py')
            or consumer == Path('src/loushang/coding/hosted/workspace_catalog.py')
            or consumer == Path('src/loushang/coding/hosted/managed/bootstrap.py')
            or consumer == Path('src/loushang/coding/hosted/managed/local.py')
            or consumer == Path('src/loushang/coding/hosted/session.py')
            or consumer == Path('src/loushang/coding/hosted/execution.py')
            # Reviewed Method capability values and Product execution adapter.
            or consumer == Path('src/loushang/coding/hosted/method.py')
            or consumer == Path('src/loushang/coding/hosted/_method_config.py')
            # COD-KD-HG-001: Goal values and shared safe Work projection.
            or consumer == Path('src/loushang/coding/hosted/goal.py')
            or consumer in {
                Path('src/loushang/coding/hosted/execution_goal.py'),
                Path('src/loushang/coding/hosted/goal_commands.py'),
                Path('src/loushang/coding/hosted/goal_recovery.py'),
                Path('src/loushang/coding/hosted/goal_review.py'),
                Path('src/loushang/coding/hosted/session_goal.py'),
                Path('src/loushang/coding/hosted/user_choice.py'),
            }
            or consumer == Path('src/loushang/coding/hosted/_work_observation.py')
            # Retained native execution and original subject borrow, no binder.
            or consumer == Path('src/loushang/coding/hosted/_execution_work.py')
            # Same exact current-subject guard extracted from that owner.
            or consumer == Path("src/loushang/coding/resume/subject.py")
            or consumer == Path("src/loushang/coding/cli/hosted.py")
            or consumer == Path("src/loushang/coding/cli/hosted_client.py")
            or consumer == Path("src/loushang/coding/cli/mux.py")
            or consumer == Path("src/loushang/coding/cli/lmux_command.py")
            or consumer == Path('src/loushang/coding/hosted/bootstrap.py')
            or consumer == Path('src/loushang/coding/hosted/local.py')
            or consumer == APPLICATION
            or consumer == CONTINUITY
            or consumer == FOREGROUND
            or consumer == APPHOST / "local.py"
            or consumer == APPHOST / "launcher.py"
            or consumer == APPHOST / "integrations/session_control.py"
            # A180: optional complete foreground control; no core facade edge.
            or consumer == APPHOST / "integrations/_foreground_client_control.py"
            or consumer == APPHOST / "integrations/_foreground_process.py"
            or consumer == APPHOST / "integrations/_foreground_stdio.py"
            or consumer == APPHOST / "integrations/_managed_mux_command.py"
            or consumer == APPHOST / "managed/connection.py"
            or consumer == APPHOST / "managed/coordinator.py"
            or consumer == APPHOST / "managed/mux_creation.py"
            or consumer == APPHOST / "managed/mux_management.py"
            or consumer == APPHOST / "managed/registry.py"
            or consumer == APPHOST / "managed/mux_probe.py"
            or consumer.is_relative_to(Path("src/loushang/appservice"))
            or consumer.is_relative_to(Path("src/loushang/harnesstui/mux"))
            or (
                consumer in integration_protocol_values
                and {
                    name for name in _imports(consumer)
                    if name == "loushang.appserver"
                    or name.startswith("loushang.appserver.")
                } <= {
                    "loushang.appserver.protocol",
                    *(f"loushang.appserver.protocol.{name}"
                      for name in integration_protocol_values[consumer]),
                }
            )
        ), consumer
    # Reviewed LMUX receipt decoding and read-only authenticated discovery.
    for filename, expected in {
        "registry.py": {
            "loushang.appserver.managed_mux",
            "loushang.appserver.managed_mux.ManagedMuxCreatedV1",
        },
        "mux_probe.py": {
            "loushang.appserver.local_record",
            "loushang.appserver.local_record.require_endpoint",
            "loushang.appserver.protocol",
            *(f"loushang.appserver.protocol.{name}" for name in (
                "AppErrorCodeV1", "AppServiceError", "MuxReadV1",
                "MuxSelectorV1", "MuxSpaceV1",
            )),
        },
    }.items():
        assert {name for name in _imports(APPHOST / "managed" / filename)
                if name.startswith("loushang.appserver")} == expected
    hosted = _source(HOSTED)
    for forbidden in (
        ".session.",
        ".work.",
        ".projection.",
        ".interaction.",
        "listen(",
        "accept(",
        "subprocess",
        "loushang.hosting",
        "loushang.harness",
    ):
        assert forbidden not in hosted


def test_a0_4_appserver_ports_remain_contract_only_after_g11() -> None:
    ports = APPSERVER / "ports.py"
    imports = _imports(ports)
    for forbidden in (
        "loushang.apphost",
        "loushang.harness",
        "loushang.hosting",
        "asyncio",
        "socket",
    ):
        assert all(
            imported != forbidden and not imported.startswith(f"{forbidden}.")
            for imported in imports
        )
    combined = _source(ports)
    assert "async def " not in combined
    assert " def listen(" not in combined
    assert " def accept(" not in combined
    assert (APPSERVER / "protocol" / "__init__.py").is_file()
    assert (APPSERVER / "client.py").is_file()


def test_a0_3_a0_4_docs_and_quality_gate_are_current() -> None:
    scope = _source(SCOPE)
    contract = _source(CONTRACT)
    appserver = _source(APPSERVER_SCOPE)
    workflow = _source(WORKFLOW)
    assert "A0.3 adds:" in scope
    assert "A0.4 adds one optional" in scope
    assert "A0.3 Live Binding And Embedded Profile" in contract
    assert "A0.4 Hosted Binder" in contract
    assert "contract-only structural Product port bundle" in appserver
    assert "tests/architecture/test_apphost_a03_a04_architecture.py" in workflow
    assert "src/loushang/appserver" in workflow
