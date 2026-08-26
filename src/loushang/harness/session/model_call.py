"""Current-Session adapter for Agent sampling and AI's transport barrier."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Protocol, cast

from loushang.agent import ModelCallPreparation
from loushang.ai.json_codec import serialize_message
from loushang.ai.options import CallOptions
from loushang.ai.prepared_request import (
    PreparedModelCallAttemptUsage,
    PreparedModelCallAttemptUsageRecorder,
    PreparedModelCallOutcome,
    PreparedModelCallOutcomeRecorder,
    PreparedModelRequest,
    PreparedRequestCommitter,
)
from loushang.ai.structured import StructuredOutputOptions
from loushang.foundation.json import JSONValue, require_json_mapping, require_json_value
from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityContractRange,
    CapabilityDependencyBinding,
    CapabilityFacetBinding,
    CapabilityProviderContext,
    EffectiveRuntimeDiff,
    EffectiveRuntimeView,
    ModelSurfaceReference,
    RegistrationExplanation,
    RegistrationInventoryEntry,
    RegistrationInventorySnapshot,
    RuntimeCapabilityGraphProjector,
    RuntimeProfileSlotExplanation,
    ScopedSourcePublicationReference,
)
from loushang.harness.capabilities.effective_runtime import (
    compose_registration_inventory,
)
from loushang.harness.capabilities.graph_projection import CapabilityGraphExplanation
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.model_input_contracts import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    MODEL_INPUT_PREPARATION_FACET,
    MODEL_INPUT_PREPARATION_REQUIREMENT,
)
from loushang.harness.capabilities.session_contracts import (
    SESSION_CAPABILITY_DEFINITION,
    SESSION_TRANSCRIPT_REQUIREMENT,
    TRANSCRIPT_PROFILE_FACET,
)
from loushang.harness.runtime import RuntimeProfileSnapshot
from loushang.harness.session.turn_performance import TurnStartPerformanceRuntime
from loushang.harness.transcript import (
    ModelCallAttemptUsage,
    ModelInputRuntimeReferences,
)
from loushang.harness.transcript.model_input import (
    ModelInputTranscriptCommitter,
    RebuiltModelInput,
)

CurrentSessionPredicate = Callable[[], bool]
RegistrationEntriesProvider = Callable[[], tuple[RegistrationInventoryEntry, ...]]
CurrentProfileFingerprintProvider = Callable[[], str]
SourcePublicationProvider = Callable[[], ScopedSourcePublicationReference | None]


class ModelInputTranscriptPort(Protocol):
    def create_model_input_committer(
        self,
        *,
        purpose: str,
        logical_input: dict[str, object],
        runtime_references: ModelInputRuntimeReferences,
    ) -> ModelInputTranscriptCommitter: ...

    def rebuild_model_input(self, snapshot_id: str) -> RebuiltModelInput: ...


@dataclass(frozen=True)
class _DependencyModelInputTranscriptPort:
    """Expose only Model Input operations from the declared Session dependency."""

    dependency: CapabilityDependencyBinding

    def create_model_input_committer(
        self,
        *,
        purpose: str,
        logical_input: dict[str, object],
        runtime_references: ModelInputRuntimeReferences,
    ) -> ModelInputTranscriptCommitter:
        return self._facet().create_model_input_committer(
            purpose=purpose,
            logical_input=logical_input,
            runtime_references=runtime_references,
        )

    def rebuild_model_input(self, snapshot_id: str) -> RebuiltModelInput:
        return self._facet().rebuild_model_input(snapshot_id)

    def _facet(self) -> ModelInputTranscriptPort:
        value = self.dependency.require(TRANSCRIPT_PROFILE_FACET)
        _require_transcript_port(value, name="model-input Session dependency")
        return cast(ModelInputTranscriptPort, value)


class SessionModelCallPreparer:
    """Bind one fresh transcript committer to a final Agent-level model input."""

    def __init__(
        self,
        *,
        transcript: ModelInputTranscriptPort,
        projector: RuntimeCapabilityGraphProjector,
        is_current: CurrentSessionPredicate,
        registration_entries_provider: RegistrationEntriesProvider,
        profile_fingerprint_provider: CurrentProfileFingerprintProvider,
        turn_performance: TurnStartPerformanceRuntime | None = None,
    ) -> None:
        _require_transcript_port(transcript, name="model-call preparation")
        if not isinstance(projector, RuntimeCapabilityGraphProjector):
            raise TypeError("model-call preparation requires graph projection")
        if not callable(is_current):
            raise TypeError("model-call preparation requires a current-Session check")
        if not callable(registration_entries_provider):
            raise TypeError("model-call preparation requires registration inventory")
        if not callable(profile_fingerprint_provider):
            raise TypeError("model-call preparation requires current Profile facts")
        self._transcript = transcript
        self._projector = projector
        self._is_current = is_current
        self._registration_entries_provider = registration_entries_provider
        self._profile_fingerprint_provider = profile_fingerprint_provider
        self._turn_performance = turn_performance

    def __call__(self, preparation: ModelCallPreparation) -> CallOptions:
        if not isinstance(preparation, ModelCallPreparation):
            raise TypeError("model-call preparation requires ModelCallPreparation")
        if self._is_current() is not True:
            raise RuntimeError("Session is not current; model transport is forbidden")
        if preparation.options.prepared_request_committer is not None:
            raise RuntimeError(
                "durable Session cannot replace an existing prepared-request committer"
            )

        if self._turn_performance is not None:
            self._turn_performance.model_call_prepare_started(preparation)
        try:
            graph = self._projector.snapshot()
            registrations = compose_registration_inventory(
                self._projector.registration_inventory(),
                self._registration_entries_provider(),
            )
            committer = self._transcript.create_model_input_committer(
                purpose=preparation.purpose,
                logical_input=_logical_input(preparation),
                runtime_references=ModelInputRuntimeReferences.from_snapshots(
                    graph,
                    registrations,
                    profile_fingerprint=self._profile_fingerprint_provider(),
                ),
            )
            options = replace(
                preparation.options,
                prepared_request_committer=_CurrentSessionCommitter(
                    committer=committer,
                    is_current=self._is_current,
                    turn_performance=self._turn_performance,
                ),
            )
        except BaseException:
            if self._turn_performance is not None:
                self._turn_performance.model_call_prepare_failed()
            raise
        if self._turn_performance is not None:
            self._turn_performance.model_call_prepared()
        return options


class _CurrentSessionCommitter(
    PreparedRequestCommitter,
    PreparedModelCallAttemptUsageRecorder,
    PreparedModelCallOutcomeRecorder,
):
    """Carry current-Session ownership through AI's final commit barrier."""

    def __init__(
        self,
        *,
        committer: PreparedRequestCommitter,
        is_current: CurrentSessionPredicate,
        turn_performance: TurnStartPerformanceRuntime | None = None,
    ) -> None:
        self._committer = committer
        self._is_current = is_current
        self._turn_performance = turn_performance
        self._latest_attempt_by_invocation: dict[str, tuple[int, str]] = {}

    async def commit_prepared_request(self, request: PreparedModelRequest) -> None:
        self._require_current()
        if self._turn_performance is not None:
            self._turn_performance.model_input_commit_started(request)
        try:
            await self._committer.commit_prepared_request(request)
        except BaseException:
            if self._turn_performance is not None:
                self._turn_performance.model_input_commit_failed(request)
            raise
        self._require_current()
        commits = getattr(self._committer, "commits", ())
        if not commits:
            raise RuntimeError("durable Model Input commit produced no snapshot")
        snapshot_id = getattr(commits[-1], "snapshot_id", None)
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise RuntimeError("durable Model Input commit produced no snapshot id")
        self._latest_attempt_by_invocation[request.invocation_id] = (
            request.attempt,
            snapshot_id,
        )
        if self._turn_performance is not None:
            self._turn_performance.transport_ready(request)

    async def record_prepared_model_call_attempt_usage(
        self,
        observation: PreparedModelCallAttemptUsage,
    ) -> bool:
        self._require_current()
        if not isinstance(self._committer, ModelInputTranscriptCommitter):
            raise TypeError(
                "durable Session Model Input committer cannot record attempt usage"
            )
        attempt_identity = self._latest_attempt_by_invocation.get(
            observation.invocation_id
        )
        if attempt_identity is None:
            raise RuntimeError(
                "attempt usage has no committed Model Input snapshot identity"
            )
        attempt, snapshot_id = attempt_identity
        usage = observation.usage
        recorded = await self._committer.record_model_call_attempt_usage(
            ModelCallAttemptUsage(
                invocation_id=observation.invocation_id,
                attempt=attempt,
                model_input_snapshot_id=snapshot_id,
                input=usage.input,
                output=usage.output,
                cache_read=usage.cache_read,
                cache_write=usage.cache_write,
                total_tokens=usage.total_tokens,
                terminal=observation.terminal,
            )
        )
        self._require_current()
        return recorded

    async def record_model_call_outcome(
        self,
        outcome: PreparedModelCallOutcome,
    ) -> None:
        self._require_current()
        if not isinstance(self._committer, PreparedModelCallOutcomeRecorder):
            raise TypeError(
                "durable Session Model Input committer cannot record outcomes"
            )
        await self._committer.record_model_call_outcome(outcome)
        self._require_current()

    @property
    def model_input_snapshot_ids(self) -> tuple[str, ...]:
        commits = getattr(self._committer, "commits", ())
        return tuple(
            commit.snapshot_id
            for commit in commits
            if isinstance(getattr(commit, "snapshot_id", None), str)
        )

    def _require_current(self) -> None:
        if self._is_current() is not True:
            raise RuntimeError("Session is not current; model transport is forbidden")


@dataclass(frozen=True)
class SessionModelCallCapabilityConsumer:
    """Adapt the declared preparation facet without receiving the graph runtime."""

    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != MODEL_INPUT_PREPARATION_REQUIREMENT:
            raise ValueError("model-call Consumer received the wrong facet view")

    def prepare(self, preparation: ModelCallPreparation) -> CallOptions:
        preparer = cast(
            SessionModelCallPreparer,
            self.facets.require(MODEL_INPUT_PREPARATION_FACET),
        )
        return preparer(preparation)


@dataclass(frozen=True)
class SessionModelCallCapabilityBinding:
    """Immutable built-in Provider input for the Session composition root."""

    provider_binding: CapabilityBundleProviderBinding


def build_session_model_call_capability_binding(
    *,
    transcript: ModelInputTranscriptPort,
    projector: RuntimeCapabilityGraphProjector,
    product_id: str,
    runtime_id: str,
    is_current: CurrentSessionPredicate,
    registration_entries_provider: RegistrationEntriesProvider,
    profile_fingerprint_provider: CurrentProfileFingerprintProvider,
    conversation_id: str | None = None,
    session_provider: CapabilityBundleProvider | None = None,
    resources_provider: CapabilityBundleProvider | None = None,
    workspace_provider: CapabilityBundleProvider | None = None,
    turn_performance: TurnStartPerformanceRuntime | None = None,
) -> SessionModelCallCapabilityBinding:
    """Build data-only graph inputs without acquiring graph lifecycle authority."""

    if resources_provider is not None and session_provider is None:
        raise ValueError(
            "model-call binding cannot use a Resources Provider without a Session Provider"
        )
    if workspace_provider is not None and session_provider is None:
        raise ValueError(
            "model-call binding cannot use a Workspace Provider without a Session Provider"
        )
    if session_provider is not None and resources_provider is None:
        raise ValueError(
            "model-call binding requires the Session Provider's Resources dependency"
        )
    _require_transcript_port(transcript, name="model-call binding")
    if not isinstance(projector, RuntimeCapabilityGraphProjector):
        raise TypeError("model-call binding requires graph projection")
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("model-call binding Product id must be non-empty")
    if not isinstance(runtime_id, str) or not runtime_id.strip():
        raise ValueError("model-call binding runtime id must be non-empty")
    for callback, name in (
        (is_current, "current-Session check"),
        (registration_entries_provider, "registration inventory"),
        (profile_fingerprint_provider, "current Profile facts"),
    ):
        if not callable(callback):
            raise TypeError(f"model-call binding requires {name}")

    resolved_conversation_id = conversation_id or getattr(
        getattr(transcript, "header", None),
        "conversation_id",
        None,
    )
    if not isinstance(resolved_conversation_id, str) or not resolved_conversation_id:
        raise ValueError("model-call binding requires a conversation id")

    provider = CapabilityBundleProvider(
        capability_id=MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
        provider_id="harness.model_input.standard",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=MODEL_INPUT_CAPABILITY_DEFINITION.facets,
        requirements=(
            (SESSION_TRANSCRIPT_REQUIREMENT,) if session_provider is not None else ()
        ),
        required_authorities=frozenset({"transcript"}),
        source_id="builtin",
        selection_rule="Product durable Model Input selection",
    )
    def build_value(
        transcript_port: ModelInputTranscriptPort,
    ) -> CapabilityBundleValue:
        return CapabilityBundleValue(
            (
                CapabilityFacetBinding(
                    MODEL_INPUT_PREPARATION_FACET,
                    SessionModelCallPreparer(
                        transcript=transcript_port,
                        projector=projector,
                        is_current=is_current,
                        registration_entries_provider=registration_entries_provider,
                        profile_fingerprint_provider=profile_fingerprint_provider,
                        turn_performance=turn_performance,
                    ),
                ),
            )
        )

    if session_provider is None:

        def create(context: CapabilityProviderContext) -> CapabilityBundleValue:
            del context
            return build_value(transcript)

    else:

        def create(context: CapabilityProviderContext) -> CapabilityBundleValue:
            return build_value(
                _DependencyModelInputTranscriptPort(
                    context.dependency(SESSION_CAPABILITY_DEFINITION.capability_id)
                )
            )

    return SessionModelCallCapabilityBinding(
        provider_binding=CapabilityBundleProviderBinding(
            provider=provider,
            scope_instance_id=runtime_id,
            binding_input_fingerprint=_fingerprint(
                {
                    "conversation_id": resolved_conversation_id,
                    "runtime_id": runtime_id,
                }
            ),
            create=create,
        ),
    )


class SessionModelCallRuntime:
    """Consume the Session-owned model-input facet and read-only projection."""

    def __init__(
        self,
        *,
        transcript: ModelInputTranscriptPort,
        ensure_consumer: Callable[[], Awaitable[SessionModelCallCapabilityConsumer]],
        projector: RuntimeCapabilityGraphProjector,
        registration_entries_provider: RegistrationEntriesProvider | None = None,
        source_publication_provider: SourcePublicationProvider | None = None,
    ) -> None:
        _require_transcript_port(transcript, name="model-call runtime")
        if not callable(ensure_consumer):
            raise TypeError("model-call runtime requires a typed Consumer port")
        if not isinstance(projector, RuntimeCapabilityGraphProjector):
            raise TypeError("model-call runtime requires graph projection")
        if registration_entries_provider is not None and not callable(
            registration_entries_provider
        ):
            raise TypeError(
                "model-call runtime registration inventory must be callable"
            )
        if source_publication_provider is not None and not callable(
            source_publication_provider
        ):
            raise TypeError("model-call runtime source publication must be callable")

        self._transcript = transcript
        self._ensure_consumer = ensure_consumer
        self._projector = projector
        self._registration_entries_provider = registration_entries_provider or (
            lambda: ()
        )
        self._source_publication_provider = source_publication_provider or (
            lambda: None
        )

    def effective_view(
        self,
        profile: RuntimeProfileSnapshot,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> EffectiveRuntimeView:
        return self._projector.effective_view(
            profile,
            model_surface=self._model_surface(model_input_snapshot_id),
            registrations=self._registration_inventory(),
            source_publication=self._source_publication_provider(),
        )

    def explain_capability(
        self,
        profile: RuntimeProfileSnapshot,
        capability_id: str,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> CapabilityGraphExplanation:
        model_surface = self._model_surface(model_input_snapshot_id)
        return self._projector.explain(
            capability_id,
            profile=profile,
            model_surface=model_surface,
            registrations=self._registration_inventory(),
            source_publication=self._source_publication_provider(),
        )

    def explain_profile_slot(
        self,
        profile: RuntimeProfileSnapshot,
        slot: str,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> RuntimeProfileSlotExplanation:
        return self._projector.explain_profile_slot(
            profile,
            slot,
            model_surface=self._model_surface(model_input_snapshot_id),
            registrations=self._registration_inventory(),
        )

    def explain_registration(
        self,
        profile: RuntimeProfileSnapshot,
        registration_id: str,
        *,
        model_input_snapshot_id: str | None = None,
    ) -> RegistrationExplanation:
        return self._projector.explain_registration(
            registration_id,
            profile=profile,
            model_surface=self._model_surface(model_input_snapshot_id),
            registrations=self._registration_inventory(),
        )

    def diff(
        self,
        before: EffectiveRuntimeView,
        after: EffectiveRuntimeView,
    ) -> EffectiveRuntimeDiff:
        return self._projector.diff(before, after)

    def to_json(
        self,
        value: EffectiveRuntimeView
        | EffectiveRuntimeDiff
        | CapabilityGraphExplanation
        | RuntimeProfileSlotExplanation
        | RegistrationExplanation,
    ) -> dict[str, JSONValue]:
        return self._projector.to_json(value)

    async def prepare(self, preparation: ModelCallPreparation) -> CallOptions:
        consumer = await self._ensure_consumer()
        return consumer.prepare(preparation)

    def _registration_inventory(self) -> RegistrationInventorySnapshot:
        return compose_registration_inventory(
            self._projector.registration_inventory(),
            self._registration_entries_provider(),
        )

    def _model_surface(
        self,
        snapshot_id: str | None,
    ) -> ModelSurfaceReference | None:
        if snapshot_id is None:
            return None
        snapshot = self._transcript.rebuild_model_input(snapshot_id).snapshot
        return ModelSurfaceReference(
            schema_version=1,
            snapshot_id=snapshot.snapshot_id,
            product_id=snapshot.product_id,
            runtime_id=snapshot.runtime_id,
            profile_fingerprint=snapshot.profile_fingerprint,
            mount_generation=snapshot.mount_generation,
            registration_revision=snapshot.registration_revision,
        )


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_transcript_port(
    value: object,
    *,
    name: str,
) -> None:
    if not callable(getattr(value, "create_model_input_committer", None)):
        raise TypeError(f"{name} requires a Model Input transcript port")
    if not callable(getattr(value, "rebuild_model_input", None)):
        raise TypeError(f"{name} requires a Model Input transcript port")


def _logical_input(preparation: ModelCallPreparation) -> dict[str, object]:
    context = preparation.context
    return {
        "system_prompt": context.system_prompt,
        "messages": [serialize_message(message) for message in context.messages],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": require_json_mapping(
                    tool.parameters,
                    name=f"Model Input Tool schema {tool.name!r}",
                ),
            }
            for tool in context.tools or ()
        ],
        "request_options": _request_options(preparation.options),
    }


def _request_options(options: CallOptions) -> dict[str, JSONValue]:
    projected: dict[str, JSONValue] = {}
    for name in (
        "cache_retention",
        "cache_key",
        "max_output_tokens",
        "temperature",
    ):
        value = getattr(options, name)
        if value is not None:
            projected[name] = require_json_value(
                value,
                name=f"Model Input request option {name!r}",
            )

    if options.reasoning is not None:
        projected["reasoning"] = require_json_mapping(
            {
                "enabled": options.reasoning.enabled,
                "effort": options.reasoning.effort,
                "budget_tokens": options.reasoning.budget_tokens,
                "expose_summary": options.reasoning.expose_summary,
            },
            name="Model Input reasoning options",
        )
    if options.tool_choice is not None:
        projected["tool_choice"] = require_json_value(
            options.tool_choice,
            name="Model Input Tool choice",
        )
    if options.output is not None:
        projected["output"] = _structured_output(options.output)
    if options.request_limits is not None:
        projected["request_limits"] = require_json_mapping(
            {
                name: value
                for name in (
                    "max_canonical_bytes",
                    "max_estimated_wire_bytes",
                    "max_message_count",
                    "max_image_bytes",
                    "max_tool_schema_bytes",
                    "max_estimated_input_tokens",
                )
                if (value := getattr(options.request_limits, name)) is not None
            },
            name="Model Input request capacity limits",
        )
    return projected


def _structured_output(output: StructuredOutputOptions) -> dict[str, JSONValue]:
    projected: dict[str, object] = {
        "mode": output.mode,
        "strict": output.strict,
    }
    if output.schema is not None:
        projected["schema"] = _structured_output_schema(output.schema)
    return require_json_mapping(projected, name="Model Input structured output")


def _structured_output_schema(
    schema: Mapping[str, JSONValue] | type,
) -> dict[str, JSONValue]:
    if isinstance(schema, Mapping):
        return require_json_mapping(schema, name="Model Input structured output schema")
    for method_name in ("model_json_schema", "schema"):
        method = getattr(schema, method_name, None)
        if callable(method):
            value = method()
            if isinstance(value, Mapping):
                return require_json_mapping(
                    value,
                    name="Model Input structured output schema",
                )
    raise TypeError("structured output type must expose a JSON schema")


__all__ = [
    "CurrentSessionPredicate",
    "SessionModelCallCapabilityConsumer",
    "SessionModelCallPreparer",
    "SessionModelCallRuntime",
]
