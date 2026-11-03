from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from loushang.coding import package_legacy_disabled_acceptance as acceptance_module
from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_legacy_classification import CodingScopedLegacyDisableV1
from loushang.coding.package_legacy_disabled_acceptance import (
    CodingLegacyDisabledOnlyAcceptanceError,
    CodingLegacyDisabledOnlyAcceptanceV1,
    accept_coding_first_b_disabled_only,
    read_coding_first_b_disabled_only_acceptance,
)
from loushang.coding.package_legacy_disabled_review import (
    CodingLegacyDisabledOnlyReviewError,
    CodingLegacyDisabledOnlyReviewV1,
    review_coding_first_b_disabled_only,
)
from loushang.coding.package_pre_b_snapshot import (
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
)
from loushang.coding.package_product_runtime import (
    _bootstrap_coding_builtin_plugin,
    open_coding_fenced_product_application_owner,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)


def _snapshot_files(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        sorted(
            (str(path.relative_to(root)), path.read_bytes())
            for path in root.rglob("*")
            if path.is_file()
        )
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX no-follow acceptance read")
def test_disabled_acceptance_read_refuses_file_swap_after_parent_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "product-state"
    state_root.mkdir(mode=0o700)
    path = state_root / "legacy-disabled-acceptance.jsonl"
    path.write_bytes(b"accepted\n")
    path.chmod(0o600)
    redirect = tmp_path / "redirect"
    redirect.write_bytes(b"must not read\n")
    original_open = os.open
    swapped = False

    def swap_before_file_open(
        name: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if name == path.name and dir_fd is not None and not swapped:
            swapped = True
            path.rename(state_root / "saved-acceptance.jsonl")
            path.symlink_to(redirect)
        return original_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(acceptance_module.os, "open", swap_before_file_open)
    with pytest.raises(OSError):
        acceptance_module._read_private_acceptance(path)
    assert swapped
    assert redirect.read_bytes() == b"must not read\n"


@pytest.mark.skipif(os.name != "posix", reason="POSIX exclusive acceptance publish")
def test_disabled_acceptance_publish_refuses_name_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "product-state"
    state_root.mkdir(mode=0o700)
    path = state_root / "legacy-disabled-acceptance.jsonl"
    redirect = tmp_path / "redirect"
    redirect.write_bytes(b"must not write\n")
    review = CodingLegacyDisabledOnlyReviewV1(
        store_id="store",
        namespace_id="a" * 64,
        scope_id="scope",
        first_fence_id="b" * 64,
        snapshot_receipt_id="c" * 64,
        source_projection_digest="d" * 64,
        disabled_plugins=(CodingScopedLegacyDisableV1("global", "coding.base"),),
    )
    receipt = CodingLegacyDisabledOnlyAcceptanceV1.create(review)
    original_link = os.link
    swapped = False

    def swap_before_publish(
        source: str | os.PathLike[str],
        target: str | os.PathLike[str],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal swapped
        if target == path.name and not swapped:
            swapped = True
            path.symlink_to(redirect)
        original_link(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(acceptance_module.os, "link", swap_before_publish)
    with pytest.raises(FileExistsError):
        acceptance_module._write_private_acceptance(path, receipt)
    assert swapped
    assert redirect.read_bytes() == b"must not write\n"
    assert sorted(item.name for item in state_root.iterdir()) == [path.name]


@pytest.mark.skipif(os.name != "posix", reason="POSIX first-B snapshot")
@pytest.mark.parametrize("old_state", (False, True))
def test_disabled_only_review_uses_immutable_first_fence_and_refuses_old_state(
    tmp_path: Path, old_state: bool
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    if old_state:
        lifecycle.desired_state.write_bytes(b"old desired state\n")
    global_path = tmp_path / "global-settings.json"
    project_path = workspace / ".loushang" / "settings.json"
    global_path.write_bytes(b'{"disabled_plugins":["coding.base"]}\n')
    project_path.parent.mkdir(mode=0o700)
    project_path.write_bytes(b'{"disabled_plugins":["coding.lsp.default"]}\n')
    settings = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    global_path.write_bytes(b'{"disabled_plugins":[]}\n')
    project_path.write_bytes(b'{"disabled_plugins":[]}\n')
    before = _snapshot_files(tmp_path)
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
        read_only=True,
    )
    try:
        if old_state:
            with pytest.raises(
                CodingLegacyDisabledOnlyReviewError, match="old Plugin state"
            ):
                review_coding_first_b_disabled_only(
                    lifecycle, owner, settings_manager=settings
                )
        else:
            first = review_coding_first_b_disabled_only(
                lifecycle, owner, settings_manager=settings
            )
            replay = review_coding_first_b_disabled_only(
                lifecycle, owner, settings_manager=settings
            )
            assert first == replay
            assert first.disabled_plugins == (
                CodingScopedLegacyDisableV1("global", "coding.base"),
                CodingScopedLegacyDisableV1("project", "coding.lsp.default"),
            )
            assert first.snapshot_receipt_id == (
                cutover.attempt.result.fence.request.snapshot_receipt_id
            )
            assert first.to_dict()["reviewVersion"] == 1
            assert str(tmp_path) not in json.dumps(first.to_dict())
    finally:
        owner.close()
    assert _snapshot_files(tmp_path) == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX first-B snapshot")
def test_disabled_only_review_refuses_configured_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    global_path = tmp_path / "global-settings.json"
    global_path.write_bytes(b'{"disabled_plugins":["coding.base"]}\n')
    project_path = workspace / ".loushang" / "settings.json"
    project_path.parent.mkdir(mode=0o700)
    project_path.write_bytes(b'{"plugin_sources":["/old/plugins"]}\n')
    settings = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="b" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    before = _snapshot_files(tmp_path)
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
        read_only=True,
    )
    try:
        with pytest.raises(
            CodingLegacyDisabledOnlyReviewError, match="not disabled-only"
        ):
            review_coding_first_b_disabled_only(
                lifecycle, owner, settings_manager=settings
            )
    finally:
        owner.close()
    assert _snapshot_files(tmp_path) == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX first-B snapshot")
def test_disabled_only_acceptance_is_explicit_durable_and_replayable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    global_path = tmp_path / "global-settings.json"
    global_path.write_bytes(b'{"disabled_plugins":["coding.base"]}\n')
    project_path = workspace / ".loushang" / "settings.json"
    settings = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=project_path,
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="c" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    global_path.write_bytes(b'{"disabled_plugins":[]}\n')
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        review = review_coding_first_b_disabled_only(
            lifecycle, owner, settings_manager=settings
        )
        with pytest.raises(
            CodingLegacyDisabledOnlyAcceptanceError, match="review ID changed"
        ):
            accept_coding_first_b_disabled_only(
                lifecycle,
                owner,
                settings_manager=settings,
                accepted_review_id="0" * 64,
            )
        receipt = accept_coding_first_b_disabled_only(
            lifecycle,
            owner,
            settings_manager=settings,
            accepted_review_id=review.review_id,
        )
        path = owner.prepare_product_state_root() / "legacy-disabled-acceptance.jsonl"
        first_bytes = path.read_bytes()
        assert len(first_bytes.splitlines()) == 1
        assert receipt.review == review
        replay = accept_coding_first_b_disabled_only(
            lifecycle,
            owner,
            settings_manager=settings,
            accepted_review_id=review.review_id,
        )
        assert replay == receipt
        assert path.read_bytes() == first_bytes
        read_owner = PackageProductPosixFencedRuntimeOwner.open(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
            read_only=True,
        )
        try:
            assert (
                read_coding_first_b_disabled_only_acceptance(
                    lifecycle, read_owner, settings_manager=settings
                )
                == receipt
            )
        finally:
            read_owner.close()
        document = json.loads(first_bytes)
        document["acceptanceId"] = "0" * 64
        path.write_text(json.dumps(document) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Journal record is invalid"):
            accept_coding_first_b_disabled_only(
                lifecycle,
                owner,
                settings_manager=settings,
                accepted_review_id=review.review_id,
            )
        read_owner = PackageProductPosixFencedRuntimeOwner.open(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
            read_only=True,
        )
        try:
            with pytest.raises(ValueError, match="Journal record is invalid"):
                read_coding_first_b_disabled_only_acceptance(
                    lifecycle, read_owner, settings_manager=settings
                )
        finally:
            read_owner.close()
    finally:
        owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX first-B snapshot")
def test_disabled_only_acceptance_refuses_product_desired_history(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    global_path = tmp_path / "global-settings.json"
    global_path.write_bytes(b'{"disabled_plugins":["coding.base"]}\n')
    settings = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="d" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    product_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        assert _bootstrap_coding_builtin_plugin(product_owner, "coding.base")
    finally:
        product_owner.close()
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        review = review_coding_first_b_disabled_only(
            lifecycle, owner, settings_manager=settings
        )
        with pytest.raises(
            CodingLegacyDisabledOnlyAcceptanceError, match="untouched Product"
        ):
            accept_coding_first_b_disabled_only(
                lifecycle,
                owner,
                settings_manager=settings,
                accepted_review_id=review.review_id,
            )
        assert not (
            owner.prepare_product_state_root() / "legacy-disabled-acceptance.jsonl"
        ).exists()
    finally:
        owner.close()
