from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.resume_activation_attempt_v2 import (
    prepare_coding_activation_attempt_v2_record,
)
from loushang.coding.resume_activation_projection_v2 import (
    project_coding_activation_attempt_path_v2,
)
from loushang.coding.resume_binding import (
    project_coding_runtime_binding_path,
)
from loushang.coding.resume_binding_v2 import prepare_coding_resume_v2_user_record
from loushang.harness.transcript.types import ExtensionData
from tests.coding.test_resume_activation_attempt_v2 import _intent
from tests.coding.test_resume_binding_v2 import _binding


def _path(session_id="session-1", message=None):
    ancestry = project_coding_runtime_binding_path(
        (), current_session_id=session_id
    ).ancestry_digest
    intent = _intent(session_id=session_id, ancestry_digest=ancestry)
    intent_record = prepare_coding_activation_attempt_v2_record(
        intent, created_at=datetime(2026, 10, 13, tzinfo=UTC)
    )
    if message is None:
        message = UserMessage(role="user", content="continue", timestamp=1.0)
    binding = _binding(message, intent)
    message_record = prepare_coding_resume_v2_user_record(
        binding, message, intent=intent, created_at=datetime(2026, 10, 13, tzinfo=UTC)
    )
    return intent_record, message_record


def _project(records):
    return project_coding_activation_attempt_path_v2(
        records, current_session_id="session-1"
    )


def test_v2_exact_selected_path_moves_from_pending_to_historical_correspondence():
    intent, message = _path()
    pending = _project((intent,))
    assert pending.status == "pending"
    assert pending.record_id == intent.record_id
    assert _project((intent, message)).status == "none"


def test_foreign_session_intent_is_historical_and_not_current_pending():
    intent, message = _path("origin-session")
    assert _project((intent,)).status == "none"
    assert _project((intent, message)).status == "none"


def test_v1_binding_cannot_close_v2_intent():
    intent, message = _path()
    raw = dict(message.metadata["coding.runtimeBindingV2"])
    raw.pop("intentDigest")
    raw["version"] = 1
    message = replace(message, metadata={"coding.runtimeBindingV1": raw})
    with pytest.raises(ValueError, match="v1 cannot close a v2"):
        _project((intent, message))


@pytest.mark.parametrize(
    "fault",
    ["missing_intent", "wrong_digest", "wrong_parent", "duplicate", "wrong_ancestry"],
)
def test_v2_projection_rejects_missing_or_conflicting_selected_path_facts(fault):
    intent, message = _path()
    records = (intent, message)
    if fault == "missing_intent":
        records = (replace(message, parent_id=None),)
    elif fault == "wrong_digest":
        raw = dict(message.metadata["coding.runtimeBindingV2"])
        raw["intentDigest"] = "e" * 64
        records = (intent, replace(message, metadata={"coding.runtimeBindingV2": raw}))
    elif fault == "wrong_parent":
        records = (intent, replace(message, parent_id="another"))
    elif fault == "duplicate":
        records = (intent, replace(message, record_id=intent.record_id))
    else:
        raw = dict(intent.payload.data)
        raw["ancestryDigest"] = "e" * 64
        records = (
            replace(intent, payload=ExtensionData(intent.payload.extension_type, raw)),
            message,
        )
    with pytest.raises(ValueError):
        _project(records)


@pytest.mark.parametrize(
    "fault", ["future_key", "future_version", "mixed_keys", "future_intent"]
)
def test_future_wire_stays_unknown_even_with_other_known_facts(fault):
    intent, message = _path()
    if fault == "future_intent":
        intent = replace(
            intent, payload=ExtensionData("coding.activation-attempt/v3", {})
        )
        assert _project((intent,)).status == "unknown_version"
        return
    raw = dict(message.metadata["coding.runtimeBindingV2"])
    if fault == "future_key":
        metadata = {"coding.runtimeBindingV3": raw}
    elif fault == "future_version":
        raw["version"] = 3
        metadata = {"coding.runtimeBindingV2": raw}
    else:
        metadata = {"coding.runtimeBindingV2": raw, "coding.runtimeBindingV1": raw}
    assert (
        _project((intent, replace(message, metadata=metadata))).status
        == "unknown_version"
    )


def test_bool_version_is_malformed_not_a_future_schema():
    intent, message = _path()
    raw = dict(message.metadata["coding.runtimeBindingV2"])
    raw["version"] = True
    with pytest.raises(ValueError):
        _project((intent, replace(message, metadata={"coding.runtimeBindingV2": raw})))


def test_async_activation_projection_yields_and_matches_sync_validation(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from loushang.coding import resume_activation_projection_v2 as module
    from loushang.harness.conversation import ConversationRecord

    async def scenario():
        records = tuple(
            ConversationRecord(
                record_id=str(index),
                parent_id=str(index - 1) if index else None,
                kind="agent.message",
                payload_version=1,
                created_at="2026-10-21",
                payload=UserMessage(role="user", content="history", timestamp=0.0),
            )
            for index in range(120)
        )
        clock = [0.0]
        original = module._encoded

        def encoded(value):
            clock[0] += 0.005
            return original(value)

        monkeypatch.setattr(module, "_encoded", encoded)
        monkeypatch.setattr(
            module, "time", SimpleNamespace(monotonic=lambda: clock[0]), raising=False
        )
        expected = _project(records)
        clock[0] = 0.0
        job = asyncio.create_task(
            module.project_coding_activation_attempt_path_v2_async(
                records, current_session_id="session-1"
            )
        )
        await asyncio.sleep(0)
        assert not job.done(), "activation validation blocked every other task"
        assert 0 < clock[0] < 0.6
        assert await job == expected
        for selected in (_path(), (_path()[1],)):
            try:
                expected = _project(selected)
            except ValueError:
                with pytest.raises(ValueError):
                    await module.project_coding_activation_attempt_path_v2_async(
                        selected, current_session_id="session-1"
                    )
            else:
                assert (
                    await module.project_coding_activation_attempt_path_v2_async(
                        selected, current_session_id="session-1"
                    )
                    == expected
                )
        job = asyncio.create_task(
            module.project_coding_activation_attempt_path_v2_async(
                records, current_session_id="session-1"
            )
        )
        await asyncio.sleep(0)
        stopped = clock[0]
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        assert clock[0] == stopped
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]

    asyncio.run(scenario())


def _guard_manager(records):
    from types import SimpleNamespace

    from loushang.coding.session_manager import SessionManager

    manager = object.__new__(SessionManager)
    manager.persist = True
    manager._transcript = SimpleNamespace(
        revision=len(records),
        leaf_id=records[-1].record_id if records else None,
        active_path=lambda: records,
        header=SimpleNamespace(conversation_id="session-1", metadata={}),
    )
    return manager


def _neutral_record(record_id, parent_id=None):
    from loushang.harness.conversation import ConversationRecord

    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind="agent.extension",
        payload_version=1,
        created_at="2026-10-21",
        payload=ExtensionData("loushang.model-input-v2.node-bundle", {}),
    )


def _select_guard_path(manager, records):
    manager._transcript.revision += 1
    manager._transcript.leaf_id = records[-1].record_id if records else None
    manager._transcript.active_path = lambda: records


@pytest.mark.parametrize("prepare", [False, True])
def test_model_input_metadata_extension_reuses_completed_activation_guard(
    monkeypatch, prepare
):
    import asyncio

    from loushang.coding import session_manager as module

    records = tuple(
        _neutral_record(str(index), str(index - 1) if index else None)
        for index in range(120)
    )
    manager = _guard_manager(records)
    manager.require_no_unsettled_resume_activation()
    original = module.project_coding_activation_attempt_path_v2
    selected = (*records, _neutral_record("new-bundle", records[-1].record_id))
    assert _project(selected).status == "none"
    _select_guard_path(manager, selected)

    def unexpected(*args, **kwargs):
        raise AssertionError("ordinary Model Input commit replayed all history")

    monkeypatch.setattr(module, "project_coding_activation_attempt_path_v2", unexpected)
    monkeypatch.setattr(
        module, "project_coding_activation_attempt_path_v2_async", unexpected
    )
    if prepare:
        asyncio.run(manager.prepare_resume_activation_guard())
    else:
        manager.require_no_unsettled_resume_activation()
    assert manager._activation_guard_snapshot == (121, "new-bundle")
    assert original(selected, current_session_id="session-1").status == "none"


@pytest.mark.parametrize(
    "change",
    [
        "branch",
        "parent",
        "duplicate",
        "binding-v1",
        "binding-v2",
        "binding-future",
        "intent",
        "publication",
        "invalidated",
    ],
)
def test_activation_guard_extension_keeps_full_validation_fences(monkeypatch, change):
    from loushang.coding import session_manager as module
    from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired

    first, second = _neutral_record("first"), _neutral_record("second", "first")
    manager = _guard_manager((first, second))
    manager.require_no_unsettled_resume_activation()
    tail = _neutral_record("third", "second")
    selected = (first, second, tail)
    if change == "branch":
        selected = (first, _neutral_record("other", "first"))
    elif change == "parent":
        selected = (first, second, replace(tail, parent_id="elsewhere"))
    elif change == "duplicate":
        selected = (first, second, replace(tail, record_id="first"))
    elif change.startswith("binding-"):
        version = {"binding-v1": "V1", "binding-v2": "V2", "binding-future": "V3"}[
            change
        ]
        selected = (
            first,
            second,
            replace(tail, metadata={f"coding.runtimeBinding{version}": {}}),
        )
    elif change == "intent":
        selected = (
            first,
            second,
            replace(tail, payload=ExtensionData("coding.activation-attempt/v3", {})),
        )
    elif change == "publication":
        manager._resume_runtime_publication_pending = True
    else:
        manager._activation_guard_snapshot = None
    _select_guard_path(manager, selected)
    seen = []
    original = module.project_coding_activation_attempt_path_v2

    def project(records, **kwargs):
        seen.append(records)
        return original(records, **kwargs)

    monkeypatch.setattr(module, "project_coding_activation_attempt_path_v2", project)
    if change in {"branch", "invalidated"}:
        manager.require_no_unsettled_resume_activation()
    else:
        with pytest.raises(CodingResumeRecoveryRequired):
            manager.require_no_unsettled_resume_activation()
    assert len(seen) == (0 if change == "publication" else 1)


def test_bound_history_keeps_local_proof_check_after_metadata_extension():
    from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired

    manager, records, attempt = _bound_guard_manager()
    manager._resume_committed_input = None
    manager.require_no_unsettled_resume_activation()
    manager._resume_committed_input = (attempt, records[-1], "changed-digest")
    _select_guard_path(
        manager, (*records, _neutral_record("bundle", records[-1].record_id))
    )
    with pytest.raises(CodingResumeRecoveryRequired, match="input_changed"):
        manager.require_no_unsettled_resume_activation()


@pytest.mark.parametrize("fault", ["v2", "future", "caller-mutation", "branch"])
def test_append_guard_checks_committed_metadata_and_selected_prefix(monkeypatch, fault):
    import asyncio

    from loushang.coding import session_manager as module
    from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired

    async def scenario():
        first = _neutral_record("first")
        manager = _guard_manager((first,))
        metadata = {
            "coding.runtimeBindingV3"
            if fault == "future"
            else "coding.runtimeBindingV2": {}
        }

        async def append(self, message, *, metadata):
            committed = replace(
                _neutral_record("new", "first"), payload=message, metadata=metadata
            )
            records = (first, committed)
            if fault == "branch":
                # A branch can change during the awaited write without an extra
                # revision. A pending future intent must still block admission.
                intent = replace(
                    _neutral_record("other"),
                    payload=ExtensionData("coding.activation-attempt/v3", {}),
                )
                records = (intent, replace(committed, parent_id="other", metadata={}))
            _select_guard_path(manager, records)
            manager._transcript.get = lambda key: next(
                (record for record in records if record.record_id == key), None
            )
            if fault == "caller-mutation":
                metadata.clear()
            return committed.record_id

        monkeypatch.setattr(module.ProductTranscriptSession, "append_message", append)
        await manager.append_message(
            UserMessage(role="user", content="next", timestamp=0.0), metadata=metadata
        )
        with pytest.raises(CodingResumeRecoveryRequired):
            manager.require_no_unsettled_resume_activation()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["none", "cancel", "branch", "publication"])
def test_async_activation_guard_publishes_only_the_current_completed_path(
    monkeypatch, change
):
    import asyncio
    from types import SimpleNamespace

    from loushang.coding import session_manager as module
    from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired

    async def scenario():
        manager = object.__new__(module.SessionManager)
        manager.persist = True
        manager._transcript = SimpleNamespace(
            revision=1,
            leaf_id="left",
            active_path=lambda: (),
            header=SimpleNamespace(conversation_id="session-1"),
        )
        entered, release = asyncio.Event(), asyncio.Event()
        selected = []

        async def held(records, *, current_session_id):
            selected.append((manager._transcript.revision, manager._transcript.leaf_id))
            entered.set()
            await release.wait()
            return _project(records)

        monkeypatch.setattr(
            module,
            "project_coding_activation_attempt_path_v2_async",
            held,
            raising=False,
        )
        job = asyncio.create_task(manager.prepare_resume_activation_guard())
        await entered.wait()
        assert manager._activation_guard_snapshot is None
        if change == "cancel":
            job.cancel()
            with pytest.raises(asyncio.CancelledError):
                await job
            assert manager._activation_guard_snapshot is None
        else:
            if change == "branch":
                manager._transcript.leaf_id = "right"
                manager._transcript.revision = 2
            elif change == "publication":
                manager._resume_runtime_publication_pending = True
            release.set()
            if change == "publication":
                with pytest.raises(
                    CodingResumeRecoveryRequired, match="publication_pending"
                ):
                    await job
                assert manager._activation_guard_snapshot is None
            else:
                await job
                expected = (2, "right") if change == "branch" else (1, "left")
                assert manager._activation_guard_snapshot == expected
                assert selected == (
                    [(1, "left"), (2, "right")] if change == "branch" else [(1, "left")]
                )

                def unexpected(*args, **kwargs):
                    raise AssertionError("completed guard replayed the entire history")

                monkeypatch.setattr(
                    module, "project_coding_activation_attempt_path_v2", unexpected
                )
                manager.require_no_unsettled_resume_activation()
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]

    asyncio.run(scenario())


def _bound_guard_manager():
    from types import SimpleNamespace

    from loushang.ai.types import TextPart
    from loushang.coding.resume_activation_attempt_v2 import (
        validate_coding_activation_attempt_v2_record,
    )
    from loushang.coding.resume_input_lookup import coding_resume_input_record_digest

    records = _path(
        message=UserMessage(
            role="user", content=[TextPart(type="text", text="continue")], timestamp=1.0
        )
    )
    manager = _guard_manager(records)
    attempt = validate_coding_activation_attempt_v2_record(records[0])
    manager._lifecycle_session = SimpleNamespace(_writer_owner=object())
    manager._resume_committed_attempt = (attempt, records[0].created_at)
    manager._resume_committed_input = (
        attempt,
        records[1],
        coding_resume_input_record_digest(records[1]),
    )
    return manager, records, attempt


@pytest.mark.parametrize(
    "fault", ["none", "input", "intent", "owner", "pending", "digest", "attempt"]
)
def test_bound_guard_reuses_validation_and_preserves_current_input_identity(
    monkeypatch, fault
):
    from loushang.ai.types import TextPart
    from loushang.coding import session_manager as module
    from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired

    manager, records, attempt = _bound_guard_manager()
    original = module.project_coding_activation_attempt_path_v2
    calls = []

    def project(records, **kwargs):
        calls.append(records)
        return original(records, **kwargs)

    monkeypatch.setattr(module, "project_coding_activation_attempt_path_v2", project)
    manager.require_no_unsettled_resume_activation()
    assert len(calls) == 1, "local identity proof replayed the whole path a second time"
    selected = (*records, _neutral_record("bundle", records[-1].record_id))
    _select_guard_path(manager, selected)
    manager.require_no_unsettled_resume_activation()
    for _ in range(2):
        assert (
            manager._require_committed_resume_input(
                attempt.attempt_id, records[-1].record_id
            )[1]
            is records[-1]
        )
    assert len(calls) == 1, (
        "ordinary metadata/input verification replayed bound history"
    )
    if fault == "none":
        return
    if fault == "input":
        records[1].payload.content.append(TextPart(type="text", text="changed"))
    elif fault == "intent":
        records[0].payload.data["version"] = True
    elif fault == "owner":
        manager._lifecycle_session._writer_owner = None
    elif fault == "pending":
        manager._resume_first_input = object()
    elif fault == "digest":
        manager._resume_committed_input = (attempt, records[1], "0" * 64)
    else:
        manager._resume_committed_attempt = (
            replace(attempt, subject_digest="0" * 64),
            records[0].created_at,
        )
    with pytest.raises(CodingResumeRecoveryRequired):
        manager._require_committed_resume_input(
            attempt.attempt_id, records[-1].record_id
        )


@pytest.mark.parametrize("fact", ["input", "intent"])
def test_bound_guard_does_not_cache_changed_historical_sensitive_facts(fact):
    from loushang.ai.types import TextPart
    from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired

    manager, records, _ = _bound_guard_manager()
    manager._resume_committed_input = None
    manager.require_no_unsettled_resume_activation()
    old_snapshot = manager._activation_guard_snapshot
    if fact == "input":
        records[1].payload.content.append(TextPart(type="text", text="changed"))
    else:
        records[0].payload.data["version"] = True
    _select_guard_path(
        manager, (*records, _neutral_record("bundle", records[-1].record_id))
    )
    with pytest.raises(CodingResumeRecoveryRequired):
        manager.require_no_unsettled_resume_activation()
    assert manager._activation_guard_snapshot == old_snapshot


def test_async_bound_guard_does_not_publish_facts_changed_while_suspended(monkeypatch):
    import asyncio

    from loushang.coding import session_manager as module
    from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired

    async def scenario():
        manager, records, _ = _bound_guard_manager()
        manager._resume_committed_input = None
        entered, release = asyncio.Event(), asyncio.Event()

        async def project(records, **kwargs):
            result = module.project_coding_activation_attempt_path_v2(records, **kwargs)
            entered.set()
            await release.wait()
            return result

        monkeypatch.setattr(
            module, "project_coding_activation_attempt_path_v2_async", project
        )
        job = asyncio.create_task(manager.prepare_resume_activation_guard())
        await entered.wait()
        records[0].payload.data["version"] = True
        release.set()
        with pytest.raises(CodingResumeRecoveryRequired):
            await job
        assert manager._activation_guard_snapshot is None

    asyncio.run(scenario())


def test_current_input_proof_rejects_branch_changed_during_identity_hash(monkeypatch):
    from loushang.coding import session_manager as module
    from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired

    manager, records, attempt = _bound_guard_manager()
    manager.require_no_unsettled_resume_activation()
    original = module.coding_resume_input_record_digest
    changed = False

    def digest(record):
        nonlocal changed
        if not changed:
            changed = True
            _select_guard_path(manager, records[:1])
        return original(record)

    monkeypatch.setattr(module, "coding_resume_input_record_digest", digest)
    with pytest.raises(CodingResumeRecoveryRequired, match="input_changed"):
        manager._require_committed_resume_input(
            attempt.attempt_id, records[-1].record_id
        )


@pytest.mark.parametrize("prepare", [False, True])
def test_guard_rechecks_mutable_sensitive_facts_at_the_cached_revision(prepare):
    import asyncio

    from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired

    manager, records, _ = _bound_guard_manager()
    manager._resume_committed_input = None
    manager.require_no_unsettled_resume_activation()
    records[0].payload.data["version"] = True
    with pytest.raises(CodingResumeRecoveryRequired):
        if prepare:
            asyncio.run(manager.prepare_resume_activation_guard())
        else:
            manager.require_no_unsettled_resume_activation()
