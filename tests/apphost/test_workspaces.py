from pathlib import Path

import pytest

from loushang.apphost.workspaces import WorkspaceRegistry


def test_registry_is_host_owned_persistent_and_does_not_change_cwd(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(a, target_is_directory=True)
    before = Path.cwd()
    owner = WorkspaceRegistry(tmp_path / "registry")
    try:
        owner.open()
        assert owner.list() == ()
        assert owner.register(str(alias)) == a
        owner.register(str(a))
        owner.register(str(b))
        assert owner.list() == (a, b)
        assert owner.select(str(alias)) == a
        with pytest.raises(ValueError):
            owner.register("relative")
        assert not list(a.iterdir()), "registration must not create Session or Runtime files"
        assert Path.cwd() == before
    finally:
        owner.close()
    reopened = WorkspaceRegistry(tmp_path / "registry")
    try:
        reopened.open()
        assert reopened.list() == (a, b)
        reopened.unregister(str(a))
        reopened.unregister(str(a))
        assert reopened.list() == (b,)
        with pytest.raises(ValueError, match="workspace_not_registered"):
            reopened.select(str(a))
    finally:
        reopened.close()


def test_registry_rejects_untrusted_store_permissions(tmp_path):
    root = tmp_path / "registry"
    root.mkdir(mode=0o777)
    root.chmod(0o777)
    owner = WorkspaceRegistry(root)
    try:
        with pytest.raises(Exception, match="managed_storage"):
            owner.open()
    finally:
        owner.close()


@pytest.mark.parametrize('document', ['{}', '["relative"]', '["/a", "/a"]', '["/b", "/a"]'])
def test_registry_refuses_corrupt_membership_instead_of_silently_starting_fresh(tmp_path, document):
    from loushang.apphost.managed._files import ManagedStorageError

    root = tmp_path / 'registry'
    owner = WorkspaceRegistry(root)
    try:
        owner.open()
        path = root / 'workspaces.json'
        path.write_text(document)
        path.chmod(0o600)
        with pytest.raises(ManagedStorageError, match='invalid_record'):
            owner.list()
    finally:
        owner.close()
