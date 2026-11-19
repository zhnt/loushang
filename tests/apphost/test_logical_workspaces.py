import json

import pytest

from loushang.apphost.managed.workspaces import WorkspaceRegistry


def test_legacy_membership_keeps_original_paths_after_rebinding(tmp_path):
    root = tmp_path / "registry"
    old_chat_origin = root / "temporary" / "old-chat"
    a = tmp_path / "project"
    b = tmp_path / "replacement"
    a.mkdir()
    b.mkdir()
    registry = WorkspaceRegistry(root)
    registry.open()
    try:
        (root / "workspaces.json").write_text(
            json.dumps(sorted((str(a), str(old_chat_origin)))), encoding="utf-8",
        )
        (root / "workspaces.json").chmod(0o600)
        project, = (item for item in registry.workspaces() if not item.default)
        assert registry.default_workspace().legacy_origins == (old_chat_origin,)
        assert registry.default_workspace().paths == ()
        a.rmdir()
        assert registry.path_status(project.paths[0]) == "missing"
        link = registry.update_path(project.id, project.paths[0].id, "frontend", str(b))
        registry.rename_workspace(project.id, "New name")
        assert link.id == project.paths[0].id
    finally:
        registry.close()
    registry = WorkspaceRegistry(root)
    registry.open()
    try:
        restored = registry.workspace(project.id)
        assert restored.legacy_origins == (a,)
        assert restored.default_path_id == link.id
        assert restored.name == "New name"
        assert restored.paths[0].path == b
        assert registry.path_status(restored.paths[0]) == "available"
        with pytest.raises(ValueError, match="workspace_has_history"):
            registry.delete_workspace(project.id)
    finally:
        registry.close()


def test_empty_workspace_multiple_paths_and_replaced_directory(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "registry")
    frontend = tmp_path / "frontend"
    backend = tmp_path / "outside" / "backend"
    frontend.mkdir()
    backend.mkdir(parents=True)
    registry.open()
    try:
        workspace = registry.create_workspace("Integration")
        assert workspace.paths == () and workspace.default_path_id is None
        assert registry.default_workspace().paths == ()
        first = registry.add_path(workspace.id, "frontend", str(frontend))
        second = registry.add_path(workspace.id, "backend", str(backend))
        registry.set_default_path(workspace.id, second.id)
        assert registry.workspace(workspace.id).default_path_id == second.id
        frontend.rmdir()
        frontend.symlink_to(backend, target_is_directory=True)
        assert registry.path_status(first) == "unsafe"
        assert registry.path_status(second) == "available"
        registry.remove_path(workspace.id, second.id)
        assert registry.workspace(workspace.id).default_path_id is None
        assert registry.workspace(workspace.id).paths == (first,)
    finally:
        registry.close()
