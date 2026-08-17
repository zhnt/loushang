"""Current-Session adapter for Agent sampling and AI's transport barrier."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import cast

from loushang.agent import ModelCallPreparation
from loushang.ai.json_codec import serialize_message
from loushang.ai.options import CallOptions
from loushang.ai.prepared_request import (
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
    CapabilityFacetBinding,
    CapabilityGraphPlanRequest,
    CapabilityProviderContext,
    EffectiveRuntimeDiff,
    EffectiveRuntimeView,
    ModelSurfaceReference,
    RegistrationExplanation,
    RegistrationInventoryEntry,
    RegistrationInventorySnapshot,
    RuntimeCapabilityGraphPlan,
    RuntimeCapabilityGraphPlanner,
    RuntimeCapabilityGraphProjector,
    RuntimeProfileSlotExplanation,
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
from loushang.harness.runtime import RuntimeProfileSnapshot
from loushang.harness.transcript import (
    AgentTranscriptSession,
    ModelInputRuntimeReferences,
)

CurrentSessionPredicate = Callable[[], bool]
RegistrationEntriesProvider = Callable[[], tuple[RegistrationInventoryEntry, ...]]
CurrentProfileFingerprintProvider = Callable[[], str]


class SessionModelCallPreparer:
    """Bind one fresh transcript committer to a final Agent-level model input."""

    def __init__(
        self,
        *,
        transcript: AgentTranscriptSession,
        projector: RuntimeCapabilityGraphProjector,
        is_current: CurrentSessionPredicate,
        registration_entries_provider: RegistrationEntriesProvider,
        profile_fingerprint_provider: CurrentProfileFingerprintProvider,
    ) -> None:
        if not isinstance(transcript, AgentTranscriptSession):
            raise TypeError("model-call preparation requires AgentTranscriptSession")
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

    def __call__(self, preparation: ModelCallPreparation) -> CallOptions:
        if not isinstance(preparation, ModelCallPreparation):
            raise TypeError("model-call preparation requires ModelCallPreparation")
        if self._is_current() is not True:
            raise RuntimeError("Session is not current; model transport is forbidden")
        if preparation.options.prepared_request_committer is not None:
            raise RuntimeError(
                "durable Session cannot replace an existing prepared-request committer"
            )

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
        return replace(
            preparation.options,
            prepared_request_committer=_CurrentSessionCommitter(
                committer=committer,
                is_current=self._is_current,
            ),
        )


class _CurrentSessionCommitter(
    PreparedRequestCommitter,
    PreparedModelCallOutcomeRecorder,
):
    """Carry current-Session ownership through AI's final commit barrier."""

    def __init__(
        self,
        *,
        committer: PreparedRequestCommitter,
        is_current: CurrentSessionPredicate,
    ) -> None:
        self._committer = committer
        self._is_current = is_current

    async def commit_prepared_request(self, request: PreparedModelRequest) -> None:
        self._require_current()
        await self._committer.commit_prepared_request(request)
        self._require_current()

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
    """Immutable graph inputs assembled for the Session composition root."""

    plan: RuntimeCapabilityGraphPlan
    provider_binding: CapabilityBundleProviderBinding


def build_session_model_call_capability_binding(
    *,
    transcript: AgentTranscriptSession,
    projector: RuntimeCapabilityGraphProjector,
    product_id: str,
    runtime_id: str,
    is_current: CurrentSessionPredicate,
    registration_entries_provider: RegistrationEntriesProvider,
    profile_fingerprint_provider: CurrentProfileFingerprintProvider,
) -> SessionModelCallCapabilityBinding:
    """Build data-only graph inputs without acquiring graph lifecycle authority."""

    if not isinstance(transcript, AgentTranscriptSession):
        raise TypeError("model-call binding requires AgentTranscriptSession")
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

    provider = CapabilityBundleProvider(
        capability_id=MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
        provider_id="harness.model_input.standard",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=MODEL_INPUT_CAPABILITY_DEFINITION.facets,
        required_authorities=frozenset({"transcript"}),
        source_id="builtin",
        selection_rule="Product durable Model Input selection",
    )
    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id=product_id,
            roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
            definitions=(MODEL_INPUT_CAPABILITY_DEFINITION,),
            providers=(provider,),
        )
    )

    def create(_context: CapabilityProviderContext) -> CapabilityBundleValue:
        return CapabilityBundleValue(
            (
                CapabilityFacetBinding(
                    MODEL_INPUT_PREPARATION_FACET,
                    SessionModelCallPreparer(
                        transcript=transcript,
                        projector=projector,
                        is_current=is_current,
                        registration_entries_provider=registration_entries_provider,
                        profile_fingerprint_provider=profile_fingerprint_provider,
                    ),
                ),
            )
        )

    return SessionModelCallCapabilityBinding(
        plan=plan,
        provider_binding=CapabilityBundleProviderBinding(
            provider=provider,
            scope_instance_id=runtime_id,
            binding_input_fingerprint=_fingerprint(
                {
                    "conversation_id": transcript.header.conversation_id,
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
        transcript: AgentTranscriptSession,
        ensure_consumer: Callable[
            [], Awaitable[SessionModelCallCapabilityConsumer]
        ],
        projector: RuntimeCapabilityGraphProjector,
        registration_entries_provider: RegistrationEntriesProvider | None = None,
    ) -> None:
        if not isinstance(transcript, AgentTranscriptSession):
            raise TypeError("model-call runtime requires AgentTranscriptSession")
        if not callable(ensure_consumer):
            raise TypeError("model-call runtime requires a typed Consumer port")
        if not isinstance(projector, RuntimeCapabilityGraphProjector):
            raise TypeError("model-call runtime requires graph projection")
        if registration_entries_provider is not None and not callable(
            registration_entries_provider
        ):
            raise TypeError("model-call runtime registration inventory must be callable")

        self._transcript = transcript
        self._ensure_consumer = ensure_consumer
        self._projector = projector
        self._registration_entries_provider = (
            registration_entries_provider or (lambda: ())
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
