from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired
from loushang.coding.resume_activation_attempt_v2 import (
    CodingActivationAttemptV2,
    CodingResumeEffectOwnerV1,
)
from loushang.coding.resume_activation_plan import build_session_activation_plan
from loushang.coding.resume_binding_v2 import CodingRuntimeBindingV2
from loushang.coding.resume_continuation import (
    _prepare_v2_plugin_parents,
    _require_v2_native_writer_protocols,
    prepare_coding_resume_continuation,
)
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.coding.session_manager import (
    SessionManager,
    _bind_owned_session_manager,
    _create_owned_session_factory,
)
from loushang.harness.worker import activation_state_journal

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux owned Resume Writer"
)


def test_v2_worker_owner_requires_exact_selection_and_phases():
    worker = CodingResumeEffectOwnerV1(
        "harness.worker-activation",
        "c" * 64,
        "d" * 64,
        ("reservation", "start"),
    )
    attempt = CodingActivationAttemptV2(
        attempt_id="attempt-2",
        request_id="input-2",
        session_id="session-2",
        original_leaf_id=None,
        ancestry_digest="a" * 64,
        plan_fingerprint="b" * 64,
        epoch_fingerprint="e" * 64,
        subject_digest="f" * 64,
        effect_owners=(worker,),
    )

    plugins, parent = _prepare_v2_plugin_parents(
        attempt, worker_candidate_plugin_id="worker.example",
    )
    assert plugins is None
    assert parent == attempt.parent_context(worker)
    with pytest.raises(CodingResumeRecoveryRequired):
        _prepare_v2_plugin_parents(attempt, worker_candidate_plugin_id=None)
    with pytest.raises(CodingResumeRecoveryRequired):
        _prepare_v2_plugin_parents(
            replace(attempt, effect_owners=(replace(worker, phases=("start",)),)),
            worker_candidate_plugin_id="worker.example",
        )


def test_v2_capability_aggregation_refuses_missing_native_writer_without_io(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        activation_state_journal, "_RESUME_WRITER_CAPABILITIES", frozenset()
    )

    with pytest.raises(CodingResumeRecoveryRequired) as caught:
        _require_v2_native_writer_protocols(SessionManager)

    assert caught.value.reason_code == "writer.resume_protocol_unsupported"
    assert not (tmp_path / ".resume-protocol-probe").exists()


def test_v2_continuation_commits_one_bound_input_with_no_effect_owners(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        original = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            defer_materialization=False,
        )
        await original.append_message(
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
        attempt = CodingActivationAttemptV2(
            attempt_id="attempt-2",
            request_id="input-2",
            session_id=session_id,
            original_leaf_id=plan.selected_leaf_id,
            ancestry_digest=plan.ancestry_digest,
            plan_fingerprint=plan.plan_id,
            epoch_fingerprint="a" * 64,
            subject_digest="b" * 64,
        )
        factory = _create_owned_session_factory()
        prepared = None
        try:
            prepared = await prepare_coding_resume_continuation(
                manager_type=_bind_owned_session_manager(factory),
                session_file=path,
                plan=plan,
                current_owner_inputs=(),
                attempt=attempt,
                input_record_id="message-2",
                text="continue",
                created_at=datetime(2026, 10, 13, tzinfo=UTC),
                require_current_admission=lambda observed: None,
                require_current_epoch_settlement=lambda observed, receipt: None,
                no_tools=True,
            )
            assert prepared.input_record_id == "message-2"
        finally:
            if prepared is not None:
                await prepared.session.dispose()
            await factory.close()

        reloaded = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        assert reloaded.activation_status == "none"
        assert reloaded.binding_status == "bound"
        assert type(reloaded.binding) is CodingRuntimeBindingV2
        assert reloaded.binding.intent_digest == attempt.digest
        assert len(
            [record for record in reloaded.selected_records if record.record_id == "message-2"]
        ) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("partial_tail", [False, True])
def test_v2_continuation_refuses_unsupported_owner_before_admission_writer_or_tail_repair(
    tmp_path, monkeypatch, partial_tail
):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        original = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            defer_materialization=False,
        )
        await original.append_message(
            UserMessage(role="user", content="history", timestamp=1.0)
        )
        path = original.session_file
        await original.dispose_runtime_profile()
        assert path is not None
        history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        plan = build_session_activation_plan(
            history,
            resolve_coding_composition_set("coding-standard"),
            workspace_root=tmp_path,
        )
        attempt = CodingActivationAttemptV2(
            attempt_id="attempt-2",
            request_id="input-2",
            session_id=plan.session_id,
            original_leaf_id=plan.selected_leaf_id,
            ancestry_digest=plan.ancestry_digest,
            plan_fingerprint=plan.plan_id,
            epoch_fingerprint="a" * 64,
            subject_digest="b" * 64,
            effect_owners=(
                CodingResumeEffectOwnerV1(
                    "unsupported.domain",
                    "c" * 64,
                    "d" * 64,
                    ("startup",),
                ),
            ),
        )
        if partial_tail:
            with path.open("ab") as stream:
                stream.write(b'{"recordId":"future-uncommitted",')
        before = {
            item.relative_to(tmp_path): item.read_bytes()
            for item in tmp_path.rglob("*")
            if item.is_file()
        }
        factory = _create_owned_session_factory()
        manager_type = _bind_owned_session_manager(factory)

        def reject(*args, **kwargs):
            pytest.fail(
                "unsupported protocol must refuse before current owner callbacks"
            )

        async def reject_writer(*args, **kwargs):
            pytest.fail(
                "unsupported protocol must refuse before original Writer acquisition"
            )

        monkeypatch.setattr(
            manager_type, "_load_resume_writer", classmethod(reject_writer)
        )
        try:
            with pytest.raises(CodingResumeRecoveryRequired) as caught:
                await prepare_coding_resume_continuation(
                    manager_type=manager_type,
                    session_file=path,
                    plan=plan,
                    current_owner_inputs=(),
                    attempt=attempt,
                    input_record_id="message-2",
                    text="continue",
                    created_at=datetime(2026, 10, 13, tzinfo=UTC),
                    require_current_admission=reject,
                    require_current_epoch_settlement=reject,
                )
            assert caught.value.reason_code == "input.effect_owner_set_unsupported"
            assert factory.pending_preparations == ()
            after = {
                item.relative_to(tmp_path): item.read_bytes()
                for item in tmp_path.rglob("*")
                if item.is_file()
            }
            assert after == before
        finally:
            await factory.close()

    asyncio.run(scenario())
