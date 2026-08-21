from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionError,
    PluginRevisionStore,
)


def test_revision_store_publishes_content_addressed_snapshot_and_keeps_source_identity(
    tmp_path: Path,
) -> None:
    source = _plugin(tmp_path / "source")
    package = PluginManifestParser().parse(source)
    store = PluginRevisionStore(tmp_path / "revisions")

    published = store.publish(package)

    handle = published.revision_handle
    assert handle is not None
    assert published.content_digest == handle.content_digest
    assert published.root == handle.root
    assert published.root == tmp_path / "revisions" / "sha256" / handle.content_digest
    assert published.package_root == published.root / "resources"
    assert published.source.path == source.resolve()
    assert published.manifest.root == published.root
    assert published.manifest_digest == package.manifest_digest
    assert published.root.stat().st_mode & 0o077 == 0
    assert (published.root / "resources" / "prompts" / "review.md").stat().st_mode & 0o077 == 0
    assert handle.verify() is None
    with handle.open_file("resources/prompts/review.md") as stream:
        assert stream.read() == b"review v1"
    assert handle.entry_kind("resources") == "directory"
    assert handle.entry_kind("resources/prompts/review.md") == "file"


def test_published_revision_isolated_from_later_source_changes(tmp_path: Path) -> None:
    source = _plugin(tmp_path / "source")
    store = PluginRevisionStore(tmp_path / "revisions")
    published = store.publish(PluginManifestParser().parse(source))
    handle = published.revision_handle
    assert handle is not None

    (source / "resources" / "prompts" / "review.md").write_text(
        "review v2", encoding="utf-8"
    )

    handle.verify()
    with handle.open_file("resources/prompts/review.md") as stream:
        assert stream.read() == b"review v1"


def test_equal_content_reuses_revision_but_returns_independent_handles(
    tmp_path: Path,
) -> None:
    first = _plugin(tmp_path / "first")
    second = _plugin(tmp_path / "second")
    store = PluginRevisionStore(tmp_path / "revisions")

    first_package = store.publish(PluginManifestParser().parse(first))
    second_package = store.publish(PluginManifestParser().parse(second))

    first_handle = first_package.revision_handle
    second_handle = second_package.revision_handle
    assert first_handle is not None
    assert second_handle is not None
    assert first_handle.root == second_handle.root
    assert first_handle.content_digest == second_handle.content_digest
    first_handle.close()
    assert first_handle.closed is True
    assert second_handle.closed is False
    second_handle.verify()


def test_revision_store_rejects_symbolic_links_without_publishing(
    tmp_path: Path,
) -> None:
    source = _plugin(tmp_path / "source")
    (source / "resources" / "prompts" / "linked.md").symlink_to("review.md")
    store = PluginRevisionStore(tmp_path / "revisions")

    with pytest.raises(PluginRevisionError) as caught:
        store.publish(PluginManifestParser().parse(source))

    assert caught.value.code == "unsafe_plugin_revision_entry"
    assert not any((tmp_path / "revisions" / "sha256").iterdir())


def test_verified_revision_detects_cache_mutation_and_fails_closed(
    tmp_path: Path,
) -> None:
    source = _plugin(tmp_path / "source")
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None
    prompt = published.root / "resources" / "prompts" / "review.md"
    prompt.parent.chmod(0o755)
    prompt.chmod(0o644)
    prompt.write_text("tampered", encoding="utf-8")

    with pytest.raises(PluginRevisionError) as caught:
        handle.verify()

    assert caught.value.code == "plugin_revision_changed"


def test_verified_revision_detects_publication_path_replacement(
    tmp_path: Path,
) -> None:
    source = _plugin(tmp_path / "source")
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None
    moved = published.root.with_name(f"{published.root.name}.moved")
    published.root.rename(moved)
    published.root.mkdir()

    with pytest.raises(PluginRevisionError) as caught:
        handle.verify()

    assert caught.value.code == "plugin_revision_changed"


def test_verified_revision_detects_entry_added_after_directory_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loushang.harness.resources.plugins.revisions as revisions_module

    source = _plugin(tmp_path / "source")
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None
    published.root.chmod(0o755)
    original_listdir = os.listdir
    changed = False

    def listdir_then_change(path: int) -> list[str]:
        nonlocal changed
        names = original_listdir(path)
        if not changed:
            changed = True
            (published.root / "late.txt").write_text("late", encoding="utf-8")
        return names

    monkeypatch.setattr(revisions_module.os, "listdir", listdir_then_change)

    with pytest.raises(PluginRevisionError) as caught:
        handle.verify()

    assert caught.value.code == "plugin_revision_changed"


def test_verified_revision_open_is_relative_nofollow_and_digest_checked(
    tmp_path: Path,
) -> None:
    source = _plugin(tmp_path / "source")
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None

    with pytest.raises(PluginRevisionError) as traversal:
        handle.open_file("../outside")
    assert traversal.value.code == "invalid_plugin_revision_path"

    prompt = published.root / "resources" / "prompts" / "review.md"
    prompt.parent.chmod(0o755)
    prompt.chmod(0o644)
    prompt.unlink()
    prompt.symlink_to(source / "resources" / "prompts" / "review.md")
    with pytest.raises(PluginRevisionError) as symlink:
        handle.open_file("resources/prompts/review.md")
    assert symlink.value.code == "plugin_revision_changed"


def test_closed_revision_handle_rejects_use(tmp_path: Path) -> None:
    source = _plugin(tmp_path / "source")
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None
    handle.close()

    with pytest.raises(PluginRevisionError) as caught:
        handle.verify()

    assert caught.value.code == "plugin_revision_handle_closed"
    with pytest.raises(PluginRevisionError) as entry_caught:
        handle.entry_kind("resources/prompts/review.md")
    assert entry_caught.value.code == "plugin_revision_handle_closed"


def _plugin(root: Path) -> Path:
    prompt_root = root / "resources" / "prompts"
    prompt_root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "review-pack",
                "version": "1",
                "packageRoot": "resources",
            }
        ),
        encoding="utf-8",
    )
    (prompt_root / "review.md").write_text("review v1", encoding="utf-8")
    executable = root / "runner.sh"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(os.stat(executable).st_mode | 0o100)
    return root
