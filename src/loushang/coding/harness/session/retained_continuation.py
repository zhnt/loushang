"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from typing import cast

from loushang.coding.runtime import agent_session_runtime as _binding

from .resume_cleanup import discard_candidate


async def prepare_continuation(
    self: _binding.AgentSessionRuntime,
    *,
    session_file: str | _binding.Path,
    plan: _binding.SessionActivationPlanV1,
    current_owner_inputs: _binding.Sequence[_binding.ActivationOwnerInputRefV1],
    attempt: _binding.CodingActivationAttemptV1,
    input_record_id: str,
    text: str,
    created_at: _binding.datetime,
    require_current_admission: _binding.Callable[
        [_binding.CodingActivationAttemptV1], None
    ],
    require_current_epoch_settlement: _binding.Callable[
        [_binding.CodingActivationAttemptV1, _binding.Mapping[str, object]], None
    ],
    images: list[_binding.ImagePart] | None,
    services: _binding.BootstrapServices | None,
    model: _binding.Model | _binding.ModelSelection | None,
    thinking_level: _binding.ThinkingLevel | None,
    no_tools: _binding.NoToolsMode | bool | None,
    approval_resolver: _binding.InteractiveApprovalResolver | None,
    tool_policy_evaluator: _binding.PolicyEvaluator | None,
    observe_input_identity: _binding.Callable[
        [_binding.CodingResumeInputLookupQueryV1], None
    ]
    | None,
    worker_candidates: bool,
    worker_candidate_plugin_id: str | None,
) -> _binding.CodingRuntimePreparedResume:
    """Retain native Resume preparation until original consume or abort.

    Live actor/policy and effect settlement remain mandatory owner inputs.
    An already selected native Product epoch must match the attempt before
    Writer acquisition and at every subsequent original admission check.
    This entry neither dispatches a model nor resubmits the committed input.
    """

    from loushang.coding.resume.activation_attempt import (
        CodingResumeRecoveryRequired,
    )
    from loushang.coding.resume.continuation import (
        prepare_coding_resume_continuation,
    )

    if self._resume_history_closed:
        raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_001"])
    view = _binding._RESUME_HISTORY_VIEW_SCOPE.get()
    if view is not None and (
        view.runtime is not self
        or self.resolve_discovered_session_source(session_file).path != view.target
        or plan.session_id != view.history.header_preview.header.conversation_id
        or plan.selected_leaf_id != view.history.selected_leaf_id
        or plan.ancestry_digest != view.history.selected_ancestry_digest
        or plan.source_fingerprint != view.history.source_fingerprint
        or plan.source_content_digest != view.history.source_content_digest
    ):
        raise CodingResumeRecoveryRequired(
            _binding._CONTINUATION_PROGRAM_VALUES["value_002"]
        )

    def current_view() -> None:
        if view is not None and view.require_current_view is not None:
            result = cast(_binding.Callable[[], object], view.require_current_view)()
            if result is not None:
                if _binding.inspect.iscoroutine(result):
                    result.close()
                raise TypeError(_binding._CONTINUATION_PROGRAM_VALUES["value_010"])

    current_view()  # A cancelled/closed display cannot begin Writer preparation.
    factory = self._owned_transcript_factory
    selection = self._product_owner_selection
    if factory is None or selection is None:
        raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_003"])
    self.lifecycle.require_retained_preparation_idle(
        error_prefix=_binding._CONTINUATION_PROGRAM_VALUES["value_004"]
    )
    if not callable(require_current_admission) or _binding.inspect.iscoroutinefunction(
        require_current_admission
    ):
        raise TypeError(_binding._CONTINUATION_PROGRAM_VALUES["value_005"])
    previous = self.current_session
    continuation: _binding.CodingResumePreparedContinuation | None = None
    operation: (
        _binding.PreparedSessionLifecycleOperation[_binding.AgentSession, str] | None
    ) = None

    def admit(observed: _binding.CodingActivationAttemptV1) -> None:
        if self._resume_history_closed:
            raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_001"])
        if operation is None or not operation.consumed:
            current_view()
        expected = (
            continuation.session
            if operation is not None and operation.consumed and continuation is not None
            else previous
        )
        if self.current_session is not expected:
            raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_006"])
        if self._embedded_resume_approval_owner is not None:
            self.require_current_embedded_resume_subject(observed)
        result = cast(
            "_binding.Callable[[_binding.CodingActivationAttemptV1], object]",
            require_current_admission,
        )(observed)
        if result is not None:
            if _binding.inspect.iscoroutine(result):
                result.close()
            raise TypeError(_binding._CONTINUATION_PROGRAM_VALUES["value_008"])
        # Borrow the original selected native epoch, including before the
        # first Writer acquisition. This read cannot select/create an owner.
        # The caller's effect settlement remains an independent gate.
        if (
            selection.resume_epoch_fingerprint(_binding.Path(plan.workspace_root))
            != observed.epoch_fingerprint
        ):
            raise CodingResumeRecoveryRequired(
                _binding._CONTINUATION_PROGRAM_VALUES["value_009"]
            )

    async def build(current: _binding.AgentSession | None) -> _binding.AgentSession:
        nonlocal continuation
        if current is not previous:
            raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_006"])
        continuation = await prepare_coding_resume_continuation(
            manager_type=_binding._bind_owned_session_manager(factory),
            session_file=session_file,
            plan=plan,
            current_owner_inputs=current_owner_inputs,
            attempt=attempt,
            input_record_id=input_record_id,
            text=text,
            created_at=created_at,
            require_current_admission=admit,
            require_current_epoch_settlement=require_current_epoch_settlement,
            images=images,
            services=services,
            model=model,
            no_tools=no_tools,
            thinking_level=thinking_level,
            approval_resolver=approval_resolver,
            tool_policy_evaluator=tool_policy_evaluator,
            observe_input_identity=observe_input_identity,
            product_owner_selection=selection,
            worker_candidates=worker_candidates,
            worker_candidate_plugin_id=worker_candidate_plugin_id,
        )
        # Native model transport checks the original Root's actual slot.
        try:
            continuation.session.set_extension_runtime_host(self)
        except BaseException as error:
            await discard_candidate(continuation.session, error)
            raise
        return continuation.session

    def bind_operation(
        prepared: _binding.PreparedSessionLifecycleOperation[
            _binding.AgentSession, str
        ],
    ) -> None:
        nonlocal operation
        operation = prepared
        assert continuation is not None

    return await self.lifecycle.prepare_retained_candidate(
        lambda: _binding.SessionLifecycleTransition(
            reason="resume",
            target_session_ref=str(session_file),
            metadata={
                "activate_extensions": False,
                "emit_before_transition": False,
                "schedule_index": False,
            },
        ),
        build,
        cleanup_error_type=_binding.CodingResumeContinuationCleanupFailure,
        bind_operation=bind_operation,
        result_factory=lambda prepared: _binding.CodingRuntimePreparedResume(
            self,
            prepared,
            cast("_binding.CodingResumePreparedContinuation", continuation),
        ),
    )


async def consume_preparation(
    self: _binding.AgentSessionRuntime, prepared: _binding.CodingRuntimePreparedResume
) -> _binding.SessionOperationResult[_binding.AgentSession, str | None]:
    if self._resume_history_closed:
        raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_001"])
    operation = prepared._operation
    if prepared._root is not self:
        raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_012"])
    return await self.lifecycle.consume_retained_preparation(
        operation,
        error_prefix=_binding._CONTINUATION_PROGRAM_VALUES["value_004"],
    )


async def abort_preparation(
    self: _binding.AgentSessionRuntime, prepared: _binding.CodingRuntimePreparedResume
) -> None:
    if prepared._root is not self:
        raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_012"])
    await self.lifecycle.abort_retained_preparation(prepared._operation)


async def run_first_input(
    self: _binding.AgentSessionRuntime, prepared: _binding.CodingRuntimePreparedResume
) -> None:
    from loushang.coding.resume.activation_attempt import (
        CodingResumeRecoveryRequired,
    )

    if self._resume_history_closed:
        raise CodingResumeRecoveryRequired(
            _binding._CONTINUATION_PROGRAM_VALUES["value_013"]
        )
    if (
        prepared._root is not self
        or not prepared.consumed
        or self.current_session is not prepared.continuation.session
    ):
        raise CodingResumeRecoveryRequired(
            _binding._CONTINUATION_PROGRAM_VALUES["value_014"]
        )
    if (
        self.lifecycle._retained_preparation_loop
        is not _binding.asyncio.get_running_loop()
    ):
        raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_015"])
    continuation = prepared.continuation
    # Original Host claim, Model Input transport admission, fixed input
    # identity and once-only dispatch remain owned by the native Session.
    await continuation.session._run_published_resume_input(
        attempt_id=continuation.attempt_id,
        input_record_id=continuation.input_record_id,
    )
