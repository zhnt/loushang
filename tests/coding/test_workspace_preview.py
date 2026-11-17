import asyncio
import os

import pytest

from loushang.apphost.managed._workspace_preview import read_workspace_preview
from loushang.apphost.workspace_registry import WorkspacePreviewError
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError


def test_reads_current_utf8_and_resolves_links_from_preview_directory(tmp_path):
    root = tmp_path.resolve()
    (root / "guide").mkdir()
    (root / "README.md").write_text("# 工作区", encoding="utf-8")
    assert read_workspace_preview(root, r"guide\..\README.md", "").text == "# 工作区"
    result = read_workspace_preview(root, "../README.md", "guide")
    assert result.path == "README.md"
    assert result.text == "# 工作区"
    (root / "README.md").write_text("# 已更新", encoding="utf-8")
    assert read_workspace_preview(root, "README.md", "").text == "# 已更新"


def test_lists_bounded_directory_entries_and_can_preview_workspace_root(tmp_path):
    root = tmp_path.resolve()
    (root / "docs").mkdir()
    (root / "notes.txt").write_text("notes", encoding="utf-8")
    preview = read_workspace_preview(root, ".", "")
    assert preview.path == "."
    assert preview.entries == (
        ("docs", "directory"), ("notes.txt", "file"),
    )
    assert not preview.limited
    for index in range(160):
        (root / "docs" / str(index)).touch()
    preview = read_workspace_preview(root, "docs/", "")
    assert preview.path == "docs"
    assert 0 < len(preview.entries) <= 128
    assert preview.limited


@pytest.mark.parametrize("reference", ["../outside.txt", "/outside.txt", r"C:\outside.txt", "//host/share", "file:outside", r"..\outside.txt"])
def test_rejects_references_outside_workspace(tmp_path, reference):
    with pytest.raises(WorkspacePreviewError) as rejected:
        read_workspace_preview(tmp_path.resolve(), reference, "")
    assert rejected.value.code == AppErrorCodeV1.PERMISSION_DENIED


def test_does_not_follow_file_or_directory_links(tmp_path):
    root = tmp_path.resolve() / "workspace"
    root.mkdir()
    outside = root.parent / "notes.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (root / "link.txt").symlink_to(outside)
        (root / "elsewhere").symlink_to(root.parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("native symlinks are unavailable")
    for reference in ("link.txt", "elsewhere/notes.txt"):
        with pytest.raises(WorkspacePreviewError) as rejected:
            read_workspace_preview(root, reference, "")
        assert rejected.value.code == AppErrorCodeV1.PERMISSION_DENIED
    assert read_workspace_preview(root, ".", "").entries == ()


@pytest.mark.parametrize(
    ("name", "content", "error"),
    [
        ("missing.txt", None, "not_found"),
        ("sample.txt", b"\x00data", "workspace_preview_binary"),
        ("unknown.txt", b"\xff", "workspace_preview_binary"),
        ("large.txt", b"a" * (129 * 1024), "workspace_preview_too_large"),
    ],
)
def test_file_failures_return_safe_codes(tmp_path, name, content, error):
    if content is not None:
        (tmp_path / name).write_bytes(content)
    with pytest.raises(WorkspacePreviewError) as rejected:
        read_workspace_preview(tmp_path.resolve(), name, "")
    assert rejected.value.code == error


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO required")
def test_does_not_read_special_files(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(WorkspacePreviewError) as rejected:
        read_workspace_preview(tmp_path.resolve(), "pipe", "")
    assert rejected.value.code == AppErrorCodeV1.PERMISSION_DENIED


def test_catalog_requires_the_exact_registered_workspace_scope(tmp_path):
    from loushang.apphost.managed.workspaces import WorkspaceRegistry
    from loushang.appserver.protocol import WorkspaceRequestV1
    from loushang.appserver.protocol.workspace_preview import WorkspacePreviewRequestV1
    from loushang.coding.workspace_catalog import CodingWorkspaceCatalog

    registry = WorkspaceRegistry(tmp_path / "registry")
    catalog = CodingWorkspaceCatalog(registry, tmp_path / "sessions", tmp_path / "stores")
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "README.md").write_text("project file", encoding="utf-8")

    def request(fingerprint):
        return WorkspaceRequestV1(
            "preview", str(workspace.resolve()),
            preview=WorkspacePreviewRequestV1("README.md", "", fingerprint),
        )

    async def scenario():
        await catalog.load()
        try:
            with pytest.raises(AppServiceError) as unregistered:
                await catalog.workspace(request("0" * 64))
            assert unregistered.value.code == AppErrorCodeV1.NOT_FOUND
            await catalog.register(str(workspace))
            scope = await catalog.select(str(workspace))
            with pytest.raises(AppServiceError) as wrong_scope:
                await catalog.workspace(request("0" * 64))
            assert wrong_scope.value.code == AppErrorCodeV1.PERMISSION_DENIED
            result = await catalog.workspace(request(scope.fingerprint))
            assert result.workspaces[0].preview.text == "project file"
            await catalog.workspace(WorkspaceRequestV1("unregister", str(workspace.resolve())))
            with pytest.raises(AppServiceError) as removed:
                await catalog.workspace(request(scope.fingerprint))
            assert removed.value.code == AppErrorCodeV1.NOT_FOUND
        finally:
            await catalog.close()

    asyncio.run(scenario())


def test_accepts_exact_read_limits_and_preserves_tabs_and_line_endings(tmp_path):
    root = tmp_path.resolve()
    text = "a" * (128 * 1024 - 3) + "\t\r\n"
    (root / "limit.txt").write_bytes(text.encode())
    assert read_workspace_preview(root, "limit.txt", "").text == text
    for index in range(127):
        (root / str(index)).touch()
    preview = read_workspace_preview(root, "./", "")
    assert len(preview.entries) == 128
    assert not preview.limited


def test_trailing_separator_is_for_directories(tmp_path):
    (tmp_path / "README.md").touch()
    with pytest.raises(WorkspacePreviewError) as missing:
        read_workspace_preview(tmp_path.resolve(), "README.md/", "")
    assert missing.value.code == AppErrorCodeV1.NOT_FOUND


@pytest.mark.parametrize(("reference", "code"), [
    ("/".join(["missing"] * 128), AppErrorCodeV1.NOT_FOUND),
    ("/".join(["missing"] * 129), AppErrorCodeV1.INVALID_REQUEST),
    ("missing/" + "x" * 4088, AppErrorCodeV1.NOT_FOUND),
    ("missing/" + "x" * 4089, AppErrorCodeV1.INVALID_REQUEST),
])
def test_resolved_paths_have_bounded_depth_and_length(tmp_path, reference, code):
    with pytest.raises(WorkspacePreviewError) as rejected:
        read_workspace_preview(tmp_path.resolve(), reference, "")
    assert rejected.value.code == code
