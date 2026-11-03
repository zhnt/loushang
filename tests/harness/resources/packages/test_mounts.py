from __future__ import annotations

import json
from pathlib import Path

import pytest

from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore


def test_verified_package_mount_binds_root_digest_lease_and_relative_reads(
    tmp_path: Path,
) -> None:
    source = _plugin(tmp_path / "source")
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None

    mount = PackageResourceMount(
        root=published.package_root,
        content_digest=published.content_digest,
        revision_handle=handle,
    )

    assert mount.verified is True
    assert mount.verify() is None
    prompt = published.package_root / "prompts" / "review.md"
    assert mount.read_text(prompt) == "review v1"
    reference = mount.reference(prompt)
    assert reference is not None
    assert reference.content_digest == published.content_digest
    assert reference.relative_path == "resources/prompts/review.md"
    assert reference.kind == "file"


def test_verified_package_mount_rejects_mismatched_digest_and_escape(
    tmp_path: Path,
) -> None:
    source = _plugin(tmp_path / "source")
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None

    with pytest.raises(ValueError, match="content digest"):
        PackageResourceMount(
            root=published.package_root,
            content_digest="0" * 64,
            revision_handle=handle,
        )

    mount = PackageResourceMount(
        root=published.package_root,
        content_digest=published.content_digest,
        revision_handle=handle,
    )
    with pytest.raises(ValueError, match="outside Package mount"):
        mount.reference(tmp_path / "outside.md")
    with pytest.raises(ValueError, match="outside Package mount"):
        mount.read_text(tmp_path / "outside.md")
    with pytest.raises(ValueError, match="kind does not match"):
        mount.reference(
            published.package_root / "prompts" / "review.md",
            kind="directory",
        )


def test_path_backed_package_mount_preserves_legacy_read_semantics(
    tmp_path: Path,
) -> None:
    root = tmp_path / "package"
    root.mkdir()
    prompt = root / "review.md"
    prompt.write_text("review", encoding="utf-8")

    mount = PackageResourceMount(root=root)

    assert mount.verified is False
    assert mount.reference(prompt) is None
    assert mount.read_text(prompt) == "review"


@pytest.mark.parametrize("portable", (False, True))
def test_verified_revision_cancellation_preserves_handle_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, portable: bool,
) -> None:
    from concurrent.futures import CancelledError

    from loushang.harness.resources.plugins import revisions

    if portable:
        monkeypatch.setattr(revisions, "_supports_descriptor_relative_revision_io", lambda: False)
    source = _plugin(tmp_path / "source")
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None
    mount = PackageResourceMount(
        root=published.package_root, content_digest=published.content_digest,
        revision_handle=handle,
    )
    calls = 0

    def stop():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise CancelledError("revision scan cancelled")

    try:
        with pytest.raises(CancelledError, match="revision scan cancelled"):
            mount.verify(work_probe=stop)
        assert calls == 3
        assert handle.closed is False
        mount.verify()
        assert mount.read_text(published.package_root / "prompts" / "review.md") == "review v1"
    finally:
        mount.close()


@pytest.mark.parametrize("portable", (False, True))
def test_verified_revision_cancellation_checks_between_digest_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, portable: bool,
) -> None:
    from concurrent.futures import CancelledError

    from loushang.harness.resources.plugins import revisions

    if portable:
        monkeypatch.setattr(revisions, "_supports_descriptor_relative_revision_io", lambda: False)
    source = _plugin(tmp_path / "source")
    (source / "resources" / "prompts" / "review.md").write_bytes(b"a" * (256 * 1024))
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None
    digest_name = "_digest_file_portable" if portable else "_digest_file"
    original_digest = getattr(revisions, digest_name)
    chunks = 0
    in_digest = False

    def stop():
        nonlocal chunks
        if in_digest:
            chunks += 1
            if chunks == 2:
                raise CancelledError("digest read cancelled")

    def digest(*args, **kwargs):
        name = args[0].name if portable else args[1]
        original_probe = kwargs.get("work_probe")
        if name != "review.md" or original_probe is None:
            return original_digest(*args, **kwargs)

        def probe():
            nonlocal in_digest
            in_digest = True
            try:
                original_probe()
            finally:
                in_digest = False

        return original_digest(*args, **{**kwargs, "work_probe": probe})

    try:
        with monkeypatch.context() as patch:
            patch.setattr(revisions, digest_name, digest)
            with pytest.raises(CancelledError, match="digest read cancelled"):
                handle.verify(work_probe=stop)
        assert chunks == 2
        assert handle.closed is False
        handle.verify()
    finally:
        handle.close()


@pytest.mark.parametrize("verified", (False, True))
def test_package_text_capture_obeys_byte_budget_and_keeps_ordinary_reads(
    tmp_path: Path, verified: bool,
) -> None:
    source = _plugin(tmp_path / "source")
    original_path = source / "resources" / "prompts" / "review.md"
    original_path.write_bytes(b"first\r\nsecond\r\n")
    if verified:
        published = PluginRevisionStore(tmp_path / "revisions").publish(
            PluginManifestParser().parse(source)
        )
        mount = PackageResourceMount(
            root=published.package_root, content_digest=published.content_digest,
            revision_handle=published.revision_handle,
        )
    else:
        mount = PackageResourceMount(root=source / "resources")
    path = mount.root / "prompts" / "review.md"
    try:
        text, byte_count = mount.capture_text(path, max_bytes=100)
        assert text == mount.read_text(path)
        assert byte_count == len(b"first\r\nsecond\r\n")
        with pytest.raises(RuntimeError, match="byte budget"):
            mount.capture_text(path, max_bytes=3)
        assert mount.read_text(path) == text
    finally:
        mount.close()


def test_package_discovery_aggregate_budget_counts_raw_bytes_before_newline_conversion(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources._loader_discovery import (
        _discover_external_package_resources,
    )
    from loushang.harness.resources._safe_files import ResourceReadBudgetExceeded

    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for name in ("one.md", "two.md"):
        (prompts / name).write_bytes(b"\r\n" * 4)
    mount = PackageResourceMount(root=tmp_path)
    with pytest.raises(ResourceReadBudgetExceeded):
        _discover_external_package_resources((mount,), max_text_bytes=12)
    # Ordinary discovery uses the same mount and remains available after a
    # discarded speculative scan. Twelve bytes cover only one of these files.
    ordinary = _discover_external_package_resources((mount,))
    assert len(ordinary.prompts) == 2


@pytest.mark.parametrize("mode", ("path", "descriptor", "portable"))
def test_package_text_capture_cancels_between_byte_chunks_without_closing_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    from concurrent.futures import CancelledError

    from loushang.harness.resources.plugins import revisions

    if mode == "portable":
        monkeypatch.setattr(revisions, "_supports_descriptor_relative_revision_io", lambda: False)
    source = _plugin(tmp_path / "source")
    (source / "resources" / "prompts" / "review.md").write_bytes(b"a" * (256 * 1024))
    if mode == "path":
        mount = PackageResourceMount(root=source / "resources")
    else:
        published = PluginRevisionStore(tmp_path / "revisions").publish(
            PluginManifestParser().parse(source)
        )
        mount = PackageResourceMount(
            root=published.package_root, content_digest=published.content_digest,
            revision_handle=published.revision_handle,
        )
    calls = 0

    def stop():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CancelledError("package text read cancelled")

    path = mount.root / "prompts" / "review.md"
    try:
        with pytest.raises(CancelledError, match="package text read cancelled"):
            mount.capture_text(path, max_bytes=512 * 1024, work_probe=stop)
        assert calls == 2
        assert mount.read_text(path) == "a" * (256 * 1024)
        mount.verify()
    finally:
        mount.close()


def test_readonly_capture_pin_does_not_eagerly_verify_or_replace_ordinary_admission(tmp_path, monkeypatch) -> None:
    source = _plugin(tmp_path / "source")
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None

    def forbidden_verify(*args, **kwargs):
        raise RuntimeError("eager verification forbidden")

    with monkeypatch.context() as patch:
        patch.setattr(handle, "verify", forbidden_verify)
        pin = handle.acquire_readonly_capture()
        with pytest.raises(RuntimeError, match="eager verification forbidden"):
            handle.acquire()
    try:
        handle.close()
        pin.verify()
        with pin.open_file("resources/prompts/review.md") as stream:
            assert stream.read() == b"review v1"
    finally:
        pin.close()


def _plugin(root: Path) -> Path:
    prompt_root = root / "resources" / "prompts"
    prompt_root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "review-pack",
                "packageRoot": "resources",
            }
        ),
        encoding="utf-8",
    )
    (prompt_root / "review.md").write_text("review v1", encoding="utf-8")
    return root
