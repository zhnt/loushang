from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import UserMessage
from loushang.coding._capability_plugin_composition import (
    CodingResumePluginParents,
    prepare_coding_resume_plugin_effect_owners,
    require_coding_resume_plugin_effect_settlement,
)
from loushang.coding._product_capability_plugin_composition import (
    _prepare_product_approval_state_root,
)
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired
from loushang.coding.resume_activation_attempt_v2 import (
    CodingActivationAttemptV2,
    CodingResumeEffectOwnerV1,
    prepare_coding_activation_attempt_v2_record,
)
from loushang.coding.resume_activation_plan import build_session_activation_plan
from loushang.coding.resume_binding import coding_user_payload_digest
from loushang.coding.resume_binding_v2 import CodingRuntimeBindingV2
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.coding.session_manager import (
    SessionManager,
    _bind_owned_session_manager,
    _create_owned_session_factory,
)
from loushang.harness.approval.plugin_activation import PluginActivationDecisionJournal
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.resources.plugins.selection import (
    PluginDeclarationSource,
    PluginExecutionApprovalSubject,
    PluginInstanceRevisionRef,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1


def _parents(root, session_id, clock):
    definition = PluginExecutionDecisionJournal(
        root / "definition-decisions.jsonl",
        scope_kind="workspace",
        scope_id=f"session:{session_id}",
        clock=clock,
    )
    activation = PluginActivationDecisionJournal(
        root / "activation-decisions.jsonl",
        scope_id=f"session:{session_id}",
        clock=clock,
    )

    def context(journal, owner_id):
        return ResumeEffectParentContextV1(
            product_id="coding",
            session_id=session_id,
            attempt_id="intent-1",
            request_id="input-1",
            intent_digest="a" * 64,
            owner_id=owner_id,
            scope_digest=journal.resume_parent_scope_digest(product_id="coding"),
            contract_digest=journal.resume_parent_contract_digest,
        )

    return (
        definition,
        activation,
        CodingResumePluginParents(
            context(definition, "harness.plugin-execution"),
            context(activation, "harness.plugin-activation"),
        ),
    )


def test_both_native_enrollments_form_one_preparation_prerequisite(tmp_path):
    root = _prepare_product_approval_state_root(tmp_path / "state")
    definition, activation, parents = _parents(root, "session-1", lambda: 1000)
    definition.enroll_resume_parent(parents.definition, expected_journal_revision=0)
    activation.enroll_resume_parent(parents.activation, expected_journal_revision=0)

    parents.require_open(session_id="session-1", state_root=root, clock=lambda: 1000)

    assert definition.resume_parent_snapshot(parents.definition).execution_uses == ()
    assert activation.resume_parent_snapshot(parents.activation).activation_uses == ()


def test_product_parent_enrollment_is_retryable_and_seals_exact_empty_membership(
    tmp_path,
):
    root = _prepare_product_approval_state_root(tmp_path / "state")
    definition, activation, parents = _parents(root, "session-1", lambda: 1000)

    parents.enroll(session_id="session-1", state_root=root, clock=lambda: 1000)
    parents.enroll(session_id="session-1", state_root=root, clock=lambda: 1000)
    definition_seal, activation_seal = parents.seal(
        session_id="session-1", state_root=root, clock=lambda: 1000
    )

    assert definition_seal.sealed
    assert definition_seal.execution_uses == ()
    assert activation_seal.sealed
    assert activation_seal.activation_uses == ()
    assert definition.resume_parent_snapshot(parents.definition) == definition_seal
    assert activation.resume_parent_snapshot(parents.activation) == activation_seal


def test_product_freezes_exact_native_plugin_owner_obligations_without_io(tmp_path):
    state_root = (tmp_path / "state").resolve()

    owners = prepare_coding_resume_plugin_effect_owners(
        session_id="session-1", state_root=state_root
    )

    assert tuple(owner.owner_id for owner in owners) == (
        "harness.plugin-activation",
        "harness.plugin-execution",
    )
    assert tuple(owner.phases for owner in owners) == (
        ("activation",),
        ("declaration",),
    )
    assert not state_root.exists()


def test_product_reconciles_audited_builtin_plugin_startup_in_original_journals(
    tmp_path,
):
    state_root = _prepare_product_approval_state_root(tmp_path / "state")
    session_id = "session-1"
    owners = prepare_coding_resume_plugin_effect_owners(
        session_id=session_id, state_root=state_root
    )
    attempt = CodingActivationAttemptV2(
        attempt_id="intent-1",
        request_id="input-1",
        session_id=session_id,
        original_leaf_id=None,
        ancestry_digest="1" * 64,
        plan_fingerprint="2" * 64,
        epoch_fingerprint="3" * 64,
        subject_digest="4" * 64,
        effect_owners=owners,
    )
    owner_by_id = {owner.owner_id: owner for owner in owners}
    definition_context = attempt.parent_context(
        owner_by_id["harness.plugin-execution"]
    )
    activation_context = attempt.parent_context(
        owner_by_id["harness.plugin-activation"]
    )
    revision = PluginInstanceRevisionRef(
        instance_id="coding.lsp.default@session:session-1",
        plugin_id="coding.lsp.default",
        revision=1,
    )

    definition = PluginExecutionDecisionJournal(
        state_root / "definition-decisions.jsonl",
        scope_kind="workspace",
        scope_id=f"session:{session_id}",
        clock=lambda: 2_500,
    )
    definition_subject = PluginExecutionApprovalSubject(
        plugin_id=revision.plugin_id,
        package_content_digest="5" * 64,
        dependency_lock_digest="6" * 64,
        entrypoint="definition.py:declare",
        package_source_identity="product:first-party",
        source_trust_class="host-equivalent-local",
        source_trust_policy_revision="trust-1",
        product_id="coding",
        scope_id=f"session:{session_id}",
        policy_revision="policy-1",
        ambient_host_authority=True,
        configuration_map_fingerprint="7" * 64,
        requested_authorities=("filesystem", "process"),
        allowed_authority_ceiling=("filesystem", "process"),
        reservation_closure_fingerprint="8" * 64,
        source_descriptor_fingerprint=PluginDeclarationSource.in_process(
            "definition.py:declare"
        ).fingerprint,
        instance_revision_ref=revision,
    )
    decision = definition.issue_execution_decision(
        definition_subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="product:coding", source="first-party-policy"
        ),
        revocation_epoch=0,
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=3_000,
        expected_journal_revision=0,
    )
    definition.enroll_resume_parent(
        definition_context, expected_journal_revision=1
    )
    use = definition.consume_execution_decision(
        definition_subject,
        decision_id=decision.decision_id,
        preflight_use_id="a" * 48,
        source_group_id="b" * 64,
        host_boot_id="c" * 32,
        import_realm_id="d" * 32,
        expected_revocation_epoch=0,
        current_policy_revision="policy-1",
        current_source_trust_policy_revision="trust-1",
        expected_journal_revision=2,
        parent_context=definition_context,
    )
    definition.transition_execution_use(
        use.execution_use_id,
        expected_state="CONSUMED_NOT_STARTED",
        target_state="STARTING",
        host_boot_id="c" * 32,
        import_realm_id="d" * 32,
        transitioned_at_unix_ms=2_100,
        expected_journal_revision=3,
    )
    definition.transition_execution_use(
        use.execution_use_id,
        expected_state="STARTING",
        target_state="EVALUATED",
        host_boot_id="c" * 32,
        import_realm_id="d" * 32,
        transitioned_at_unix_ms=2_200,
        expected_journal_revision=4,
    )
    definition.seal_resume_parent(
        definition_context, expected_journal_revision=5
    )

    activation = PluginActivationDecisionJournal(
        state_root / "activation-decisions.jsonl",
        scope_id=f"session:{session_id}",
        clock=lambda: 2_500,
    )
    from tests.harness.approval.test_plugin_activation_journal import (
        _subject as activation_subject_fixture,
    )

    activation_subject = replace(
        activation_subject_fixture(),
        plugin_id=revision.plugin_id,
        product_id="coding",
        scope_id=f"session:{session_id}",
        instance_revision_ref=revision,
    )
    activation_decision = activation.issue_activation_decision(
        activation_subject,
        disposition="approved",
        authorization=PluginApprovalAuthorizationV1.direct(
            actor_id="product:coding", source="first-party-policy"
        ),
        issued_at_unix_ms=1_000,
        expires_at_unix_ms=3_000,
        expected_journal_revision=0,
    )
    activation.enroll_resume_parent(
        activation_context, expected_journal_revision=1
    )
    activation_use = activation.consume_activation_decision(
        activation_subject,
        decision_id=activation_decision.decision_id,
        host_boot_id="c" * 32,
        import_realm_id="d" * 32,
        expected_journal_revision=2,
        parent_context=activation_context,
    )
    for expected, target, journal_revision in (
        ("CONSUMED_NOT_STARTED", "STARTING", 3),
        ("STARTING", "STARTED", 4),
        ("STARTED", "COMMITTED", 5),
    ):
        activation.transition_activation_use(
            activation_use.activation_use_id,
            expected_state=expected,
            target_state=target,
            host_boot_id="c" * 32,
            import_realm_id="d" * 32,
            transitioned_at_unix_ms=2_100 + journal_revision,
            expected_journal_revision=journal_revision,
        )
    activation.seal_resume_parent(
        activation_context, expected_journal_revision=6
    )

    receipt = {
        "selectedRevisions": [
            {
                "pluginId": revision.plugin_id,
                "packageRevisionFingerprint": "e" * 64,
                "instanceRevisionRef": revision.to_dict(),
            }
        ]
    }
    require_coding_resume_plugin_effect_settlement(
        attempt, receipt, state_root=state_root, clock=lambda: 2_500
    )

    activation_path = state_root / "activation-decisions.jsonl"
    original = activation_path.read_bytes()
    activation_path.write_bytes(original.replace(b'"COMMITTED"', b'"FAILED"'))
    with pytest.raises(CodingResumeRecoveryRequired) as caught:
        require_coding_resume_plugin_effect_settlement(
            attempt, receipt, state_root=state_root, clock=lambda: 2_500
        )
    assert caught.value.reason_code == "input.effect_settlement_unknown"


@pytest.mark.parametrize("missing_owner", ["definition", "activation"])
def test_missing_native_enrollment_refuses_before_any_definition_use(
    tmp_path,
    missing_owner,
):
    root = _prepare_product_approval_state_root(tmp_path / "state")
    definition, activation, parents = _parents(root, "session-1", lambda: 1000)
    if missing_owner != "definition":
        definition.enroll_resume_parent(parents.definition, expected_journal_revision=0)
    if missing_owner != "activation":
        activation.enroll_resume_parent(parents.activation, expected_journal_revision=0)
    before = {path.name: path.read_bytes() for path in root.glob("*.jsonl")}
    with pytest.raises(Exception, match="enrollment is missing"):
        parents.require_open(
            session_id="session-1", state_root=root, clock=lambda: 1000
        )
    assert not definition.snapshot().execution_uses
    assert {path.name: path.read_bytes() for path in root.glob("*.jsonl")} == before


def test_mixed_native_parents_cannot_represent_one_frozen_intent(tmp_path):
    root = _prepare_product_approval_state_root(tmp_path / "state")
    _, _, parents = _parents(root, "session-1", lambda: 1000)
    with pytest.raises(ValueError, match="one intent"):
        CodingResumePluginParents(
            parents.definition,
            replace(parents.activation, intent_digest="b" * 64),
        )


def test_transcript_writer_commits_and_reloads_explicit_v2_intent_and_binding(
    tmp_path,
):
    async def scenario():
        original = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            defer_materialization=False,
        )
        leaf = await original.append_message(
            UserMessage(role="user", content="history", timestamp=1.0)
        )
        path = original.session_file
        session_id = original.header.conversation_id
        await original.dispose_runtime_profile()
        assert path is not None
        history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        plan = build_session_activation_plan(
            history,
            resolve_coding_composition_set("coding-standard"),
            workspace_root=tmp_path,
        )
        owners = tuple(
            CodingResumeEffectOwnerV1(
                owner_id,
                digest,
                contract,
                (phase,),
            )
            for owner_id, digest, contract, phase in (
                ("harness.plugin-activation", "a" * 64, "b" * 64, "activation"),
                ("harness.plugin-execution", "c" * 64, "d" * 64, "declaration"),
            )
        )
        attempt = CodingActivationAttemptV2(
            attempt_id="intent-v2",
            request_id="input-v2",
            session_id=session_id,
            original_leaf_id=leaf,
            ancestry_digest=plan.ancestry_digest,
            plan_fingerprint=plan.plan_id,
            epoch_fingerprint="e" * 64,
            subject_digest="f" * 64,
            effect_owners=owners,
        )
        factory = _create_owned_session_factory()
        manager_type = _bind_owned_session_manager(factory)
        manager = None
        try:
            manager = await manager_type._load_resume_writer(
                path,
                plan=plan,
                current_owner_inputs=(),
                required_writer_capabilities=frozenset(
                    {"coding.resume-continuation/v2"}
                ),
            )
            await manager._commit_resume_activation_intent(
                prepare_coding_activation_attempt_v2_record(
                    attempt, created_at=datetime(2026, 10, 13, tzinfo=UTC)
                )
            )
            message = UserMessage(role="user", content="continue", timestamp=2.0)
            manager._stage_resume_first_user_input(
                message,
                prepare_binding=lambda persisted: CodingRuntimeBindingV2(
                    attempt_id=attempt.attempt_id,
                    input_id=attempt.request_id,
                    record_id="message-v2",
                    session_id=attempt.session_id,
                    original_leaf_id=attempt.original_leaf_id,
                    ancestry_digest=attempt.ancestry_digest,
                    subject_digest=attempt.subject_digest,
                    origin_composition=plan.composition_comparison.origin,
                    planned_fingerprint=attempt.plan_fingerprint,
                    actual_fingerprint=attempt.epoch_fingerprint,
                    payload_digest=coding_user_payload_digest(persisted),
                    difference_codes=plan.composition_comparison.difference_codes,
                    intent_digest=attempt.digest,
                ),
                created_at=datetime(2026, 10, 13, tzinfo=UTC),
                original_leaf_id=leaf,
                ancestry_digest=attempt.ancestry_digest,
                attempt_id=attempt.attempt_id,
            )
            assert await manager.append_message(message) == "message-v2"
        finally:
            if manager is not None:
                await manager.dispose_runtime_profile()
            await factory.close()

        reloaded = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        assert reloaded.binding_status == "bound"
        assert type(reloaded.binding) is CodingRuntimeBindingV2
        assert reloaded.binding.intent_digest == attempt.digest
        assert reloaded.activation_status == "none"
        assert (
            build_session_activation_plan(
                reloaded,
                resolve_coding_composition_set("coding-standard"),
                workspace_root=tmp_path,
            ).status
            == "needs_final_validation"
        )

    asyncio.run(scenario())


def test_transcript_writer_refuses_future_capability_before_source_io(tmp_path):
    source = tmp_path / "history.jsonl"
    source.write_bytes(b"unterminated")
    factory = _create_owned_session_factory()
    manager_type = _bind_owned_session_manager(factory)

    async def scenario():
        try:
            with pytest.raises(CodingResumeRecoveryRequired) as caught:
                await manager_type._load_resume_writer(
                    source,
                    plan=object(),
                    current_owner_inputs=(),
                    required_writer_capabilities=frozenset(
                        {"coding.resume-continuation/v3"}
                    ),
                )
            assert caught.value.reason_code == "writer.resume_protocol_unsupported"
            assert source.read_bytes() == b"unterminated"
            assert factory.pending_preparations == ()
        finally:
            await factory.close()

    asyncio.run(scenario())
