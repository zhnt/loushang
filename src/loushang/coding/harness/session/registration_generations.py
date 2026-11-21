"""Stage and retire admitted Session Tool and Command registrations."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from loushang.coding.composition import base_owners as _product
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_EDIT_FACET,
    WORKSPACE_LIST_FACET,
    WORKSPACE_PROCESS_LAUNCH_FACET,
    WORKSPACE_READ_FACET,
    WORKSPACE_SEARCH_FACET,
    WORKSPACE_WRITE_FACET,
)
from loushang.harness.runtime.registration import RegistrationOwner, RegistrationScope
from loushang.harness.session.capability_composition_inputs import (
    OwnerGenerationDispose,
    OwnerGenerationStage,
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
)
from loushang.harness.session.command_controller import SessionCommandGenerationRegistry
from loushang.harness.session.commands.catalog import (
    list_standard_session_command_descriptors,
)
from loushang.harness.session.tool_owner_binding import SessionToolRegistrationPort
from loushang.harness.tools.workspace.bash import BashOperations
from loushang.harness.tools.workspace.factory import ToolsOptions
from loushang.harness.workspace.exec import AuthorizedProcessExecBackend, ExecService
from loushang.harness.workspace.generation_bindings import GenerationBoundOperationSet
from loushang.harness.workspace.operations import (
    EditOperations,
    FindOperations,
    GrepOperations,
    LsOperations,
    ReadOperations,
    WriteOperations,
)
from loushang.harness.workspace.process import AuthorizedProcessLauncher


def stage_workspace_tools(
    owner_adapter: _product.CodingBaseToolOwner,
    captures: tuple[SessionCapabilityConsumerCapture, ...],
    *,
    registration: SessionToolRegistrationPort,
    label: str,
) -> _product._CodingBaseGeneration:
    """Stage the admitted pack under the workspace operation generation."""
    options, operation_set = owner_adapter._options_from_capture(captures)
    tool_names = _product._tool_identities(owner_adapter.admission.contribution_id)
    owner = _registration_owner(owner_adapter.admission, owner_adapter.scope_id)
    scope = RegistrationScope(owner)
    source_info = _product._CodingBaseSourceInfo(
        plugin_id=owner_adapter.admission.plugin_id,
        contribution_id=owner_adapter.admission.contribution_id,
        admission_fingerprint=owner_adapter.admission.fingerprint,
    )
    try:
        by_name = {
            item.name: item
            for item in _product.create_coding_builtin_tool_definitions(options=options)
        }
        if set(by_name) != set(tool_names):
            raise RuntimeError(f"{label} catalog changed admitted identities")
        for name in tool_names:
            scope.add(
                registration.stage_runtime_tool(
                    by_name[name],
                    owner=owner,
                    source_info=source_info,
                )
            )
    except BaseException as error:
        operation_set.invalidate(_product._FAILED_WORKSPACE_GENERATION)
        _rollback_scope(scope, error, label=label)
        raise
    return _product._CodingBaseGeneration(
        scope=scope,
        kind="tool",
        operation_set=operation_set,
    )


def workspace_options_from_capture(
    owner_adapter: _product.CodingBaseToolOwner,
    capture: SessionCapabilityConsumerCapture,
    *,
    label: str,
) -> tuple[ToolsOptions, GenerationBoundOperationSet]:
    """Capture the admitted facets into one revocable workspace binding."""
    facets = capture.facets
    launcher = facets.require(WORKSPACE_PROCESS_LAUNCH_FACET)
    if not callable(getattr(launcher, "start", None)):
        raise TypeError(f"{label} process facet is invalid")
    process_operations = ExecService(
        backend=AuthorizedProcessExecBackend(cast(AuthorizedProcessLauncher, launcher))
    )
    operation_set = GenerationBoundOperationSet(
        {
            "process": process_operations,
            "read": facets.require(WORKSPACE_READ_FACET),
            "list": facets.require(WORKSPACE_LIST_FACET),
            "search": facets.require(WORKSPACE_SEARCH_FACET),
            "write": facets.require(WORKSPACE_WRITE_FACET),
            "edit": facets.require(WORKSPACE_EDIT_FACET),
        },
        stale_message=_product._STALE_WORKSPACE_GENERATION,
    )
    return replace(
        owner_adapter.options,
        exec_service=None,
        bash_operations=cast(BashOperations, operation_set.capture("process")),
        shell_operations=cast(BashOperations, operation_set.capture("process")),
        read_operations=cast(ReadOperations, operation_set.capture("read")),
        ls_operations=cast(LsOperations, operation_set.capture("list")),
        find_operations=cast(FindOperations, operation_set.capture("search")),
        grep_operations=cast(GrepOperations, operation_set.capture("search")),
        write_operations=cast(WriteOperations, operation_set.capture("write")),
        edit_operations=cast(EditOperations, operation_set.capture("edit")),
    ), operation_set


def stage_commands(
    owner_adapter: _product.CodingBaseCommandOwner,
    captures: tuple[SessionCapabilityConsumerCapture, ...],
    *,
    registry: SessionCommandGenerationRegistry,
    label: str,
) -> _product._CodingBaseGeneration:
    """Stage the exact admitted Command catalog without publishing it."""
    if captures:
        raise ValueError(f"{label} owner declares no Consumers")
    descriptors = tuple(list_standard_session_command_descriptors())
    if tuple(sorted(item.name for item in descriptors)) != _product._COMMAND_NAMES:
        raise RuntimeError(f"{label} catalog changed admitted identities")
    owner = _registration_owner(owner_adapter.admission, owner_adapter.scope_id)
    scope = RegistrationScope(owner)
    try:
        scope.add(
            registry.stage_pack(
                descriptors,
                owner=owner,
                pack_id=_product._COMMAND_CATALOG_ID,
            )
        )
    except BaseException as error:
        _rollback_scope(scope, error, label=label)
        raise
    return _product._CodingBaseGeneration(scope=scope, kind="command")


def bind_registration_owner(
    admission: OwnerContributionAdmissionRecord,
    authority_gate: SessionCapabilityOwnerAuthorityGate,
    *,
    stage: OwnerGenerationStage,
    dispose: OwnerGenerationDispose,
    label: str,
) -> SessionCapabilityOwnerGenerationBinding:
    """Hand the staged scope to the existing capability Graph lifecycle."""

    def require_generation(value: object) -> _product._CodingBaseGeneration:
        if not isinstance(value, _product._CodingBaseGeneration):
            raise TypeError(f"{label} owner received a foreign generation")
        return value

    return SessionCapabilityOwnerGenerationBinding(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=admission.plugin_id,
        contribution_id=admission.contribution_id,
        admission_fingerprint=admission.fingerprint,
        authority_gate=authority_gate,
        stage=stage,
        dispose=dispose,
        retirement_receipt=lambda value: require_generation(value).retirement_receipt(
            contribution_id=admission.contribution_id,
        ),
        commit=lambda value: require_generation(value).commit(),
        rollback_commit=lambda value: require_generation(value).rollback_commit(),
    )


async def dispose_registration_generation(
    generation: _product._CodingBaseGeneration,
) -> None:
    """Revoke captured workspace operations before disposing the leases."""
    if generation.operation_set is not None:
        generation.operation_set.invalidate(_product._STALE_WORKSPACE_GENERATION)
    report = await generation.scope.dispose()
    if report.has_failures:
        raise _product._generation_disposal_error(generation.kind)


def _registration_owner(
    admission: OwnerContributionAdmissionRecord,
    scope_id: str,
) -> RegistrationOwner:
    return RegistrationOwner(
        owner_kind="product",
        owner_id=admission.owner_id,
        runtime_id=(f"{scope_id}:{admission.plugin_id}:{admission.contribution_id}"),
        generation=admission.candidate.instance_revision_ref.revision,
    )


def _rollback_scope(
    scope: RegistrationScope,
    error: BaseException,
    *,
    label: str,
) -> None:
    if scope.state == "committed":
        scope.rollback_commit()
    if scope.state == "open":
        rollback = scope.rollback_admission()
        if rollback.has_failures:
            error.add_note(f"{label} rollback remains incomplete")
