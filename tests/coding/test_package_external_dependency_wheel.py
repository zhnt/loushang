from __future__ import annotations

import csv
import io
import os
import stat
import zipfile
from base64 import urlsafe_b64encode
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_external_dependency_wheel import (
    CodingExternalDependencyWheelCatalog,
    CodingExternalDependencyWheelError,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_preview import (
    CodingFencedProductReadOnlyPreviewOwner,
)
from loushang.coding.package_product_runtime import (
    admit_coding_external_dependency_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.harness.config.agent import SettingsManager
from loushang.harness.journal import journal_file_lock
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencySelectionRequestV1,
)


def _dependency_wheel_bytes(
    version: str,
    *,
    metadata_version: str | None = None,
    unrecorded_member: bool = False,
) -> bytes:
    dist_info = f"review_lib-{version}.dist-info"
    files = {
        "review_lib/__init__.py": b"VALUE = 1\n",
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
        ),
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: review-lib\n"
            f"Version: {metadata_version or version}\n\n"
        ).encode(),
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode()
        writer.writerow((name, f"sha256={digest}", str(len(body))))
    writer.writerow((f"{dist_info}/RECORD", "", ""))
    files[f"{dist_info}/RECORD"] = record.getvalue().encode()
    if unrecorded_member:
        files["review_lib/extra.py"] = b"UNRECORDED = True\n"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as wheel:
        for name, body in sorted(files.items()):
            member = zipfile.ZipInfo(name)
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            member.compress_type = zipfile.ZIP_STORED
            wheel.writestr(member, body)
    return output.getvalue()


def test_dependency_catalog_read_does_not_create_or_repair(tmp_path: Path) -> None:
    catalog = CodingExternalDependencyWheelCatalog(
        tmp_path / "bindings.jsonl",
        source_root=tmp_path / "sources",
        store_id="coding-store",
        namespace_id="d" * 64,
        scope_id="workspace:read-only",
        read_only=True,
    )
    lock = catalog.path.with_name(f"{catalog.path.name}.lock")
    assert catalog.read_records() == ()
    assert not catalog.path.exists()
    assert not lock.exists()
    catalog.path.write_bytes(b'{"partial":')
    with journal_file_lock(catalog.path, "exclusive"):
        pass
    original = catalog.path.read_bytes()
    with pytest.raises(CodingExternalDependencyWheelError, match="corrupt"):
        catalog.read_records()
    assert catalog.path.read_bytes() == original


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_dependency_sources_reopen_with_exact_versions_and_read_only_preview(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    for version in ("1.0", "2.0"):
        source = tmp_path / f"review_lib-{version}-py3-none-any.whl"
        source.write_bytes(_dependency_wheel_bytes(version))
        record = admit_coding_external_dependency_wheel(lifecycle, source=source)
        assert record.project_name == "review-lib"
        assert record.version == version
        assert (
            admit_coding_external_dependency_wheel(lifecycle, source=source) == record
        )
    duplicate_version = tmp_path / "review_lib-2.0.0-py3-none-any.whl"
    duplicate_version.write_bytes(_dependency_wheel_bytes("2.0.0"))
    with pytest.raises(CodingExternalDependencyWheelError, match="already bound"):
        admit_coding_external_dependency_wheel(lifecycle, source=duplicate_version)

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        policy = owner.runtime_owner.product_owner.policy
        dependencies = tuple(
            item for item in policy.dependencies if item.project_name == "review-lib"
        )
        assert tuple(item.version for item in dependencies) == ("1.0", "2.0")
        assert all(
            Path(item.source_identity).parent.name == "dependencies"
            and Path(item.source_identity).is_file()
            for item in dependencies
        )
        assert not any(
            binding.source_identity == item.source_identity
            for binding in policy.bindings
            for item in dependencies
        )
        request = PackageDependencySelectionRequestV1(
            operation_id="operation:dependency-source",
            attempt_epoch=1,
            parent_node_id="root",
            request_fingerprint="b" * 64,
            resolution_environment_fingerprint=(
                policy.resolution_environment_fingerprint
            ),
            requirement=NormalizedPackageRequirementV1.parse("review-lib>=1"),
        )
        selected = policy.resolve(request)
        assert selected.version == "2.0"
        assert (
            policy.source_authority()
            .verify_pinned_bytes(selected.canonical_source_identity, max_bytes=1024)
            .artifact_digest
            == selected.expected_artifact_digest
        )
        with CodingFencedProductReadOnlyPreviewOwner.open(lifecycle) as preview:
            assert preview.policy == policy
            assert (
                preview.selected_manifests.capture_selected_manifest_for_plugin(
                    "coding.base", max_files=64, max_total_bytes=1024 * 1024
                )
                .verified_manifest()
                .name
                == "coding.base"
            )
    finally:
        owner.close()

    controlled = Path(dependencies[0].source_identity)
    controlled.write_bytes(b"changed")
    with pytest.raises(CodingExternalDependencyWheelError, match="changed"):
        open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_dependency_capture_refuses_symlink_before_binding(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    target = tmp_path / "target.whl"
    target.write_bytes(b"untrusted")
    source = tmp_path / "review_lib-1.0-py3-none-any.whl"
    source.symlink_to(target)
    with pytest.raises(CodingExternalDependencyWheelError, match="invalid"):
        admit_coding_external_dependency_wheel(lifecycle, source=source)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
@pytest.mark.parametrize(
    "case", ("not_archive", "metadata_mismatch", "unrecorded_member")
)
def test_dependency_capture_refuses_invalid_wheel_before_binding(
    tmp_path: Path, case: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="a" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    source = tmp_path / "review_lib-1.0-py3-none-any.whl"
    source.write_bytes(
        b"not a Wheel"
        if case == "not_archive"
        else _dependency_wheel_bytes(
            "1.0",
            metadata_version="2.0" if case == "metadata_mismatch" else None,
            unrecorded_member=case == "unrecorded_member",
        )
    )
    with pytest.raises(CodingExternalDependencyWheelError, match="metadata is invalid"):
        admit_coding_external_dependency_wheel(lifecycle, source=source)
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        assert owner.runtime_owner.product_owner.policy.dependencies == ()
    finally:
        owner.close()
