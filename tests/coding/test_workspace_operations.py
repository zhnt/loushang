from __future__ import annotations

from pathlib import Path

import pytest

from loushang.coding.workspace_operations import CodingWorkspaceOperations
from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.workspace.operations import LOCAL_TOOL_OPERATIONS


def test_standard_file_tools_do_not_borrow_linked_git_process_scope(tmp_path: Path) -> None:
    from loushang.coding.sandbox import CodingExecutionAuthority
    from loushang.harness.permissions import permission_profile_snapshot

    workspace = tmp_path / "worktree"
    metadata = tmp_path / "shared-git"
    workspace.mkdir()
    metadata.mkdir()
    target = metadata / "config"
    target.write_text("metadata", encoding="utf-8")
    requested = "standard"
    process_scope = EffectiveExecutionProfile(
        readable_roots=(workspace, metadata), writable_roots=(workspace, metadata),
    )
    ceiling = EffectiveExecutionProfile(readable_roots=(tmp_path,), writable_roots=(tmp_path,))
    authority = CodingExecutionAuthority(
        workspace_root=workspace, workspace_profile=process_scope, ceiling=ceiling,
        permission_snapshot=lambda: permission_profile_snapshot(requested),
    )
    operations = CodingWorkspaceOperations(
        root=workspace, operations=LOCAL_TOOL_OPERATIONS, execution_profile=ceiling,
        execution_profile_provider=authority.for_workspace_operation,
    )
    assert metadata in authority().readable_roots
    with pytest.raises(PermissionError):
        operations.read_text(target)
    requested = "full_access"
    assert operations.read_text(target) == "metadata"
    requested = "standard"
    with pytest.raises(PermissionError):
        operations.write_text(target, "blocked")
    assert target.read_text(encoding="utf-8") == "metadata"


def test_coding_workspace_operations_reject_paths_outside_the_admitted_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    operations = CodingWorkspaceOperations(
        root=root,
        operations=LOCAL_TOOL_OPERATIONS,
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(root,),
            writable_roots=(root,),
        ),
    )

    with pytest.raises(PermissionError, match="outside the admitted root"):
        operations.read_bytes(outside)


def test_coding_workspace_operations_enforce_read_only_admission(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "notes.txt"
    target.write_text("old", encoding="utf-8")
    operations = CodingWorkspaceOperations(
        root=root,
        operations=LOCAL_TOOL_OPERATIONS,
        execution_profile=EffectiveExecutionProfile(readable_roots=(root,)),
    )

    assert operations.read_bytes(target) == b"old"
    with pytest.raises(PermissionError, match="outside the admitted writable roots"):
        operations.write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old"


def test_coding_workspace_operations_honor_narrowed_and_denied_roots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    writable = root / "generated"
    denied = root / "private"
    writable.mkdir(parents=True)
    denied.mkdir()
    operations = CodingWorkspaceOperations(
        root=root,
        operations=LOCAL_TOOL_OPERATIONS,
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(root,),
            writable_roots=(writable,),
            denied_roots=(denied,),
        ),
    )

    operations.write_text(writable / "result.txt", "ok")
    with pytest.raises(PermissionError, match="writable roots"):
        operations.write_text(root / "source.txt", "no")
    with pytest.raises(PermissionError, match="denied"):
        operations.read_bytes(denied / "secret.txt")
