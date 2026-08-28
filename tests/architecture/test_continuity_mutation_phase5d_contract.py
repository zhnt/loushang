from __future__ import annotations

import ast
from pathlib import Path

CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/"
    "continuity-mutation-phase5d-contract.md"
)
PLUGIN_README_PATH = Path("docs/internals/architecture/harness/plugin/README.md")
MUTATION_PATH = Path("src/loushang/harness/continuity/mutation.py")
CONTINUITY_ROOT_PATH = Path("src/loushang/harness/continuity/__init__.py")


def test_phase5d_contract_is_indexed_and_implemented() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    readme = PLUGIN_README_PATH.read_text(encoding="utf-8")

    assert "# Continuity Mutation Foundation (Phase 5D Contract)" in contract
    assert "implemented incremental contract" in contract
    assert (
        "[Phase 5D Continuity Mutation Foundation]"
        "(continuity-mutation-phase5d-contract.md)"
    ) in readme


def test_phase5d_keeps_product_authority_separate_from_source_mutation() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    source = MUTATION_PATH.read_text(encoding="utf-8")

    for required in (
        "Provider prepares exact, unpublished deletion candidate",
        "Product authority durably accepts exact plan + source fingerprints",
        "Provider idempotently commits its own Domain deletion",
        "Product authority durably records completion",
        "The Product is the transaction coordinator",
    ):
        assert required in contract
    assert "class ContinuityDeletionAuthority(Protocol)" in source
    assert "class PreparedContinuityDeletion(Protocol)" in source
    assert "class ContinuityDeletionAuthorization" in source
    assert "def __init__(self) -> None:" in source
    assert "raise TypeError(\"Continuity deletion authorization is authority-issued\")" in source
    assert "Continuity deletion lease is owner-constructed" in source
    assert "Continuity mutation cleanup is owner-constructed" in source
    imported_modules = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    for forbidden_import in (
        "loushang.coding",
        "loushang.harness.plugin_management",
        "loushang.harness.transcript",
    ):
        assert not any(
            module == forbidden_import
            or module.startswith(f"{forbidden_import}.")
            for module in imported_modules
        )


def test_phase5d_freezes_exact_retryable_transaction_order() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    source = MUTATION_PATH.read_text(encoding="utf-8")

    ordered = (
        "Product cancellation is recorded before source cleanup",
        "source commit succeeds but Product completion fails",
        "caller cancellation during commit",
        "successful consume is idempotent",
    )
    positions = tuple(contract.index(item) for item in ordered)
    assert positions == tuple(sorted(positions))
    assert "self._abort_requested = True" in source
    assert "self._commit_task = task" in source
    assert "self._commit_started = True" in source
    assert "self._candidate.commit(self._plan)" in source
    assert "await self._candidate.close()" in source
    assert "await self._authority.complete_delete" in source
    assert "await self._authority.cancel_delete" in source
    assert "ContinuityMutationPendingCleanup" in source


def test_phase5d_public_surface_is_typed_and_handoff_is_explicit() -> None:
    root = CONTINUITY_ROOT_PATH.read_text(encoding="utf-8")
    contract = CONTRACT_PATH.read_text(encoding="utf-8")

    for public_name in (
        "AuthorizedContinuityDeletionLease",
        "ContinuityDeletionAuthority",
        "ContinuityDeletionPlanV1",
        "ContinuityDeletionReceiptV1",
        "PreparedContinuityDeletion",
        "prepare_authorized_continuity_deletion",
    ):
        assert public_name in root
    assert "Until Phase 5E binds an admitted Provider" in contract


def test_phase5d_handoff_requires_concrete_phase5e_recovery_binding() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")

    for required in (
        "concrete durable Product deletion authority",
        "generation-gates prepare, consume, abort, and pending cleanup",
        "recovers accepted-but-unsettled operations",
        "same reviewers' post-fix re-review",
    ):
        assert required in contract
