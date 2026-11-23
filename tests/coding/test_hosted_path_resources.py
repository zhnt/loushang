from contextlib import suppress
from types import SimpleNamespace

import pytest

from loushang.appserver.execution.model import ResourceRefV1
from loushang.appserver.execution.resources import SessionResourceQueryV1
from loushang.appserver.protocol import AppServiceError
from loushang.coding.hosted.resources import HostedResourceAccess
from loushang.coding.hosted_workspace import CodingHostedWorkspace


def test_reference_does_not_copy_contents_or_grant_paths(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    resource_path = workspace / "resources"
    resource_path.mkdir()
    (resource_path / "sample.py").write_text("inside\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n")
    with suppress(OSError):
        (resource_path / "link").symlink_to(outside)
    current = [workspace]
    env = CodingHostedWorkspace(
        workspace, workspace, None, workspace, (workspace,), (sessions,),
        lambda: tuple(current), lambda: current[0] if current else None,
    )
    records = []
    access = HostedResourceAccess("session", sessions, lambda: records, env)
    with pytest.raises(AppServiceError):
        access.exchange(SessionResourceQueryV1("reference", path=str(outside)))
    resource, = access.exchange(SessionResourceQueryV1("reference", path=str(resource_path))).resources
    assert resource.kind == "directory" and resource.source == "host_reference"
    with pytest.raises(AppServiceError):
        access.resolve_host(resource.id, "sample.py")
    ref = ResourceRefV1(resource.id, resource.id)
    records.append(SimpleNamespace(payload=None, metadata=access.input_metadata((ref,))))
    restored = HostedResourceAccess("session", sessions, lambda: records, env)
    assert restored.associated() == (resource,)
    assert restored.resolve_host(resource.id, "sample.py")[1] == resource_path / "sample.py"
    for bad in ("../outside.txt", str(outside), "link/../.."):
        with pytest.raises(AppServiceError):
            restored.resolve_host(resource.id, bad)
    if (resource_path / "link").is_symlink():
        with pytest.raises(AppServiceError):
            restored.resolve_host(resource.id, "link")
    assert restored.exchange(SessionResourceQueryV1("read", resource.id)).data == ""
    with pytest.raises(AppServiceError):
        restored.images((ResourceRefV1("a" * 64, "a" * 64),))
    current.clear()
    assert restored.associated() == (resource,)
    with pytest.raises(AppServiceError):
        restored.resolve_host(resource.id, "sample.py")
