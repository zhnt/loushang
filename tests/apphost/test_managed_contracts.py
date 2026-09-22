from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from loushang.apphost.managed import contracts
from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedHandoffV1,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    ManagedStopEvidenceV1,
    require_mux_name,
)


def _namespace() -> ManagedNamespaceV1:
    return ManagedNamespaceV1("/private/user/.loushang", 1000, "a" * 32)


def _instance() -> ManagedInstanceRefV1:
    return ManagedInstanceRefV1(
        _namespace().namespace_key,
        ManagedServiceKeyV1("coding", "/workspace").service_id,
        "b" * 32,
    )


def test_managed_values_are_pure_private_and_immutable(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("contract must not resolve native paths")

    monkeypatch.setattr(Path, "resolve", forbidden)
    namespace = _namespace()
    key = ManagedServiceKeyV1("coding", "/workspace")
    assert namespace.namespace_key == _namespace().namespace_key
    assert key.service_id == ManagedServiceKeyV1("coding", "/workspace").service_id
    assert "/private" not in repr(namespace)
    assert "/workspace" not in repr(key)
    with pytest.raises(FrozenInstanceError):
        key.workspace = "/other"  # type: ignore[misc]


def test_namespace_and_service_keys_cover_all_binding_dimensions():
    namespace = _namespace()
    assert len({namespace.namespace_key, *(
        replace(namespace, **change).namespace_key for change in (
            {"platform_home": "/another/home"}, {"user_id": 1001},
            {"machine_id": "b" * 32},
        )
    )}) == 4
    key = ManagedServiceKeyV1("coding", "/workspace")
    assert len({key.service_id, replace(key, workspace="/other").service_id,
                replace(key, product_id="work").service_id}) == 3
    assert len(key.service_id) == 64


@pytest.mark.parametrize("name", ["dev", "Dev", "review-2", "a_b", "A" * 64])
def test_mux_display_name(name):
    assert require_mux_name(name) == name


@pytest.mark.parametrize("name", ["", "a" * 65, "../dev", "dev:main", "-dev",
                                 "dev/main", "dev\n", "中文", "dev\0", 12, True])
def test_mux_name_rejects_invalid_without_echo(name):
    with pytest.raises(ManagedContractError, match="^invalid_managed_contract$"):
        require_mux_name(name)


@pytest.mark.parametrize("path", ["relative", "/a/../b", "/a/./b", "/a//b",
                                 "//host/a", "/trailing/", "/a\n", "/a\0",
                                 "/a\ud800", "", None])
def test_paths_are_lexically_normalized_without_native_admission(path):
    with pytest.raises(ManagedContractError):
        ManagedServiceKeyV1("coding", path)


@pytest.mark.parametrize("change", [{"user_id": True}, {"user_id": -1},
                                   {"user_id": 2**32}, {"machine_id": "host"},
                                   {"machine_id": "A" * 32}, {"platform_home": "/"}])
def test_namespace_rejects_unbounded_or_ambiguous_identity(change):
    with pytest.raises(ManagedContractError):
        replace(_namespace(), **change)


def test_closed_profile_and_exact_reference_validation():
    with pytest.raises(ManagedContractError):
        ManagedServiceKeyV1("coding", "/workspace", profile="legacy")
    for change in ({"namespace_key": "a"}, {"service_id": "b" * 32},
                   {"instance_id": "C" * 32}):
        with pytest.raises(ManagedContractError):
            replace(_instance(), **change)


def test_handoff_commit_cannot_be_aborted_or_reversed_by_lost_ack():
    provisional = ManagedHandoffV1(_instance(), "c" * 32)
    committed = provisional.commit()
    assert provisional.phase is ManagedHandoffPhaseV1.PROVISIONAL
    assert committed.phase is ManagedHandoffPhaseV1.COMMITTED
    assert committed.commit() == committed
    with pytest.raises(ManagedContractError):
        committed.abort()
    assert committed.request_stop().phase is ManagedHandoffPhaseV1.COMMITTED
    with pytest.raises(ManagedContractError):
        committed.request_stop().commit()


def test_stop_or_abort_fences_later_commit():
    provisional = ManagedHandoffV1(_instance(), "c" * 32)
    for value in (provisional.request_stop(), provisional.abort()):
        with pytest.raises(ManagedContractError):
            value.commit()
        assert value.abort().phase is ManagedHandoffPhaseV1.ABORTING
    assert provisional.abort().abort() == provisional.abort()
    for change in ({"phase": "committed"}, {"stop_requested": 1},
                   {"instance": object()}, {"attempt_id": "invalid"}):
        with pytest.raises(ManagedContractError):
            replace(provisional, **change)


@pytest.mark.parametrize("exited", [False, True])
@pytest.mark.parametrize("cleaned", [False, True])
@pytest.mark.parametrize("scope_settled", [False, True])
def test_stop_needs_exact_exit_application_cleanup_and_scope(exited, cleaned, scope_settled):
    evidence = ManagedStopEvidenceV1(_instance(), exited, cleaned, scope_settled)
    assert evidence.cleanly_stopped is (exited and cleaned and scope_settled)
    with pytest.raises(ManagedContractError):
        replace(evidence, process_exited=1)
    with pytest.raises(ManagedContractError):
        replace(evidence, application_cleanup_completed=0)
    with pytest.raises(ManagedContractError):
        replace(evidence, process_scope_settled=1)


def test_contract_edge_has_only_closed_standard_library_dependencies():
    source = Path(contracts.__file__).read_text()
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imports.add(node.module)
    assert imports <= {"__future__", "re", "dataclasses", "enum", "hashlib", "pathlib"}
