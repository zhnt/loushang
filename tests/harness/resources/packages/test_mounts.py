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
