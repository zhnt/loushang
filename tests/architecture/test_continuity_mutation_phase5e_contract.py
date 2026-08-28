from __future__ import annotations

import ast
from pathlib import Path

CONTRACT = Path(
    "docs/internals/architecture/harness/plugin/"
    "continuity-mutation-phase5e-contract.md"
)
MUTATION = Path("src/loushang/harness/continuity/mutation.py")
PLUGIN_PROVIDER = Path("src/loushang/harness/continuity/plugin_provider.py")
PLUGIN_RUNTIME = Path("src/loushang/harness/continuity/plugin_runtime.py")
PRODUCT_JOURNAL = Path(
    "src/loushang/harness/plugin_management/continuity_mutation.py"
)
CODING = Path("src/loushang/coding/continuity.py")


def test_phase5e_contract_is_indexed_and_freezes_all_authority_layers() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    readme = Path(
        "docs/internals/architecture/harness/plugin/README.md"
    ).read_text(encoding="utf-8")

    assert "# Installed Continuity Mutation Lifecycle (Phase 5E Contract)" in contract
    assert "implemented incremental contract" in contract
    assert "Phase 5E Installed Continuity Mutation Lifecycle" in readme
    for required in (
        "Product-confirmed Hub.delete",
        "durable Product authority appends ACCEPTED",
        "generation registers the authorized mutation lease",
        "publication barrier",
        "only the process generation fingerprint may differ",
        "Instance/Package ownership pinned",
        "exact operation-scoped filesystem lock",
        "synchronously reserve the sole generation publication slot",
        "leaves the durable confirmed intent pending",
        "continuity.delete",
    ):
        assert required in contract


def test_phase5e_dependency_direction_is_enforced_by_ast() -> None:
    mutation_imports = _imports(MUTATION)
    provider_imports = _imports(PLUGIN_PROVIDER)
    runtime_imports = _imports(PLUGIN_RUNTIME)
    journal_imports = _imports(PRODUCT_JOURNAL)
    coding_imports = _imports(CODING)

    assert not any(item.startswith("loushang.harness.plugin_management") for item in mutation_imports)
    assert not any(item.startswith("loushang.harness.plugin_management") for item in provider_imports)
    assert not any(item.startswith("loushang.harness.plugin_management") for item in runtime_imports)
    assert "loushang.harness.continuity.mutation" in journal_imports
    assert "loushang.harness.plugin_management.continuity_mutation" not in coding_imports


def test_phase5e_generation_gate_and_recovery_are_real_code_paths() -> None:
    provider = PLUGIN_PROVIDER.read_text(encoding="utf-8")
    runtime = PLUGIN_RUNTIME.read_text(encoding="utf-8")
    journal = PRODUCT_JOURNAL.read_text(encoding="utf-8")

    provider_tree = ast.parse(provider)
    provider_class = next(
        node
        for node in provider_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PluginContinuityProvider"
    )
    methods = {
        node.name
        for node in provider_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"delete", "_prepare_delete"}.issubset(methods)
    assert "self._gate._register_lease(lease)" in provider
    assert "self._gate._register_pending_cleanup(wrapped)" in provider
    assert "recover_continuity_plugin_deletions" in runtime
    assert "await recover_continuity_plugin_deletions" in runtime
    assert "_reserve_continuity_plugin_publication" in runtime
    assert "class PluginContinuityDeletionJournal" in journal
    assert "class PluginContinuityDeletionAuthority" in journal
    assert "_execution_lock_target" in journal
    assert "owner_binding_fingerprint" in journal


def test_phase5e_coding_binding_is_explicit_and_activation_compatible() -> None:
    coding = CODING.read_text(encoding="utf-8")

    assert "deletion_authority: ContinuityDeletionRecoveryAuthority | None = None" in coding
    assert "publish_continuity_plugin_generation_with_mutations" in coding
    assert "if deletion_authority is None:" in coding
    assert "publish_continuity_plugin_generation(" in coding


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            result.add(node.module)
        elif isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
    return result
