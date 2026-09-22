"""Combined Provider for the sealed ``harness.session`` Capability."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar, cast

from loushang.foundation.json import dump_json_value
from loushang.harness.capabilities.contracts import CapabilityContractRange
from loushang.harness.capabilities.packs import (
    CapabilityPack,
    CapabilityPackComposition,
)
from loushang.harness.capabilities.prompt import PreparedPrompt, PromptSection
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityDependencyBinding,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.capabilities.resources_contracts import (
    COMMAND_PACKS_FACET,
    PROMPT_SECTIONS_FACET,
    RESOURCE_RUNTIME_FACET,
    RESOURCES_CAPABILITY_DEFINITION,
    RESOURCES_SESSION_COMPOSITION_REQUIREMENT,
    SKILL_ACTIVATION_FACET,
    TOOL_PACKS_FACET,
)
from loushang.harness.capabilities.session_contracts import (
    COMPACTION_FACET,
    CONVERSATION_STORE_FACET,
    RESOURCE_COMPOSITION_FACET,
    SESSION_CAPABILITY_DEFINITION,
    SIDE_QUESTION_FACET,
    TRANSCRIPT_PROFILE_FACET,
    WORKSPACE_TOOL_OPERATIONS_FACET,
)
from loushang.harness.capabilities.session_contracts import (
    WORKSPACE_PROCESS_LAUNCH_FACET as SESSION_WORKSPACE_PROCESS_LAUNCH_FACET,
)
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_CAPABILITY_DEFINITION,
    WORKSPACE_EDIT_FACET,
    WORKSPACE_LIST_FACET,
    WORKSPACE_PROCESS_LAUNCH_FACET,
    WORKSPACE_READ_FACET,
    WORKSPACE_SEARCH_FACET,
    WORKSPACE_SESSION_COMPOSITION_REQUIREMENT,
    WORKSPACE_WRITE_FACET,
)
from loushang.harness.resources.activation import ResourceActivation
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime.side_question import (
    SideQuestionAnswer,
    SideQuestionCoordinator,
    SideQuestionProvider,
    SideQuestionProviderFactory,
    SideQuestionUpdate,
)
from loushang.harness.session.legacy_side_question import LegacySideQuestionBinding
from loushang.harness.transcript.capability_candidate import (
    AgentTranscriptCapabilityCandidate,
)
from loushang.harness.transcript.compaction import (
    AgentTranscriptCompactionCapability,
)
from loushang.harness.transcript.model_input import (
    ModelInputLogicalProjection,
    ModelInputRuntimeReferences,
    ModelInputTranscriptCommitter,
    RebuiltModelInput,
)
from loushang.harness.workspace.operations import (
    EditOperations,
    FindOperations,
    GrepOperations,
    LsOperations,
    ReadOperations,
    WriteOperations,
)
from loushang.harness.workspace.process import AuthorizedProcessLauncher

T = TypeVar("T")


class _ResourceRuntimeFacet(Protocol):
    def activate(self, bundle: ResourceBundle | None) -> ResourceActivation: ...


class _SkillActivationFacet(Protocol):
    def apply(
        self,
        bundle: ResourceBundle,
        disabled_skills: tuple[str, ...] | list[str],
    ) -> ResourceBundle: ...


class _PromptFacet(Protocol):
    def compose(self, sections: Iterable[PromptSection]) -> PreparedPrompt: ...


class _PackFacet(Protocol):
    def compose(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]: ...


@dataclass(frozen=True)
class _SideQuestionFacet:
    _coordinator: SideQuestionCoordinator | None = field(
        repr=False,
        compare=False,
    )

    async def ask(
        self,
        question: str,
        *,
        on_update: SideQuestionUpdate | None = None,
    ) -> SideQuestionAnswer:
        coordinator = self._coordinator
        if coordinator is None:
            raise RuntimeError("Side questions are not available for this session.")
        return await coordinator.ask(question, on_update=on_update)

    def cancel(self) -> bool:
        coordinator = self._coordinator
        return coordinator.cancel() if coordinator is not None else False

    def owns_current_task(self) -> bool:
        coordinator = self._coordinator
        return coordinator.owns_current_task() if coordinator is not None else False

    async def cancel_and_wait(self) -> bool:
        coordinator = self._coordinator
        if coordinator is None:
            return False
        return await coordinator.cancel_and_wait()


@dataclass(frozen=True)
class _TranscriptFacet:
    _candidate: AgentTranscriptCapabilityCandidate = field(
        repr=False,
        compare=False,
    )

    def create_model_input_committer(
        self,
        *,
        purpose: str,
        logical_input: ModelInputLogicalProjection,
        runtime_references: ModelInputRuntimeReferences,
    ) -> ModelInputTranscriptCommitter:
        return self._candidate.create_model_input_committer(
            purpose=purpose,
            logical_input=logical_input,
            runtime_references=runtime_references,
        )

    def rebuild_model_input(self, snapshot_id: str) -> RebuiltModelInput:
        return self._candidate.rebuild_model_input(snapshot_id)

    def compaction_capability(self) -> AgentTranscriptCompactionCapability:
        return self._candidate.compaction_capability()


@dataclass(frozen=True)
class _ResourceCompositionFacet:
    _dependency: CapabilityDependencyBinding = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._dependency.requirement != RESOURCES_SESSION_COMPOSITION_REQUIREMENT:
            raise ValueError(
                "Session Resource composition received the wrong dependency view"
            )

    def activate(self, bundle: ResourceBundle | None) -> ResourceActivation:
        return cast(
            _ResourceRuntimeFacet,
            self._dependency.require(RESOURCE_RUNTIME_FACET),
        ).activate(bundle)

    def apply_skill_activation(
        self,
        bundle: ResourceBundle,
        disabled_skills: tuple[str, ...] | list[str],
    ) -> ResourceBundle:
        return cast(
            _SkillActivationFacet,
            self._dependency.require(SKILL_ACTIVATION_FACET),
        ).apply(bundle, disabled_skills)

    def compose_prompt(self, sections: Iterable[PromptSection]) -> PreparedPrompt:
        return cast(
            _PromptFacet,
            self._dependency.require(PROMPT_SECTIONS_FACET),
        ).compose(sections)

    def compose_tools(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]:
        return cast(
            _PackFacet,
            self._dependency.require(TOOL_PACKS_FACET),
        ).compose(packs)

    def compose_commands(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]:
        return cast(
            _PackFacet,
            self._dependency.require(COMMAND_PACKS_FACET),
        ).compose(packs)


@dataclass(frozen=True)
class _WorkspaceToolFacet:
    _dependency: CapabilityDependencyBinding | None = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        dependency = self._dependency
        if (
            dependency is not None
            and dependency.requirement != WORKSPACE_SESSION_COMPOSITION_REQUIREMENT
        ):
            raise ValueError(
                "Session Workspace Tool facet received the wrong dependency view"
            )

    def read_operations(self) -> ReadOperations:
        return cast(ReadOperations, self._require(WORKSPACE_READ_FACET))

    def list_operations(self) -> LsOperations:
        return cast(LsOperations, self._require(WORKSPACE_LIST_FACET))

    def find_operations(self) -> FindOperations:
        return cast(FindOperations, self._require(WORKSPACE_SEARCH_FACET))

    def grep_operations(self) -> GrepOperations:
        return cast(GrepOperations, self._require(WORKSPACE_SEARCH_FACET))

    def write_operations(self) -> WriteOperations:
        return cast(WriteOperations, self._require(WORKSPACE_WRITE_FACET))

    def edit_operations(self) -> EditOperations:
        return cast(EditOperations, self._require(WORKSPACE_EDIT_FACET))

    def _require(self, facet_id: str) -> object:
        dependency = self._dependency
        if dependency is None:
            raise RuntimeError("Workspace Capability is not available for this session")
        return dependency.require(facet_id)


@dataclass(frozen=True)
class _WorkspaceProcessFacet:
    _dependency: CapabilityDependencyBinding | None = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        dependency = self._dependency
        if (
            dependency is not None
            and dependency.requirement != WORKSPACE_SESSION_COMPOSITION_REQUIREMENT
        ):
            raise ValueError(
                "Session Workspace Process facet received the wrong dependency view"
            )

    def process_launcher(self) -> AuthorizedProcessLauncher:
        dependency = self._dependency
        if dependency is None:
            raise RuntimeError("Workspace Capability is not available for this session")
        return cast(
            AuthorizedProcessLauncher,
            dependency.require(WORKSPACE_PROCESS_LAUNCH_FACET),
        )


def session_capability_provider_binding(
    *,
    scope_instance_id: str,
    staged_side_question: LegacySideQuestionBinding,
    staged_transcript: AgentTranscriptCapabilityCandidate,
    bind_provider: Callable[[SideQuestionProviderFactory], SideQuestionProvider],
    check_transcript_retirement: Callable[[], None] | None = None,
    provider_id: str = "harness.session.standard",
    source_id: str = "builtin",
) -> CapabilityBundleProviderBinding:
    """Transfer the focused side-question and transcript candidates together.

    ``bind_provider`` is the narrow Product port that binds the selected factory
    to its live Session context. It is never fingerprinted or projected.
    """

    if staged_side_question.ownership_state != "root_owned":
        raise RuntimeError("side-question candidate is not root-owned")
    if staged_transcript.ownership_state != "root_owned":
        raise RuntimeError("transcript candidate is not root-owned")
    provider = CapabilityBundleProvider(
        capability_id=SESSION_CAPABILITY_DEFINITION.capability_id,
        provider_id=provider_id,
        implementation_version=4,
        compatible_contract=CapabilityContractRange.exact(
            SESSION_CAPABILITY_DEFINITION.contract_version
        ),
        facets=SESSION_CAPABILITY_DEFINITION.facets,
        requirements=(
            RESOURCES_SESSION_COMPOSITION_REQUIREMENT,
            WORKSPACE_SESSION_COMPOSITION_REQUIREMENT,
        ),
        source_id=source_id,
        selection_rule="Product-admitted sealed Session selection",
    )

    def create(context: CapabilityProviderContext) -> CapabilityBundleValue:
        resource_facet = _ResourceCompositionFacet(
            context.dependency(RESOURCES_CAPABILITY_DEFINITION.capability_id)
        )
        workspace_dependency = next(
            (
                dependency
                for dependency in context.dependencies
                if dependency.capability_id
                == WORKSPACE_CAPABILITY_DEFINITION.capability_id
            ),
            None,
        )
        workspace_tool_facet = _WorkspaceToolFacet(workspace_dependency)
        workspace_process_facet = _WorkspaceProcessFacet(workspace_dependency)
        side_begun = False
        transcript_begun = False
        try:
            staged_side_question._begin_graph_construction()
            side_begun = True
            staged_transcript._begin_graph_construction()
            transcript_begun = True
            factory = staged_side_question.provider_factory
            if factory is None:
                coordinator = None
            else:
                selected_provider = bind_provider(factory)
                if inspect.isawaitable(selected_provider):
                    close = getattr(selected_provider, "close", None)
                    if callable(close):
                        close()
                    raise TypeError(
                        "side-question Provider binding must be synchronous"
                    )
                if not callable(
                    getattr(selected_provider, "ask", None)
                ) or not callable(getattr(selected_provider, "cancel", None)):
                    raise TypeError(
                        "side-question factory returned an invalid Provider"
                    )
                coordinator = SideQuestionCoordinator(selected_provider)
            transcript_facet = _TranscriptFacet(staged_transcript)
            value = CapabilityBundleValue(
                facets=(
                    CapabilityFacetBinding(
                        SIDE_QUESTION_FACET,
                        _SideQuestionFacet(coordinator),
                    ),
                    CapabilityFacetBinding(
                        CONVERSATION_STORE_FACET,
                        transcript_facet,
                    ),
                    CapabilityFacetBinding(
                        TRANSCRIPT_PROFILE_FACET,
                        transcript_facet,
                    ),
                    CapabilityFacetBinding(COMPACTION_FACET, transcript_facet),
                    CapabilityFacetBinding(
                        RESOURCE_COMPOSITION_FACET,
                        resource_facet,
                    ),
                    CapabilityFacetBinding(
                        WORKSPACE_TOOL_OPERATIONS_FACET,
                        workspace_tool_facet,
                    ),
                    CapabilityFacetBinding(
                        SESSION_WORKSPACE_PROCESS_LAUNCH_FACET,
                        workspace_process_facet,
                    ),
                )
            )
            staged_side_question._commit_graph_ownership()
            staged_transcript._commit_graph_ownership()
        except BaseException:
            if transcript_begun and staged_transcript.ownership_state in {
                "graph_constructing",
                "graph_owned",
            }:
                staged_transcript._rollback_unpublished_graph_ownership()
            if side_begun and staged_side_question.ownership_state in {
                "graph_constructing",
                "graph_owned",
            }:
                staged_side_question._rollback_unpublished_graph_ownership()
            raise
        return value

    async def dispose(value: CapabilityBundleValue) -> None:
        # Binding failure may reach this disposer before the Product's outer
        # rollback. Never wait under Graph locks for an active output capture.
        if check_transcript_retirement is not None:
            check_transcript_retirement()
        facet = value.require(SIDE_QUESTION_FACET)
        if not isinstance(facet, _SideQuestionFacet):
            raise TypeError("Session Provider received an alien Bundle value")
        errors: list[BaseException] = []
        try:
            await facet.cancel_and_wait()
        except BaseException as exc:
            errors.append(exc)
        try:
            staged_side_question._dispose_graph_owned()
        except BaseException as exc:
            errors.append(exc)
        try:
            await staged_transcript.publish_index_summary()
        except BaseException as exc:
            errors.append(exc)
        try:
            await staged_transcript._dispose_graph_owned()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            primary = errors[0]
            for cleanup_error in errors[1:]:
                primary.add_note(
                    f"Additional Session Provider cleanup failure: {cleanup_error!r}"
                )
            raise primary

    return CapabilityBundleProviderBinding(
        provider=provider,
        scope_instance_id=scope_instance_id,
        binding_input_fingerprint=_binding_input_fingerprint(
            staged_side_question=staged_side_question,
            staged_transcript=staged_transcript,
            scope_instance_id=scope_instance_id,
            provider_id=provider_id,
        ),
        create=create,
        dispose=dispose,
    )


def _binding_input_fingerprint(
    *,
    staged_side_question: LegacySideQuestionBinding,
    staged_transcript: AgentTranscriptCapabilityCandidate,
    scope_instance_id: str,
    provider_id: str,
) -> str:
    payload = dump_json_value(
        {
            "schemaVersion": 1,
            "capabilityId": SESSION_CAPABILITY_DEFINITION.capability_id,
            "contractVersion": SESSION_CAPABILITY_DEFINITION.contract_version,
            "providerId": provider_id,
            "providerVersion": 4,
            "scopeInstanceId": scope_instance_id,
            "sideQuestionProfile": staged_side_question.profile.snapshot().to_json(),
            "transcriptProfile": staged_transcript.runtime_profile_snapshot.to_json(),
        },
        name="Session binding-input fingerprint",
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = ["session_capability_provider_binding"]
