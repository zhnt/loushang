from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import stat
import zipfile
from base64 import urlsafe_b64encode
from contextlib import suppress
from hashlib import sha256
from importlib.metadata import version
from io import StringIO
from pathlib import Path

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.cli.application import run_cli
from loushang.coding.package_external_data_wheel import (
    CodingExternalDataWheelError,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_management_cli import (
    build_coding_fenced_product_management_cli_ports,
)
from loushang.coding.package_product_runtime import (
    CodingFencedProductApplicationSelection,
    admit_coding_external_data_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.plugin_management_cli import (
    build_coding_plugin_management_cli_binding,
    build_coding_plugin_management_cli_read_binding,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.cli.plugin_listing import list_plugin_records
from loushang.harness.cli.resource_toggles import (
    ResourceToggleRequest,
    apply_resource_toggles,
)
from loushang.harness.config.agent import ControlConfig, SettingsManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.product_retention import (
    PackageProductRetentionSettlementOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelCandidate,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_handoff import (
    PackageProductHandoffFinalizer,
)
from loushang.plugin import package, resource, skill_action


def _data_wheel(
    *, version: str = "1", executable_member: bool = False,
    actions_member: bool = False, requires_dist: bool = False,
    manifest_bytes: bytes | None = None,
    managed_actions_reservation: bool = False,
    skill_size: int | None = None,
) -> bytes:
    compiled = package(
        id="reviewpack",
        version=version,
        contributions=(
            resource.skill(
                contribution_id="review-skill", locator="skills/review",
                actions=(
                    skill_action(
                        id="review", script="scripts/review.py",
                        script_digest=sha256(b"print('review')\n").hexdigest(),
                        runtime="python",
                    ),
                ) if managed_actions_reservation else (),
            ),
        ),
    )
    files = {
        f"reviewpack/{item.path}": item.content for item in compiled.artifacts
        if not (managed_actions_reservation and item.path.endswith("/actions.json"))
    }
    if manifest_bytes is not None:
        files["reviewpack/plugin.json"] = manifest_bytes
    files["reviewpack/skills/review/SKILL.md"] = (
        f"---\nname: review\ndescription: Review files v{version}\n---\n"
        f"# Review v{version}\n"
    ).encode()
    if skill_size is not None:
        files["reviewpack/skills/review/SKILL.md"] = files[
            "reviewpack/skills/review/SKILL.md"
        ].ljust(skill_size, b" ")
    if executable_member:
        files["reviewpack/entry.py"] = b"raise RuntimeError('must never execute')\n"
    if actions_member:
        files["reviewpack/skills/review/actions.json"] = b"{}\n"
    files[f"reviewpack-{version}.dist-info/METADATA"] = (
        f"Metadata-Version: 2.1\nName: reviewpack\nVersion: {version}\n"
        + ("Requires-Dist: requests\n" if requires_dist else "")
        + "\n"
    ).encode()
    files[f"reviewpack-{version}.dist-info/WHEEL"] = (
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
    )
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((name, f"sha256={digest}", str(len(body))))
    writer.writerow((f"reviewpack-{version}.dist-info/RECORD", "", ""))
    files[f"reviewpack-{version}.dist-info/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            member.compress_type = zipfile.ZIP_STORED
            archive.writestr(member, body)
    return output.getvalue()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_wheel_capture_reopens_exact_product_binding(
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
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    body = b"wheel bytes are still untrusted at Source authorization"
    source.write_bytes(body)

    record = admit_coding_external_data_wheel(lifecycle, source=source)
    assert admit_coding_external_data_wheel(lifecycle, source=source) == record
    assert record.original_source == str(source)
    assert record.artifact_digest == sha256(body).hexdigest()

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        [binding] = [
            item
            for item in owner.runtime_owner.product_owner.policy.bindings
            if item.plugin_id == "reviewpack"
        ]
        assert binding.source_identity != str(source)
        assert Path(binding.source_identity).read_bytes() == body
        assert binding.artifact_digest == record.artifact_digest
        assert binding.plugin_manifest_path == "reviewpack/plugin.json"
        assert binding.source_trust_class == "local-data-only"
        product = owner.runtime_owner.product_owner
        factory = product.factory_for_session(
            session_id="external-malformed", cwd=workspace, runtime_id="external-malformed"
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="external-malformed", cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            outcome = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="external-malformed-install",
                    action="install",
                    source=binding.source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
            assert outcome.handled
            assert outcome.record is not None
            assert outcome.record.lifecycle == "failed"
        finally:
            runtime.dispose_runtime()
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id="reviewpack",
        )
        assert product.desired_state.snapshot().installation(key).selection.desired_state == "absent"
    finally:
        owner.close()

    source.write_bytes(b"changed after Product capture")
    reopened = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        [binding] = [
            item
            for item in reopened.runtime_owner.product_owner.policy.bindings
            if item.plugin_id == "reviewpack"
        ]
        assert Path(binding.source_identity).read_bytes() == body
    finally:
        reopened.close()
    Path(binding.source_identity).unlink()
    projection = build_coding_fenced_product_management_cli_ports(
        lifecycle
    ).queries.snapshot(
        PluginManagementQueryV1(
            correlation_id="test:missing-source",
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_ids=("reviewpack",),
        )
    )
    [installation] = projection.installations
    assert installation.source is not None
    assert installation.source.availability == "unavailable"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_wheel_refuses_symlink_and_oversize_before_capture(
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
        namespace_id="b" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    real = tmp_path / "real-wheel"
    real.write_bytes(b"bytes")
    source.symlink_to(real)
    with pytest.raises(CodingExternalDataWheelError, match="Source changed"):
        admit_coding_external_data_wheel(lifecycle, source=source)
    source.unlink()
    source.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(CodingExternalDataWheelError, match="exceeds budget"):
        admit_coding_external_data_wheel(lifecycle, source=source)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
@pytest.mark.parametrize(
    "executable_member,cleanup_failure",
    [(False, False), (True, False), (True, True)],
)
def test_external_data_wheel_product_admits_only_verified_skill_shape(
    tmp_path: Path, executable_member: bool, cleanup_failure: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="c" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    source.write_bytes(_data_wheel(executable_member=executable_member))
    if cleanup_failure:
        def fail_cleanup(_candidate: VerifiedWheelCandidate) -> None:
            raise OSError("injected quarantine removal failure")

        monkeypatch.setattr(VerifiedWheelCandidate, "cleanup", fail_cleanup)
    admit_coding_external_data_wheel(lifecycle, source=source)
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        binding = next(
            item for item in product.policy.bindings if item.plugin_id == "reviewpack"
        )
        factory = product.factory_for_session(
            session_id="external-skill", cwd=workspace, runtime_id="external-skill"
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="external-skill", cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            outcome = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id="external-skill-install",
                    action="install",
                    source=binding.source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
        finally:
            runtime.dispose_runtime()
        assert outcome.handled and outcome.record is not None
        assert outcome.record.lifecycle == (
            "failed" if executable_member else "installed"
        )
        if executable_member:
            assert outcome.evidence is not None
            assert outcome.evidence.failure_code == "package_plugin_contribution_rejected"
        if cleanup_failure:
            cleanup = PackageQuarantineCleanupJournal(
                product.state_root / "cleanup.jsonl"
            )
            assert any(
                item.status.rejection_code == "package_plugin_contribution_rejected"
                and item.status.disposition == "cleanup_retryable"
                for item in cleanup.records()
            )
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id="reviewpack",
        )
        assert product.desired_state.snapshot().installation(key).selection.desired_state == (
            "absent" if executable_member else "installed_disabled"
        )
    finally:
        owner.close()

    if not executable_member:
        binding = build_coding_plugin_management_cli_read_binding(workspace, settings)
        assert binding.fresh_product
        listing = list_plugin_records(binding)
        record = next(item for item in listing if item["name"] == "reviewpack")
        assert record["desiredState"] == "installed_disabled"
        command = build_coding_plugin_management_cli_binding(workspace, settings)
        apply_resource_toggles(
            None,
            ResourceToggleRequest(enable_plugins=("reviewpack",)),
            plugin_management=command,
        )
        record = next(
            item for item in list_plugin_records(binding) if item["name"] == "reviewpack"
        )
        assert record["desiredState"] == "installed_enabled"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_wheel_installs_through_real_coding_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="d" * 64,
        runtime_version="0.1.0",
        runtime_protocol_epoch=2,
    )
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    source.write_bytes(_data_wheel())
    stdout = StringIO()
    stderr = StringIO()
    result = asyncio.run(
        run_cli(
            ["--install-package", str(source), "--package-scope", "project"],
            cwd=workspace,
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
        )
    )
    assert result == 0, stderr.getvalue()
    listing = list_plugin_records(
        build_coding_plugin_management_cli_read_binding(workspace, settings)
    )
    assert next(item for item in listing if item["name"] == "reviewpack")[
        "desiredState"
    ] == "installed_disabled"
    enabled_output = StringIO()
    assert asyncio.run(
        run_cli(
            ["--enable-plugin", "reviewpack"],
            cwd=workspace,
            stdin=StringIO(),
            stdout=enabled_output,
            stderr=stderr,
        )
    ) == 0, stderr.getvalue()
    listed_output = StringIO()
    assert asyncio.run(
        run_cli(
            ["--list-plugins", "--list-plugins-format", "json"],
            cwd=workspace,
            stdin=StringIO(),
            stdout=listed_output,
            stderr=stderr,
        )
    ) == 0, stderr.getvalue()
    listed = json.loads(listed_output.getvalue())
    assert next(item for item in listed if item["name"] == "reviewpack")[
        "desiredState"
    ] == "installed_enabled"
    update_source = tmp_path / "reviewpack-2-py3-none-any.whl"
    update_source.write_bytes(_data_wheel(version="2"))
    assert asyncio.run(
        run_cli(
            ["--update-package", str(update_source), "--package-scope", "project"],
            cwd=workspace,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
        )
    ) == 0, stderr.getvalue()
    listed = list_plugin_records(
        build_coding_plugin_management_cli_read_binding(workspace, settings)
    )
    current = next(item for item in listed if item["name"] == "reviewpack")
    assert (current["version"], current["desiredState"]) == (
        "2", "installed_enabled"
    )
    assert current["management"]["retirementStates"]
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version="0.1.0",
        runtime_protocol_epoch=2,
    )
    try:
        factory = owner.runtime_owner.product_owner.factory_for_session(
            session_id="updated-skill", cwd=workspace, runtime_id="updated-skill"
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id="updated-skill", cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            selected = runtime.capture_selected_plugin_manifest_for(
                "reviewpack", max_files=16, max_total_bytes=2 * 1024 * 1024
            )
            assert selected.manifest.version == "2"
            assert len(selected.verified_data_only_declarations()) == 1
        finally:
            runtime.dispose_runtime()
    finally:
        owner.close()
    assert asyncio.run(
        run_cli(
            ["--disable-plugin", "reviewpack"],
            cwd=workspace,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
        )
    ) == 0, stderr.getvalue()
    assert asyncio.run(
        run_cli(
            ["--uninstall-package", "reviewpack", "--package-scope", "project"],
            cwd=workspace,
            stdin=StringIO(),
            stdout=StringIO(),
            stderr=stderr,
        )
    ) == 0, stderr.getvalue()
    listing = list_plugin_records(
        build_coding_plugin_management_cli_read_binding(workspace, settings)
    )
    assert next(item for item in listing if item["name"] == "reviewpack")[
        "desiredState"
    ] == "absent"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_data_skill_enters_fenced_session_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout,
        settings,
        workspace=workspace,
        namespace_id="e" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    source = tmp_path / "reviewpack-1-py3-none-any.whl"
    source.write_bytes(_data_wheel())
    for args in (
        ("--install-package", str(source), "--package-scope", "project"),
        ("--enable-plugin", "reviewpack"),
    ):
        stderr = StringIO()
        assert asyncio.run(
            run_cli(
                list(args), cwd=workspace, stdin=StringIO(),
                stdout=StringIO(), stderr=stderr,
            )
        ) == 0, stderr.getvalue()
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    services = create_services(settings_manager=settings)
    session = create_agent_session(
        session_manager=manager,
        model=Model(
            id="external-skill-model", name="External Skill Model",
            provider="test", endpoint="anthropic-messages",
            capabilities=Capabilities(
                reasoning=True, input=("text",), context_window=128000,
                max_tokens=4096,
            ),
        ),
        services=services,
        composition_set="coding-standard",
    )
    try:
        assert session.resource_bundle is not None
        review = next(
            item for item in session.resource_bundle.skills if item.name == "review"
        )
        assert review.source_kind == "external_package"
        inputs = session._capability_composition_inputs
        assert inputs is not None
        assert "reviewpack" in {
            item.plugin_id for item in inputs.product_composition.resource_admissions
        }
        async def inspect_skill() -> None:
            await session.prepare_model_call_runtime()
            preflight = await session._preflight_user_input_async("/skill:review")
            assert "# Review v1" in preflight.text
            [loaded] = preflight.loaded_skills
            assert loaded.summary.source_kind == "external_package"
            assert loaded.receipt.content_digest == (
                loaded.summary.expected_content_digest
            )

        asyncio.run(inspect_skill())
        old_revision = review.revision_ref
        update_source = tmp_path / "reviewpack-2-py3-none-any.whl"
        update_source.write_bytes(_data_wheel(version="2"))
        stderr = StringIO()
        assert asyncio.run(
            run_cli(
                ["--update-package", str(update_source), "--package-scope", "project"],
                cwd=workspace, stdin=StringIO(), stdout=StringIO(), stderr=stderr,
            )
        ) == 0, stderr.getvalue()
        assert review.revision_ref == old_revision
        next_manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "next-sessions",
                cwd=str(workspace), persist=False,
            )
        )
        next_session = create_agent_session(
            session_manager=next_manager,
            model=Model(
                id="external-skill-model", name="External Skill Model",
                provider="test", endpoint="anthropic-messages",
                capabilities=Capabilities(
                    reasoning=True, input=("text",), context_window=128000,
                    max_tokens=4096,
                ),
            ),
            services=services,
            composition_set="coding-standard",
        )
        try:
            assert next_session.resource_bundle is not None
            next_review = next(
                item for item in next_session.resource_bundle.skills
                if item.name == "review"
            )
            assert next_review.revision_ref != old_revision

            async def inspect_updated_skill() -> None:
                await next_session.prepare_model_call_runtime()
                preflight = await next_session._preflight_user_input_async(
                    "/skill:review"
                )
                assert "# Review v2" in preflight.text

            asyncio.run(inspect_updated_skill())
        finally:
            asyncio.run(next_session.dispose())
        resource_only_manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "resource-only-sessions",
                cwd=str(workspace), persist=False,
            )
        )
        resource_only = create_agent_session(
            session_manager=resource_only_manager,
            model=Model(
                id="external-skill-model", name="External Skill Model",
                provider="test", endpoint="anthropic-messages",
                capabilities=Capabilities(
                    reasoning=True, input=("text",), context_window=128000,
                    max_tokens=4096,
                ),
            ),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(
                        capabilities={"coding.lsp": "disabled", "coding.arch": "disabled"}
                    )
                )
            ),
            composition_set="coding-standard",
        )
        try:
            assert any(
                item.name == "review" and item.source_kind == "external_package"
                for item in resource_only.resource_bundle.skills
            )
        finally:
            asyncio.run(resource_only.dispose())
    finally:
        asyncio.run(session.dispose())


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_cached_application_selection_refreshes_external_source_for_new_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout, settings, workspace=workspace, namespace_id="6" * 64,
        runtime_version=version("loushang"), runtime_protocol_epoch=2,
    )
    first_source = tmp_path / "reviewpack-1-py3-none-any.whl"
    first_source.write_bytes(_data_wheel())
    for args in (
        ("--install-package", str(first_source), "--package-scope", "project"),
        ("--enable-plugin", "reviewpack"),
    ):
        stderr = StringIO()
        assert asyncio.run(run_cli(
            list(args), cwd=workspace, stdin=StringIO(),
            stdout=StringIO(), stderr=stderr,
        )) == 0, stderr.getvalue()
    selection = CodingFencedProductApplicationSelection()
    first_manager = asyncio.run(SessionManager.new(
        session_dir=tmp_path / "first-sessions", cwd=str(workspace), persist=False
    ))
    first_factory = selection.factory_for_session(first_manager)
    assert first_factory is not None
    first_runtime = first_factory.create(PackageProductRuntimeRequestV1(
        product_id="coding", session_id=first_manager.get_header().conversation_id,
        cwd=str(workspace),
    ))
    try:
        first_runtime.activate()
        assert first_runtime.selected_external_data_plugin_ids() == ("reviewpack",)
        second_source = tmp_path / "reviewpack-2-py3-none-any.whl"
        second_source.write_bytes(_data_wheel(version="2"))
        stderr = StringIO()
        assert asyncio.run(run_cli(
            ["--update-package", str(second_source), "--package-scope", "project"],
            cwd=workspace, stdin=StringIO(), stdout=StringIO(), stderr=stderr,
        )) == 0, stderr.getvalue()
        second_manager = asyncio.run(SessionManager.new(
            session_dir=tmp_path / "second-sessions", cwd=str(workspace),
            persist=False,
        ))
        second_factory = selection.factory_for_session(second_manager)
        assert second_factory is not None
        second_runtime = second_factory.create(PackageProductRuntimeRequestV1(
            product_id="coding", session_id=second_manager.get_header().conversation_id,
            cwd=str(workspace),
        ))
        try:
            second_runtime.activate()
            assert second_runtime.selected_external_data_plugin_ids() == ("reviewpack",)
            selected = second_runtime.capture_selected_plugin_manifest_for(
                "reviewpack", max_files=16, max_total_bytes=1024 * 1024,
            )
            assert selected.manifest.version == "2"
        finally:
            second_runtime.dispose_runtime()
    finally:
        first_runtime.dispose_runtime()
        selection.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_fenced_cli_refuses_external_executable_and_invalid_wheels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout, settings, workspace=workspace, namespace_id="f" * 64,
        runtime_version=version("loushang"), runtime_protocol_epoch=2,
    )
    failed_operations: list[tuple[str, str]] = []
    for version_id, body, code in (
        ("3", _data_wheel(version="3", executable_member=True),
         "package_plugin_contribution_rejected"),
        ("4", _data_wheel(version="4", actions_member=True),
         "package_plugin_contribution_rejected"),
        ("5", _data_wheel(version="5", requires_dist=True),
         "package_closure_conflict"),
        ("6", b"not a wheel", "package_archive_malformed"),
        ("8", _data_wheel(version="8", manifest_bytes=b"[" * 1500 + b"0" + b"]" * 1500),
         "package_plugin_contribution_rejected"),
        ("9", _data_wheel(version="9", managed_actions_reservation=True),
         "package_plugin_contribution_rejected"),
        ("10", _data_wheel(version="10", skill_size=1024 * 1024 - 1),
         "package_plugin_contribution_rejected"),
    ):
        source = tmp_path / f"reviewpack-{version_id}-py3-none-any.whl"
        source.write_bytes(body)
        stderr = StringIO()
        assert asyncio.run(
            run_cli(
                ["--install-package", str(source), "--package-scope", "project"],
                cwd=workspace, stdin=StringIO(), stdout=StringIO(), stderr=stderr,
            )
        ) == 1
        assert code in stderr.getvalue(), (version_id, stderr.getvalue())
        operation_id = stderr.getvalue().split("(Package operation: ", 1)[1].split(")", 1)[0]
        failed_operations.append((operation_id, code))
    target = tmp_path / "reviewpack-real.whl"
    target.write_bytes(_data_wheel(version="7"))
    symlink = tmp_path / "reviewpack-7-py3-none-any.whl"
    symlink.symlink_to(target)
    stderr = StringIO()
    assert asyncio.run(
        run_cli(
            ["--install-package", str(symlink), "--package-scope", "project"],
            cwd=workspace, stdin=StringIO(), stdout=StringIO(), stderr=stderr,
        )
    ) == 1
    assert "Source changed" in stderr.getvalue()
    key = PluginInstallationKeyV1(
        product_id="coding", installation_scope="workspace",
        scope_id=layout.scope_id, plugin_id="reviewpack",
    )
    owner = open_coding_fenced_product_application_owner(
        layout, workspace=workspace, runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        assert product.desired_state.snapshot().installation(
            key
        ).selection.desired_state == "absent"
        lifecycle = PackageLifecycleJournal(product.state_root / "lifecycle.jsonl")
        for operation_id, code in failed_operations:
            status = lifecycle.status(operation_id)
            assert status is not None and status.failure is not None
            assert status.failure.code == code
        management_ids = {
            item.command.mutation.operation_id
            for item in product.management.operations()
            if isinstance(item, PluginManagementOperationEventV1)
        }
        assert not management_ids.intersection(
            operation_id for operation_id, _ in failed_operations
        )
    finally:
        owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_fenced_cli_list_preserves_pending_management_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout, settings, workspace=workspace, namespace_id="1" * 64,
        runtime_version=version("loushang"), runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        layout, workspace=workspace, runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        snapshot = product.desired_state.snapshot()
        installation = next(
            item for item in snapshot.installations
            if item.installation_key.plugin_id == "coding.base"
        )
        operation = PluginManagementOperationEventV1.accepted(
            journal_revision=len(
                product.management.operation_journal_path.read_bytes().splitlines()
            ) + 1,
            command=PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="test:pending-b-disable",
                    idempotency_key="test:pending-b-disable",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=installation.installation_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator", policy_revision="test",
                ),
            ),
        )
        path = product.management.operation_journal_path
        path.write_bytes(
            path.read_bytes()
            + (json.dumps(operation.to_dict(), sort_keys=True) + "\n").encode()
        )
        before_operations = path.read_bytes()
        before_desired = product.desired_state.path.read_bytes()
    finally:
        owner.close()
    stdout = StringIO()
    stderr = StringIO()
    assert asyncio.run(
        run_cli(
            ["--list-plugins", "--list-plugins-format", "json"],
            cwd=workspace, stdin=StringIO(), stdout=stdout, stderr=stderr,
        )
    ) == 0, stderr.getvalue()
    assert path.read_bytes() == before_operations
    assert product.desired_state.path.read_bytes() == before_desired
    [base] = [
        item for item in json.loads(stdout.getvalue())
        if item["name"] == "coding.base"
    ]
    assert any(
        item["status"] == "accepted"
        for item in base["management"]["operations"]
    )
    path.write_bytes(path.read_bytes() + b'{"partial":')
    before_operations = path.read_bytes()
    before_desired = product.desired_state.path.read_bytes()
    stderr = StringIO()
    assert asyncio.run(
        run_cli(
            ["--list-plugins", "--list-plugins-format", "json"],
            cwd=workspace, stdin=StringIO(), stdout=StringIO(), stderr=stderr,
        )
    ) == 1
    assert path.read_bytes() == before_operations
    assert product.desired_state.path.read_bytes() == before_desired


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_external_update_recovers_interrupted_retention_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout, settings, workspace=workspace, namespace_id="2" * 64,
        runtime_version=version("loushang"), runtime_protocol_epoch=2,
    )
    initial = tmp_path / "reviewpack-1-py3-none-any.whl"
    initial.write_bytes(_data_wheel())
    for args in (
        ("--install-package", str(initial), "--package-scope", "project"),
        ("--enable-plugin", "reviewpack"),
    ):
        stderr = StringIO()
        assert asyncio.run(
            run_cli(
                list(args), cwd=workspace, stdin=StringIO(),
                stdout=StringIO(), stderr=stderr,
            )
        ) == 0, stderr.getvalue()
    replacement = tmp_path / "reviewpack-2-py3-none-any.whl"
    replacement.write_bytes(_data_wheel(version="2"))
    captured = admit_coding_external_data_wheel(layout, source=replacement)
    operation_id = "test:interrupted-external-update"
    original_settle = PackageProductRetentionSettlementOwner.settle
    interrupted = False

    def interrupt_once(owner, receipt, *, desired_receipt):  # type: ignore[no-untyped-def]
        nonlocal interrupted
        if receipt.request.operation_id == operation_id and not interrupted:
            interrupted = True
            raise OSError("injected retention settlement interruption")
        return original_settle(owner, receipt, desired_receipt=desired_receipt)

    owner = open_coding_fenced_product_application_owner(
        layout, workspace=workspace, runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        runtime_id = "interrupted-update-runtime"
        factory = product.factory_for_session(
            session_id=runtime_id, cwd=workspace, runtime_id=runtime_id
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=runtime_id, cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            monkeypatch.setattr(
                PackageProductRetentionSettlementOwner, "settle", interrupt_once
            )
            with pytest.raises(RuntimeError, match="handoff"):
                runtime.lifecycle.route(
                    PackageProductLifecycleIntentV1(
                        operation_id=operation_id, action="update",
                        source=str(
                            owner.epoch_runtime.control_root
                            / "product-sources" / captured.wheel_filename
                        ),
                        scope="project",
                    ),
                    entrypoint="cli",
                )
            handoff = PackageRetentionHandoffJournal(
                product.state_root / "handoff.jsonl"
            )
            matching = [
                item.receipt for item in handoff.records()
                if item.receipt is not None
                and item.receipt.request.operation_id == operation_id
            ]
            assert matching[-1].state == "desired_committed"
        finally:
            runtime.dispose_runtime()
    finally:
        owner.close()
    monkeypatch.setattr(
        PackageProductRetentionSettlementOwner, "settle", original_settle
    )
    reopened = open_coding_fenced_product_application_owner(
        layout, workspace=workspace, runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = reopened.runtime_owner.product_owner
        runtime_id = "recovered-update-runtime"
        factory = product.factory_for_session(
            session_id=runtime_id, cwd=workspace, runtime_id=runtime_id
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=runtime_id, cwd=str(workspace)
            )
        )
        try:
            runtime.activate()
            selected = runtime.capture_selected_plugin_manifest_for(
                "reviewpack", max_files=16, max_total_bytes=1024 * 1024
            )
            assert selected.manifest.version == "2"
        finally:
            runtime.dispose_runtime()
        handoff = PackageRetentionHandoffJournal(product.state_root / "handoff.jsonl")
        matching = [
            item.receipt for item in handoff.records()
            if item.receipt is not None
            and item.receipt.request.operation_id == operation_id
        ]
        assert matching[-1].state == "settled"
    finally:
        reopened.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_stale_interrupted_update_cannot_replace_newer_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        layout, settings, workspace=workspace, namespace_id="7" * 64,
        runtime_version=version("loushang"), runtime_protocol_epoch=2,
    )
    sources = {}
    for release in ("1", "2", "3"):
        source = tmp_path / f"reviewpack-{release}-py3-none-any.whl"
        source.write_bytes(_data_wheel(version=release))
        sources[release] = admit_coding_external_data_wheel(layout, source=source)
    owner = open_coding_fenced_product_application_owner(
        layout, workspace=workspace, runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    product = owner.runtime_owner.product_owner

    def activate(name: str):  # type: ignore[no-untyped-def]
        factory = product.factory_for_session(
            session_id=name, cwd=workspace, runtime_id=name
        )
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=name, cwd=str(workspace)
            )
        )
        runtime.activate()
        return runtime

    def route(runtime, release: str, action: str) -> None:  # type: ignore[no-untyped-def]
        outcome = runtime.lifecycle.route(
            PackageProductLifecycleIntentV1(
                operation_id=f"test:reviewpack-{release}",
                action=action,
                source=str(
                    owner.epoch_runtime.control_root / "product-sources"
                    / sources[release].wheel_filename
                ),
                scope="project",
            ),
            entrypoint="cli",
        )
        assert outcome.record is not None
        assert outcome.record.lifecycle in {"installed", "updated"}

    first = activate("stale-update-first")
    try:
        route(first, "1", "install")
        second = activate("stale-update-second")
        try:
            original_finalize = PackageProductHandoffFinalizer.finalize

            def interrupt(owner, request, *, current):  # type: ignore[no-untyped-def]
                if current.operation_id == "test:reviewpack-2":
                    raise OSError("injected interruption before first handoff")
                return original_finalize(owner, request, current=current)

            with monkeypatch.context() as patch:
                patch.setattr(PackageProductHandoffFinalizer, "finalize", interrupt)
                with pytest.raises(OSError, match="injected interruption"):
                    route(first, "2", "update")
            anchor = product.gc_bindings.update_anchor("test:reviewpack-2")
            assert anchor is not None
            assert anchor.expected_package_revision.plugin_version == "1"
            route(second, "3", "update")
            selected = product.desired_state.snapshot().installation(
                PluginInstallationKeyV1(
                    product_id="coding", installation_scope="workspace",
                    scope_id=layout.scope_id, plugin_id="reviewpack",
                )
            )
            assert selected.selection.package_revision.plugin_version == "3"
            with suppress(RuntimeError):
                first.activate()
            selected_after = product.desired_state.snapshot().installation(
                selected.installation_key
            )
            assert selected_after.selection.package_revision.plugin_version == "3"
            third = activate("stale-update-third")
            try:
                assert product.desired_state.snapshot().installation(
                    selected.installation_key
                ).selection.package_revision.plugin_version == "3"
            finally:
                third.dispose_runtime()
        finally:
            second.dispose_runtime()
    finally:
        first.dispose_runtime()
        owner.close()
