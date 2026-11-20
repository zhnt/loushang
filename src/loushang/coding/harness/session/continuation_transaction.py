"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from typing import cast

from loushang.coding.resume import continuation as _binding


def prepare_effect_parents(
    attempt: _binding.CodingActivationAttemptV2,
    *,
    worker_candidate_plugin_id: str | None,
) -> tuple[
    _binding.CodingResumePluginParents | None,
    _binding.ResumeEffectParentContextV1 | None,
]:
    owners = {owner.owner_id: owner for owner in attempt.effect_owners}
    plugin_ids = {
        _binding._RESUME_OPERATION_VALUES["definition_owner"],
        _binding._RESUME_OPERATION_VALUES["activation_owner"],
    }
    selected_plugin_ids = plugin_ids & owners.keys()
    if selected_plugin_ids and selected_plugin_ids != plugin_ids:
        raise _binding.CodingResumeRecoveryRequired(
            _binding._RESUME_OPERATION_VALUES["value_001"]
        )
    worker_owner_id = _binding._RESUME_OPERATION_VALUES["worker_owner"]
    supported = plugin_ids | (
        {worker_owner_id} if worker_candidate_plugin_id else set()
    )
    unsupported = set(owners) - supported
    if (
        unsupported
        or attempt.effect_classes
        or any(owner.effect_classes for owner in attempt.effect_owners)
    ):
        raise _binding.CodingResumeRecoveryRequired(
            _binding._RESUME_OPERATION_VALUES["value_001"]
        )
    worker_owner = owners.get(worker_owner_id)
    if (worker_candidate_plugin_id is None) != (worker_owner is None):
        raise _binding.CodingResumeRecoveryRequired(
            _binding._RESUME_OPERATION_VALUES["value_001"]
        )
    worker_parent = None
    if worker_owner is not None:
        if worker_owner.phases != ("reservation", "start"):
            raise _binding.CodingResumeRecoveryRequired(
                _binding._RESUME_OPERATION_VALUES["value_001"]
            )
        worker_parent = attempt.parent_context(worker_owner)
    if not selected_plugin_ids:
        return None, worker_parent
    if owners[_binding._RESUME_OPERATION_VALUES["definition_owner"]].phases != (
        "declaration",
    ) or owners[_binding._RESUME_OPERATION_VALUES["activation_owner"]].phases != (
        "activation",
    ):
        raise _binding.CodingResumeRecoveryRequired(
            _binding._RESUME_OPERATION_VALUES["value_001"]
        )
    return (
        _binding.CodingResumePluginParents(
            definition=attempt.parent_context(
                owners[_binding._RESUME_OPERATION_VALUES["definition_owner"]]
            ),
            activation=attempt.parent_context(
                owners[_binding._RESUME_OPERATION_VALUES["activation_owner"]]
            ),
        ),
        worker_parent,
    )


def require_writer_protocols(manager_type: type[_binding.SessionManager]) -> None:
    """Negotiate all accepted v2 writers without opening any durable source."""

    manager_type._require_resume_writer_capabilities(
        frozenset({_binding._RESUME_OPERATION_VALUES["value_002"]})
    )
    probe_root = (
        _binding.Path.cwd().resolve(strict=False)
        / _binding._RESUME_OPERATION_VALUES["probe_directory"]
    )
    try:
        _binding.PluginExecutionDecisionJournal(
            probe_root / _binding._RESUME_OPERATION_VALUES["value_003"],
            scope_kind="workspace",
            scope_id=_binding._RESUME_OPERATION_VALUES["probe_scope"],
            required_writer_capabilities=frozenset(
                {_binding._RESUME_OPERATION_VALUES["definition_writer_capability"]}
            ),
        )
        _binding.PluginActivationDecisionJournal(
            probe_root / _binding._RESUME_OPERATION_VALUES["value_004"],
            scope_id=_binding._RESUME_OPERATION_VALUES["probe_scope"],
            required_writer_capabilities=frozenset(
                {_binding._RESUME_OPERATION_VALUES["activation_writer_capability"]}
            ),
        )
        _binding.WorkerActivationStateJournal(
            probe_root / _binding._RESUME_OPERATION_VALUES["value_005"],
            required_writer_capabilities=frozenset(
                {_binding._RESUME_OPERATION_VALUES["worker_writer_capability"]}
            ),
        )
    except (
        _binding.PluginExecutionJournalError,
        _binding.PluginActivationJournalError,
        _binding.WorkerActivationStateJournalError,
    ) as error:
        raise _binding.CodingResumeRecoveryRequired(
            _binding._RESUME_OPERATION_VALUES["value_006"]
        ) from error


async def prepare_continuation(
    *,
    manager_type: type[_binding.SessionManager],
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
    stream_fn: _binding.StreamFn | None,
    tools: list[_binding.ToolDefinition] | None,
    output_capture_factory: _binding.ExecCaptureFactory | None,
    no_tools: _binding.NoToolsMode | bool | None,
    approval_resolver: _binding.InteractiveApprovalResolver | None,
    tool_policy_evaluator: _binding.PolicyEvaluator | None,
    observe_input_identity: _binding.Callable[
        [_binding.CodingResumeInputLookupQueryV1], None
    ]
    | None,
    product_owner_selection: _binding.CodingFencedProductApplicationSelection | None,
    resume_writer_factory: _binding.AgentTranscriptSessionFactory[
        _binding.ResolvedRuntimeProfile, _binding.RuntimeProfileBinding
    ]
    | None,
    worker_candidates: bool,
    worker_candidate_plugin_id: str | None,
) -> _binding.CodingResumePreparedContinuation:
    """Prepare one initial input, commit it once, then publish original owners.

    There is no retry, model dispatch or Product slot replacement here. Failure
    releases the undelivered original candidate/Writer without erasing history.
    Commit uncertainty requires original logical-input lookup, not another input.
    """

    if not isinstance(manager_type, type) or not issubclass(
        manager_type, _binding.SessionManager
    ):
        raise TypeError(_binding._RESUME_OPERATION_VALUES["value_009"])
    if isinstance(attempt, _binding.CodingActivationAttemptV1) and type(
        attempt
    ) not in {
        _binding.CodingActivationAttemptV1,
        _binding.CodingActivationAttemptV2,
    }:
        raise _binding.CodingResumeRecoveryRequired(
            _binding._RESUME_OPERATION_VALUES["value_006"]
        )
    if product_owner_selection is not None and not isinstance(
        product_owner_selection,
        _binding.CodingFencedProductApplicationSelection,
    ):
        raise TypeError(_binding._RESUME_OPERATION_VALUES["value_010"])
    if (
        type(worker_candidates) is not bool
        or (
            worker_candidate_plugin_id is not None
            and (
                not isinstance(worker_candidate_plugin_id, str)
                or not worker_candidate_plugin_id
                or worker_candidate_plugin_id != worker_candidate_plugin_id.strip()
            )
        )
        or (
            (worker_candidates or worker_candidate_plugin_id is not None)
            and product_owner_selection is None
        )
    ):
        raise ValueError(_binding._RESUME_OPERATION_VALUES["value_011"])
    resume_plugin_parents: _binding.CodingResumePluginParents | None = None
    resume_worker_parent: _binding.ResumeEffectParentContextV1 | None = None
    if type(attempt) is _binding.CodingActivationAttemptV2:
        if worker_candidates and worker_candidate_plugin_id is None:
            raise _binding.CodingResumeRecoveryRequired(
                _binding._RESUME_OPERATION_VALUES["value_001"]
            )
        resume_plugin_parents, resume_worker_parent = (
            _binding._prepare_v2_plugin_parents(
                attempt,
                worker_candidate_plugin_id=worker_candidate_plugin_id,
            )
        )
        _binding._require_v2_native_writer_protocols(manager_type)
    elif worker_candidate_plugin_id is not None:
        raise _binding.CodingResumeRecoveryRequired(
            _binding._RESUME_OPERATION_VALUES["value_001"]
        )
    if (
        not isinstance(plan, _binding.SessionActivationPlanV1)
        or not isinstance(attempt, _binding.CodingActivationAttemptV1)
        or plan.status != "needs_final_validation"
        or attempt.session_id != plan.session_id
        or attempt.original_leaf_id != plan.selected_leaf_id
        or attempt.ancestry_digest != plan.ancestry_digest
        or attempt.plan_fingerprint != plan.plan_id
    ):
        raise ValueError(_binding._RESUME_OPERATION_VALUES["value_012"])
    if (
        type(input_record_id) is not str
        or _binding._IDENTIFIER.fullmatch(input_record_id) is None
    ):
        raise ValueError(_binding._RESUME_OPERATION_VALUES["value_013"])
    if input_record_id == attempt.attempt_id:
        raise ValueError(_binding._RESUME_OPERATION_VALUES["value_014"])
    if not isinstance(text, str) or (not text.strip() and not images):
        raise ValueError(_binding._RESUME_OPERATION_VALUES["value_015"])
    if not isinstance(created_at, _binding.datetime) or created_at.tzinfo is None:
        raise ValueError(_binding._RESUME_OPERATION_VALUES["value_016"])
    if any(
        not callable(check) or _binding.inspect.iscoroutinefunction(check)
        for check in (
            require_current_admission,
            require_current_epoch_settlement,
        )
    ):
        raise TypeError(_binding._RESUME_OPERATION_VALUES["value_017"])

    def checked(callback: _binding.Callable[[], None]) -> None:
        result = cast(_binding.Callable[[], object], callback)()
        if result is not None:
            if _binding.inspect.iscoroutine(result):
                result.close()
            raise TypeError(_binding._RESUME_OPERATION_VALUES["value_018"])

    def current() -> None:
        checked(lambda: require_current_admission(attempt))

    manager: _binding.SessionManager | None = None
    session: _binding.AgentSession | None = None
    resume_plugin_state_root: _binding.Path | None = None
    observed_input = False
    phase = "writer_preparation"
    current()  # Confirmation/current caller admission precedes Writer acquisition.
    try:
        manager = await manager_type._load_resume_writer(
            session_file,
            plan=plan,
            current_owner_inputs=current_owner_inputs,
            required_writer_capabilities=(
                frozenset({_binding._RESUME_OPERATION_VALUES["value_002"]})
                if type(attempt) is _binding.CodingActivationAttemptV2
                else frozenset()
            ),
            _factory=resume_writer_factory,
        )
        with manager._lifecycle_session.sync_operation_scope():
            current()
            if any(
                record.record_id in {input_record_id, attempt.attempt_id}
                for record in manager.get_entries()
            ):
                raise _binding.CodingResumeRecoveryRequired(
                    _binding._RESUME_OPERATION_VALUES["value_019"]
                )
            for record in manager.get_active_entries():
                existing = _binding.inspect_coding_runtime_binding(
                    record.metadata
                ).binding
                if (
                    existing is None
                    and _binding.CODING_RUNTIME_BINDING_V2_METADATA_KEY
                    in record.metadata
                ):
                    existing = _binding.decode_coding_runtime_binding_v2(
                        record.metadata
                    )
                if (
                    existing is not None
                    and existing.session_id == attempt.session_id
                    and existing.input_id == attempt.request_id
                ):
                    raise _binding.CodingResumeRecoveryRequired(
                        _binding._RESUME_OPERATION_VALUES["value_020"]
                    )
        phase = "intent_commit"
        await manager._commit_resume_activation_intent(
            _binding.prepare_coding_activation_attempt_v2_record(
                attempt, created_at=created_at
            )
            if type(attempt) is _binding.CodingActivationAttemptV2
            else _binding.prepare_coding_activation_attempt_record(
                attempt, created_at=created_at
            ),
        )
        if resume_plugin_parents is not None:
            phase = "native_owner_enrollment"
            current()
            resume_plugin_state_root = (
                _binding.prepare_coding_product_approval_state_root(
                    _binding._coding_capability_plugin_state_root(
                        manager, session_id=attempt.session_id
                    )
                )
            )
            resume_plugin_parents.enroll(
                session_id=attempt.session_id,
                state_root=resume_plugin_state_root,
                clock=lambda: int(created_at.timestamp() * 1000),
            )
            current()
        phase = "runtime_preparation"
        session = await _binding._create_resume_agent_session(
            session_manager=manager,
            attempt_id=attempt.attempt_id,
            composition_set=_binding.resolve_coding_composition_set(
                plan.composition_comparison.candidate_set_id
            ),
            require_current_admission=require_current_admission,
            services=services,
            model=model,
            thinking_level=thinking_level,
            stream_fn=stream_fn,
            tools=tools,
            output_capture_factory=output_capture_factory,
            no_tools=no_tools,
            approval_resolver=approval_resolver,
            tool_policy_evaluator=tool_policy_evaluator,
            product_owner_selection=product_owner_selection,
            worker_candidates=worker_candidates,
            worker_candidate_plugin_id=worker_candidate_plugin_id,
            resume_plugin_parents=resume_plugin_parents,
            resume_worker_parent=resume_worker_parent,
            resume_effect_owner_ids=(
                frozenset(owner.owner_id for owner in attempt.effect_owners)
                if type(attempt) is _binding.CodingActivationAttemptV2
                else None
            ),
        )
        receipt = await session._prepare_resume_runtime_graph(
            attempt_id=attempt.attempt_id,
            require_current_admission=require_current_admission,
        )
        if resume_plugin_parents is not None:
            phase = "native_owner_seal"
            current()
            assert resume_plugin_state_root is not None
            resume_plugin_parents.seal(
                session_id=attempt.session_id,
                state_root=resume_plugin_state_root,
                clock=lambda: int(created_at.timestamp() * 1000),
            )
            current()

        def settled() -> None:
            with manager._lifecycle_session.sync_operation_scope():
                current()
                candidate = session._resume_candidate
                if candidate is None:
                    raise RuntimeError(_binding._RESUME_OPERATION_VALUES["value_021"])
                session._require_resume_candidate(candidate)
                current()
                session._require_resume_worker_effect_settlement(attempt)
                current()
                checked(lambda: require_current_epoch_settlement(attempt, receipt))
                current()
                session._require_resume_candidate(candidate)
                current()

        settled()  # Unsettled effects cannot proceed to first-input preparation.
        phase = "input_preparation"
        message = await session._prepare_resume_first_user_input(
            text,
            images=images,
            attempt_id=attempt.attempt_id,
            require_current_admission=require_current_admission,
        )
        settled()

        def binding(
            persisted: _binding.UserMessage,
        ) -> _binding.CodingRuntimeBindingV1 | _binding.CodingRuntimeBindingV2:
            if type(attempt) is _binding.CodingActivationAttemptV2:
                return _binding.CodingRuntimeBindingV2(
                    attempt_id=attempt.attempt_id,
                    input_id=attempt.request_id,
                    record_id=input_record_id,
                    session_id=attempt.session_id,
                    original_leaf_id=attempt.original_leaf_id,
                    ancestry_digest=attempt.ancestry_digest,
                    subject_digest=attempt.subject_digest,
                    origin_composition=plan.composition_comparison.origin,
                    planned_fingerprint=attempt.plan_fingerprint,
                    actual_fingerprint=attempt.epoch_fingerprint,
                    payload_digest=_binding.coding_user_payload_digest(persisted),
                    difference_codes=plan.composition_comparison.difference_codes,
                    intent_digest=attempt.digest,
                )
            return _binding.CodingRuntimeBindingV1(
                attempt_id=attempt.attempt_id,
                input_id=attempt.request_id,
                record_id=input_record_id,
                session_id=attempt.session_id,
                original_leaf_id=attempt.original_leaf_id,
                ancestry_digest=attempt.ancestry_digest,
                subject_digest=attempt.subject_digest,
                origin_composition=plan.composition_comparison.origin,
                planned_fingerprint=attempt.plan_fingerprint,
                actual_fingerprint=attempt.epoch_fingerprint,
                payload_digest=_binding.coding_user_payload_digest(persisted),
                difference_codes=plan.composition_comparison.difference_codes,
            )

        manager._stage_resume_first_user_input(
            message,
            prepare_binding=binding,
            created_at=created_at,
            original_leaf_id=attempt.original_leaf_id,
            ancestry_digest=attempt.ancestry_digest,
            attempt_id=attempt.attempt_id,
        )
        phase = "input_commit"
        record_id = await session._commit_resume_first_user_input(
            message,
            attempt_id=attempt.attempt_id,
            require_current_admission=require_current_admission,
        )
        _, committed_input = manager._require_committed_resume_input(
            attempt.attempt_id, record_id
        )
        query = _binding.CodingResumeInputLookupQueryV1(
            attempt.request_id,
            _binding.coding_resume_input_record_digest(committed_input),
        )
        observed_input = True  # A failing receiver must not receive this twice.
        if observe_input_identity is not None:
            checked(lambda: observe_input_identity(query))
        phase = "runtime_publication"
        await session._publish_resume_runtime(
            attempt_id=attempt.attempt_id,
            input_record_id=record_id,
            require_current_admission=require_current_admission,
            require_current_epoch_settlement=require_current_epoch_settlement,
        )
        return _binding.CodingResumePreparedContinuation(
            session, attempt.attempt_id, record_id, query
        )
    except BaseException as error:
        error.add_note(
            f"{_binding._RESUME_OPERATION_VALUES['value_007']}{phase}; no model was dispatched by this entry."
        )
        if isinstance(error, _binding.CodingResumeContinuationCleanupFailure):
            # Bootstrap already retains the complete candidate. Disposing its
            # Manager separately could release its Writer before graph cleanup.
            raise
        if phase in {"input_commit", "runtime_publication"}:
            error.add_note(
                "Input may already be committed; use original input lookup before any explicit recovery."
            )
            if (
                manager is not None
                and not observed_input
                and observe_input_identity is not None
            ):
                proof = manager._resume_committed_input
                pending = manager._resume_first_input
                prepared_record = (
                    proof[1]
                    if proof is not None
                    else (pending.prepared_record if pending is not None else None)
                )
                if prepared_record is not None:
                    try:
                        recovery_query = _binding.CodingResumeInputLookupQueryV1(
                            attempt.request_id,
                            _binding.coding_resume_input_record_digest(prepared_record),
                        )
                        checked(lambda: observe_input_identity(recovery_query))
                    except BaseException as observation_error:
                        error.add_note(
                            f"Resume input identity delivery also failed: {observation_error!r}"
                        )
        try:
            if session is not None:
                await session.dispose()
            elif manager is not None:
                await manager.dispose_runtime_profile()
        except BaseException as cleanup_error:
            error.add_note(
                f"{_binding._RESUME_OPERATION_VALUES['value_008']}{cleanup_error!r}"
            )
            original_owner = session if session is not None else manager
            assert original_owner is not None
            raise _binding.retain_resume_cleanup_failure(
                original_owner=original_owner,
                original_error=error,
                cleanup_error=cleanup_error,
            ) from error
        raise
