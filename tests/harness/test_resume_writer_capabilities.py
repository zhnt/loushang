from __future__ import annotations

import sys

import pytest

from loushang.harness.approval.plugin_activation import (
    PluginActivationDecisionJournal,
    PluginActivationJournalError,
)
from loushang.harness.approval.plugin_execution import (
    PluginExecutionDecisionJournal,
    PluginExecutionJournalError,
)
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournal,
    WorkerActivationStateJournalError,
)
from tests.harness.approval.test_plugin_activation_resume_context import (
    _enrolled as activation_enrolled,
)
from tests.harness.approval.test_plugin_execution_resume_context import (
    _enrolled as execution_enrolled,
)
from tests.harness.worker.test_resume_parent_context import _fixture as worker_fixture

_WORKER_OWNER = pytest.param(
    "worker",
    marks=pytest.mark.skipif(
        sys.platform != "linux", reason="Linux rooted Worker activation journal"
    ),
)


def _fixture(tmp_path, owner):
    if owner == "execution":
        journal, context = execution_enrolled(tmp_path)

        def constructor(required, journal_type=PluginExecutionDecisionJournal):
            return journal_type(
                journal.path,
                scope_kind=journal._scope_kind,
                scope_id=journal._scope_id,
                required_writer_capabilities=required,
            )

        return (
            journal,
            constructor,
            PluginExecutionJournalError,
            "plugin_execution_writer_protocol_unsupported",
        )
    if owner == "activation":
        journal, context, use = activation_enrolled(tmp_path)

        def constructor(required, journal_type=PluginActivationDecisionJournal):
            return journal_type(
                journal.path,
                scope_id=journal._scope_id,
                required_writer_capabilities=required,
            )

        return (
            journal,
            constructor,
            PluginActivationJournalError,
            "plugin_activation_writer_protocol_unsupported",
        )
    journal, receipt, coordinator, context = worker_fixture(tmp_path)
    coordinator.enroll_resume_parent(
        context, policy=receipt.policy, expected_state_revision=1
    )

    def constructor(required, journal_type=WorkerActivationStateJournal):
        return journal_type(
            journal.path,
            required_writer_capabilities=required,
        )

    return (
        journal,
        constructor,
        WorkerActivationStateJournalError,
        "worker_activation_writer_protocol_unsupported",
    )


@pytest.mark.parametrize("owner", ["execution", "activation", _WORKER_OWNER])
@pytest.mark.parametrize("partial_tail", [False, True])
def test_unsupported_native_writer_protocol_refuses_before_repair_or_enrollment(
    tmp_path, owner, partial_tail
):
    journal, constructor, error_type, error_code = _fixture(tmp_path, owner)
    if partial_tail:
        with journal.path.open("ab") as stream:
            stream.write(b'{"future-uncommitted":')
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    known = journal.writer_protocol_capabilities
    assert len(known) == 1
    future = next(iter(known)).removesuffix("v1") + "v2"
    with pytest.raises(error_type) as caught:
        constructor(known | {future})
    assert caught.value.code == error_code
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("owner", ["execution", "activation", _WORKER_OWNER])
def test_exact_native_capability_constructs_without_filesystem_effects(tmp_path, owner):
    journal, constructor, _, _ = _fixture(tmp_path, owner)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    selected = constructor(journal.writer_protocol_capabilities)
    assert selected.writer_protocol_capabilities == journal.writer_protocol_capabilities
    assert selected.path == journal.path
    if owner == "worker":
        assert selected.load_read_only()["stateVersion"] == 3
    else:
        assert selected.snapshot().journal_revision >= 2
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("owner", ["execution", "activation", _WORKER_OWNER])
@pytest.mark.parametrize("requirements", ["v1", {"v1"}, frozenset({1})])
def test_native_protocol_requirements_are_exact_strings_not_coercible_inputs(
    tmp_path, owner, requirements
):
    journal, constructor, _, _ = _fixture(tmp_path, owner)
    before = journal.path.read_bytes()
    with pytest.raises(TypeError):
        constructor(requirements)
    assert journal.path.read_bytes() == before


@pytest.mark.parametrize("owner", ["execution", "activation", _WORKER_OWNER])
def test_overridden_advertisement_cannot_expand_compiled_writer_support(
    tmp_path, owner
):
    journal, constructor, error_type, error_code = _fixture(tmp_path, owner)
    known = journal.writer_protocol_capabilities
    requested = known | {next(iter(known)).removesuffix("v1") + "v2"}
    advertised = type(
        "AdvertisedFutureWriter",
        (type(journal),),
        {"writer_protocol_capabilities": property(lambda self: requested)},
    )
    before = journal.path.read_bytes()
    with pytest.raises(error_type) as caught:
        constructor(requested, journal_type=advertised)
    assert caught.value.code == error_code
    assert journal.path.read_bytes() == before
