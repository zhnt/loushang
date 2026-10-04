from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.provider.protocol import APIAdapter, ProviderRequest
from loushang.coding import package_legacy_local_acceptance as local_acceptance_module
from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.cli.package_cutover import main as cutover_main
from loushang.coding.package_legacy_binding_catalog import (
    CodingLegacyBindingError,
    CodingLegacyLocalBindingCatalog,
)
from loushang.coding.package_legacy_desired_evidence import (
    CodingLegacyDesiredError,
    CodingLegacyDesiredEvidenceV1,
    parse_coding_legacy_desired_evidence,
)
from loushang.coding.package_legacy_installation_inventory import (
    CodingLegacyBuiltinIntentV1,
    CodingLegacyInventoryError,
    classify_coding_legacy_installations,
    classify_coding_legacy_removed_local_installations,
    read_coding_legacy_installation_inventory,
)
from loushang.coding.package_legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceError,
    CodingLegacyLocalAcceptanceV1,
    accept_coding_legacy_installed_local_review,
    read_coding_legacy_installed_local_acceptance,
    reopen_coding_legacy_installed_local_acceptance,
)
from loushang.coding.package_legacy_local_adoption import (
    adopt_coding_legacy_local_skill_review,
)
from loushang.coding.package_legacy_local_binding_owner import (
    bind_coding_accepted_legacy_local_source,
)
from loushang.coding.package_legacy_local_installation import (
    CodingLegacyLocalInstallationError,
    enable_coding_accepted_legacy_local_data_plugin,
    enable_coding_accepted_legacy_local_skill,
    install_coding_accepted_legacy_local_plugin,
)
from loushang.coding.package_legacy_local_wheel import (
    reacquire_coding_legacy_local_plugin_wheel,
)
from loushang.coding.package_legacy_lock_evidence import (
    parse_coding_legacy_local_binding_heads,
)
from loushang.coding.package_legacy_reacquisition import (
    reacquire_coding_legacy_installed_local_source,
)
from loushang.coding.package_legacy_review import (
    CodingLegacyLocalAdoptionReviewV1,
    review_coding_legacy_installed_local_source,
)
from loushang.coding.package_legacy_skill_cutover_admission import (
    admit_coding_single_legacy_skill_snapshot,
    inspect_coding_legacy_local_data_wheel,
    require_coding_fenced_single_legacy_data,
)
from loushang.coding.package_legacy_snapshot_member import (
    CodingFirstBLegacyStateObserver,
    CodingLegacySnapshotError,
)
from loushang.coding.package_pre_b_snapshot import (
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
)
from loushang.coding.package_product_preview import (
    CodingFencedProductReadOnlyPreviewOwner,
)
from loushang.coding.package_product_runtime import (
    CodingFencedProductApplicationSelection,
    _bootstrap_coding_builtin_plugin,
    admit_coding_external_data_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackagePosixEpochCutoverError,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_pre_b_snapshot import (
    read_posix_product_pre_b_snapshot,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.transcript.model_input_types import ModelInputSnapshot
from loushang.harness.transcript.model_input_v2_types import ModelInputSnapshotV2
from loushang.plugin import build_coding_data_skill_wheel, package, resource

_SCOPE = "workspace:" + "a" * 64


@pytest.mark.skipif(os.name != "posix", reason="POSIX legacy Source reacquisition")
@pytest.mark.parametrize(
    ("resource_kind", "expected_name"),
    (("skill", "review"), ("prompt", "review.md")),
)
def test_legacy_local_data_wheel_inspection_is_type_specific(
    tmp_path: Path, resource_kind: str, expected_name: str
) -> None:
    binding = _real_binding(tmp_path, prompt_resource=resource_kind == "prompt")
    staging = tmp_path / "private-staging"
    staging.mkdir(mode=0o700)
    wheel = reacquire_coding_legacy_local_plugin_wheel(
        tmp_path / "source",
        legacy_package_root=tmp_path / "old-package",
        staging_parent=staging,
        plugin_id=binding.plugin_id,
        expected_source_identity=binding.source_identity,
        expected_content_digest=binding.content_digest,
        expected_manifest_digest=binding.manifest_digest,
        expected_dependency_lock=binding.dependency_lock,
    )

    inspected = inspect_coding_legacy_local_data_wheel(wheel)
    assert (inspected.resource_kind, inspected.canonical_name) == (
        resource_kind,
        expected_name,
    )
    with pytest.raises(ValueError, match="digest"):
        inspect_coding_legacy_local_data_wheel(replace(wheel, artifact_digest="0" * 64))


@pytest.mark.skipif(os.name != "posix", reason="POSIX legacy Source reacquisition")
def test_legacy_local_data_wheel_inspection_accepts_bounded_theme(
    tmp_path: Path,
) -> None:
    binding = _real_binding(tmp_path, theme_resource=True)
    staging = tmp_path / "private-staging"
    staging.mkdir(mode=0o700)
    wheel = reacquire_coding_legacy_local_plugin_wheel(
        tmp_path / "source",
        legacy_package_root=tmp_path / "old-package",
        staging_parent=staging,
        plugin_id=binding.plugin_id,
        expected_source_identity=binding.source_identity,
        expected_content_digest=binding.content_digest,
        expected_manifest_digest=binding.manifest_digest,
        expected_dependency_lock=binding.dependency_lock,
    )

    inspected = inspect_coding_legacy_local_data_wheel(wheel)
    assert (inspected.resource_kind, inspected.canonical_name) == (
        "theme",
        "review.json",
    )
    with pytest.raises(ValueError, match="digest"):
        inspect_coding_legacy_local_data_wheel(replace(wheel, artifact_digest="0" * 64))


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
def test_prompt_acceptance_binds_type_and_reopens_without_original_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    binding = _real_binding(tmp_path, prompt_resource=True)
    (lifecycle.package_root / "package-lock.json").write_bytes(
        (tmp_path / "old-package" / "package-lock.json").read_bytes()
    )
    revision = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    _desired(
        tmp_path / "old-intent",
        revision,
        final_state="installed_enabled",
        scope_id=lifecycle.scope_id,
    )
    lifecycle.desired_state.write_bytes(
        (tmp_path / "old-intent" / "old-desired.jsonl").read_bytes()
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    monkeypatch.setattr(
        "loushang.coding.cli.package_cutover.resolve_coding_plugin_lifecycle_state_layout",
        lambda _workspace: lifecycle,
    )
    monkeypatch.setattr(
        "loushang.coding.cli.package_cutover.version", lambda _package: "2.0.0"
    )
    monkeypatch.setattr(
        "loushang.coding.cli.package_cutover.default_global_settings_path",
        lambda: tmp_path / "global-settings.json",
    )
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--prepare-legacy-local-prompt-review",
                binding.plugin_id,
            )
        )
        == 0
    ), capsys.readouterr().err
    prepared_review = json.loads(capsys.readouterr().out)
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        with pytest.raises(ValueError, match="Resource type changed"):
            require_coding_fenced_single_legacy_data(
                lifecycle, owner, plugin_id=binding.plugin_id, resource_kind="skill"
            )
        require_coding_fenced_single_legacy_data(
            lifecycle, owner, plugin_id=binding.plugin_id, resource_kind="prompt"
        )
        review = review_coding_legacy_installed_local_source(
            lifecycle,
            owner,
            plugin_id=binding.plugin_id,
            policy_revision="coding-product-package-policy:1",
        )
        assert prepared_review["reviewId"] == review.review_id
        with pytest.raises(CodingLegacyLocalAcceptanceError, match="Resource type"):
            accept_coding_legacy_installed_local_review(
                lifecycle,
                owner,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:1",
                accepted_review_id=review.review_id,
            )
        receipt = accept_coding_legacy_installed_local_review(
            lifecycle,
            owner,
            plugin_id=binding.plugin_id,
            policy_revision="coding-product-package-policy:1",
            accepted_review_id=review.review_id,
            resource_kind="prompt",
        )
        assert receipt.acceptance_version == 2
        assert receipt.resource_kind == "prompt"
        assert CodingLegacyLocalAcceptanceV1.from_dict(receipt.to_dict()) == receipt
        with pytest.raises(CodingLegacyLocalAcceptanceError, match="conflicts"):
            accept_coding_legacy_installed_local_review(
                lifecycle,
                owner,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:1",
                accepted_review_id=review.review_id,
            )
        bound = bind_coding_accepted_legacy_local_source(
            lifecycle,
            owner,
            plugin_id=binding.plugin_id,
            policy_revision="coding-product-package-policy:1",
        )
        assert bound.record_version == 2
        assert bound.resource_kind == "prompt"
        assert bound.approval_id == receipt.acceptance_id
    finally:
        owner.close()
    with pytest.raises(ValueError, match="matching Resource receipt"):
        adopt_coding_legacy_local_skill_review(
            lifecycle,
            workspace=workspace,
            plugin_id=binding.plugin_id,
            accepted_review_id=receipt.review.review_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
    shutil.rmtree(tmp_path / "source")
    reopened = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
        read_only=True,
    )
    try:
        assert (
            reopen_coding_legacy_installed_local_acceptance(
                lifecycle,
                reopened,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:1",
            )
            == receipt
        )
        catalog = CodingLegacyLocalBindingCatalog(
            reopened.control_root / "product-state" / "legacy-local-bindings.jsonl",
            source_root=reopened.control_root / "product-sources",
            store_id=bound.store_id,
            namespace_id=bound.namespace_id,
            scope_id=bound.scope_id,
            policy_revision=bound.policy_revision,
            acceptance_reader=lambda _plugin_id: receipt,
        )
        assert catalog.read_records() == (bound,)
        assert bound.to_policy_binding(catalog.source_root).source_trust_class == (
            "legacy-local-reacquired-prompt"
        )
    finally:
        reopened.close()
    monkeypatch.setattr(
        "loushang.coding.package_legacy_local_adoption.default_global_settings_path",
        lambda: tmp_path / "global-settings.json",
    )
    monkeypatch.setattr(
        "loushang.coding.package_legacy_local_adoption_read.default_global_settings_path",
        lambda: tmp_path / "global-settings.json",
    )
    assert (
        cutover_main(
            (
                "--workspace",
                str(workspace),
                "--adopt-legacy-local-prompt-review",
                binding.plugin_id,
                receipt.review.review_id,
            )
        )
        == 0
    ), capsys.readouterr().err
    assert json.loads(capsys.readouterr().out)["acceptanceId"] == receipt.acceptance_id
    assert cutover_main(("--workspace", str(workspace))) == 0, capsys.readouterr().err
    assert json.loads(capsys.readouterr().out)["disposition"] == "fenced"
    installed = install_coding_accepted_legacy_local_plugin(
        lifecycle,
        workspace=workspace,
        plugin_id=binding.plugin_id,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    assert installed.acceptance_id == receipt.acceptance_id
    assert installed.package_revision.package_content_digest == bound.artifact_digest
    with pytest.raises(
        CodingLegacyLocalInstallationError, match="accepted enabled selection"
    ):
        enable_coding_accepted_legacy_local_skill(
            lifecycle,
            workspace=workspace,
            plugin_id=binding.plugin_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
    enabled = enable_coding_accepted_legacy_local_data_plugin(
        lifecycle,
        workspace=workspace,
        plugin_id=binding.plugin_id,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        resource_kind="prompt",
    )
    assert enabled.package_revision == installed.package_revision
    assert (
        install_coding_accepted_legacy_local_plugin(
            lifecycle,
            workspace=workspace,
            plugin_id=binding.plugin_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        == installed
    )
    assert (
        enable_coding_accepted_legacy_local_data_plugin(
            lifecycle,
            workspace=workspace,
            plugin_id=binding.plugin_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
            resource_kind="prompt",
        )
        == enabled
    )
    product_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        product = product_owner.runtime_owner.product_owner
        factory = product.factory_for_session(
            session_id="legacy-prompt-selection",
            cwd=workspace,
            runtime_id="legacy-prompt-selection",
        )
        selected_runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="legacy-prompt-selection",
                cwd=str(workspace),
            )
        )
        try:
            selected_runtime.activate()
            assert selected_runtime.selected_external_data_plugin_ids() == (
                binding.plugin_id,
            )
            selected_manifest = selected_runtime.capture_selected_plugin_manifest_for(
                binding.plugin_id,
                max_files=64,
                max_total_bytes=1024 * 1024,
            )
            assert selected_manifest.source_trust_snapshot is not None
            assert (
                selected_manifest.source_trust_snapshot.source_trust_class
                == "legacy-local-reacquired-prompt"
            )
            assert selected_manifest.verified_data_only_declarations()[0][0].owner == (
                "resources.prompt"
            )
        finally:
            selected_runtime.dispose_runtime()
        _bootstrap_coding_builtin_plugin(product_owner, "coding.base", enable=False)
        for builtin_id in ("coding.lsp.default", "coding.arch.default"):
            _bootstrap_coding_builtin_plugin(product_owner, builtin_id, enable=True)

        class LegacyPromptAdapter:
            api = "legacy-prompt-product-test"

            def prepare_request(self, request: ProviderRequest) -> PreparedModelRequest:
                return PreparedModelRequest.from_provider_request(
                    request,
                    payload={
                        "system": request.context.system_prompt,
                        "messages": [
                            serialize_message(message)
                            for message in request.context.messages
                        ],
                        "model": request.model.id,
                    },
                )

            async def invoke_prepared_raw(
                self, request: ProviderRequest, prepared: PreparedModelRequest
            ) -> AsyncIterator[dict[str, object]]:
                del request
                prepared.payload_for_transport()
                yield {"type": "response_start", "response_id": "legacy-prompt"}
                yield {"type": "text_delta", "text": "reviewed"}
                yield {"type": "stop_reason", "stop_reason": "stop"}
                yield {"type": "response_done"}

            async def invoke_raw(
                self, request: ProviderRequest
            ) -> AsyncIterator[dict[str, object]]:
                prepared = self.prepare_request(request)
                async for part in self.invoke_prepared_raw(request, prepared):
                    yield part

        registry = get_default_api_registry()
        registry.register_api_adapter(
            cast(APIAdapter, LegacyPromptAdapter()),
            source_id=LegacyPromptAdapter.api,
        )
        manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "legacy-prompt-session",
                cwd=str(workspace),
                persist=True,
            )
        )
        model = Model(
            id="legacy-prompt-model",
            name="Legacy Prompt Model",
            provider="test",
            endpoint="legacy-prompt-product-test",
            api=LegacyPromptAdapter.api,
            base_url="https://provider.test/v1",
            auth=Auth(kind="none"),
            capabilities=Capabilities(
                input=("text",),
                output=("text",),
                context_window=128000,
                stream=True,
                tool_use=True,
            ),
        )
        session = create_agent_session(
            session_manager=manager,
            model=model,
            services=create_services(settings_manager=settings),
            composition_set="coding-standard",
            package_product_runtime_factory=product_owner.factory_for_session(manager),
        )
        try:
            assert session.resource_bundle is not None
            assert any(
                item.name == "review" and item.source_kind == "external_package"
                for item in session.resource_bundle.prompts
            )
            asyncio.run(session.prompt("/review Review this change"))
            snapshots = [
                entry.payload
                for entry in manager.get_entries()
                if entry.kind == "model.input.prepared"
            ]
            assert len(snapshots) == 1
            assert isinstance(snapshots[0], (ModelInputSnapshot, ModelInputSnapshotV2))
            snapshot_id = snapshots[0].snapshot_id
            assert "Check the change" in json.dumps(
                manager.rebuild_model_input(snapshot_id).logical_input,
                ensure_ascii=False,
            )
        finally:
            asyncio.run(session.dispose())
            registry.unregister_api_adapters(LegacyPromptAdapter.api)
        session_file = manager.get_session_file()
        assert session_file is not None
        resumed = asyncio.run(SessionManager.load(session_file))
        assert "Check the change" in json.dumps(
            resumed.rebuild_model_input(snapshot_id).logical_input,
            ensure_ascii=False,
        )
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=binding.plugin_id,
        )
        disabled = product.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator-disabled-legacy-prompt",
                    idempotency_key="operator-disabled-legacy-prompt",
                    expected_inventory_revision=(
                        product.desired_state.snapshot().inventory_revision
                    ),
                    installation_key=key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision=product.desired_policy_revision,
                ),
            )
        )
        assert disabled.result is not None
        assert disabled.result.disposition == "succeeded"
        with pytest.raises(
            CodingLegacyLocalInstallationError,
            match="disablement was independently changed",
        ):
            enable_coding_accepted_legacy_local_data_plugin(
                lifecycle,
                workspace=workspace,
                plugin_id=binding.plugin_id,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
                resource_kind="prompt",
            )
        next_manager = asyncio.run(
            SessionManager.new(
                session_dir=tmp_path / "legacy-prompt-disabled-session",
                cwd=str(workspace),
                persist=False,
            )
        )
        next_session = create_agent_session(
            session_manager=next_manager,
            model=model,
            services=create_services(settings_manager=settings),
            composition_set="coding-standard",
            package_product_runtime_factory=product_owner.factory_for_session(
                next_manager
            ),
        )
        try:
            assert next_session.resource_bundle is not None
            assert not any(
                item.name == "review" and item.source_kind == "external_package"
                for item in next_session.resource_bundle.prompts
            )
        finally:
            asyncio.run(next_session.dispose())
    finally:
        product_owner.close()
    bound_source = epoch.control_root / "product-sources" / bound.wheel_filename
    bound_source.write_bytes(b"changed")
    with pytest.raises(CodingLegacyBindingError, match="changed on disk"):
        open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )


def _real_binding(
    tmp_path: Path,
    *,
    executable_member: bool = False,
    prompt_resource: bool = False,
    theme_resource: bool = False,
):
    source = tmp_path / "source"
    source.mkdir()
    compiled = package(
        id="review-pack",
        version="1",
        contributions=(
            resource.theme(contribution_id="review-theme", locator="themes/review.json")
            if theme_resource
            else resource.prompt(
                contribution_id="review-prompt", locator="prompts/review.md"
            )
            if prompt_resource
            else resource.skill(
                contribution_id="review-skill", locator="skills/review"
            ),
        ),
    )
    for artifact in compiled.artifacts:
        target = source / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    if theme_resource:
        theme = source / "themes" / "review.json"
        theme.parent.mkdir(parents=True)
        theme.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "tokens": {"markdown.heading": {"color": "blue"}},
                }
            )
        )
    elif prompt_resource:
        prompt = source / "prompts" / "review.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("# Review\nCheck the change.\n")
    else:
        skill = source / "skills" / "review" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: review\ndescription: review files\n---\n# Review\n"
        )
    if executable_member:
        (source / "entry.py").write_text("raise RuntimeError('must not execute')\n")
    old_package = tmp_path / "old-package"
    materializer = PackageMaterializer(install_root=old_package / "installed")
    published = materializer.publish_plugin_packages(
        (PluginManifestParser().parse(source),)
    )
    try:
        materializer.bind_plugin_packages(published)
    finally:
        published[0].revision_handle.close()
    [binding] = parse_coding_legacy_local_binding_heads(
        (old_package / "package-lock.json").read_bytes()
    )
    return binding


def _desired(
    tmp_path: Path,
    package: PluginPackageRevisionRefV1,
    *,
    final_state: str,
    scope_id: str = _SCOPE,
) -> CodingLegacyDesiredEvidenceV1:
    path = tmp_path / "old-desired.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=scope_id,
        plugin_id=package.plugin_id,
    )
    ledger = PluginDesiredStateLedger(path)
    ledger.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-install",
            idempotency_key="old-install",
            expected_inventory_revision=0,
            installation_key=key,
            desired_state="installed_disabled",
            package_revision=package,
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    if final_state != "installed_disabled":
        ledger.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-final-state",
                idempotency_key="old-final-state",
                expected_inventory_revision=1,
                installation_key=key,
                desired_state=final_state,  # type: ignore[arg-type]
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    snapshot, transitions = ledger.capture_read_only()
    return CodingLegacyDesiredEvidenceV1(
        snapshot=snapshot,
        journal_digest=sha256(path.read_bytes()).hexdigest(),
        transitions=transitions,
    )


@pytest.mark.parametrize("state", ["installed_disabled", "installed_enabled"])
def test_inventory_requires_exact_old_installed_head(
    tmp_path: Path, state: str
) -> None:
    binding = _real_binding(tmp_path)
    package = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    desired = _desired(tmp_path, package, final_state=state)
    inventory = classify_coding_legacy_installations(
        (binding,), desired, scope_id=_SCOPE
    )
    assert len(inventory.active_local) == 1
    assert inventory.active_local[0].desired_state == state
    assert inventory.active_local[0].binding == binding
    assert inventory.removed_plugin_ids == ()
    assert inventory.unselected_source_identities == ()

    changed = _desired(
        tmp_path / "changed",
        replace(package, package_content_digest="f" * 64),
        final_state="installed_disabled",
    )
    with pytest.raises(CodingLegacyInventoryError, match="differs"):
        classify_coding_legacy_installations((binding,), changed, scope_id=_SCOPE)


def test_inventory_keeps_removed_and_unselected_sources_out_of_adoption(
    tmp_path: Path,
) -> None:
    binding = _real_binding(tmp_path)
    package = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    missing = classify_coding_legacy_installations((binding,), None, scope_id=_SCOPE)
    assert missing.active_local == ()
    assert missing.unselected_source_identities == (binding.source_identity,)

    removed = classify_coding_legacy_installations(
        (binding,), _desired(tmp_path, package, final_state="absent"), scope_id=_SCOPE
    )
    assert removed.active_local == ()
    assert removed.removed_plugin_ids == (binding.plugin_id,)
    assert removed.unselected_source_identities == (binding.source_identity,)


def test_removed_local_history_must_match_lock_install_then_remove(
    tmp_path: Path,
) -> None:
    binding = _real_binding(tmp_path)
    package = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    desired = _desired(tmp_path / "removed", package, final_state="absent")
    [removed] = classify_coding_legacy_removed_local_installations(
        (binding,), desired, scope_id=_SCOPE
    )
    assert removed.binding == binding
    assert removed.install_operation_id == "old-install"
    assert removed.remove_operation_id == "old-final-state"

    with pytest.raises(CodingLegacyInventoryError, match="incomplete"):
        classify_coding_legacy_removed_local_installations(
            (binding,),
            replace(desired, transitions=desired.transitions[-1:]),
            scope_id=_SCOPE,
        )
    changed = _desired(
        tmp_path / "changed-removed",
        replace(package, package_content_digest="f" * 64),
        final_state="absent",
    )
    with pytest.raises(CodingLegacyInventoryError, match="does not match"):
        classify_coding_legacy_removed_local_installations(
            (binding,), changed, scope_id=_SCOPE
        )


def test_old_desired_capture_preserves_removed_local_history(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    binding = _real_binding(tmp_path)
    package = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    old_dir = tmp_path / "old-desired"
    expected = _desired(
        old_dir, package, final_state="absent", scope_id=lifecycle.scope_id
    )
    captured = parse_coding_legacy_desired_evidence(
        (old_dir / "old-desired.jsonl").read_bytes(), lifecycle=lifecycle
    )
    assert captured == expected
    [removed] = classify_coding_legacy_removed_local_installations(
        (binding,), captured, scope_id=lifecycle.scope_id
    )
    assert removed.binding == binding


def test_inventory_tracks_builtin_intent_without_local_binding(tmp_path: Path) -> None:
    package = PluginPackageRevisionRefV1(
        plugin_id="coding.base",
        plugin_version="1",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="embedded:coding.base",
    )
    inventory = classify_coding_legacy_installations(
        (),
        _desired(tmp_path, package, final_state="installed_disabled"),
        scope_id=_SCOPE,
    )
    assert inventory.active_local == ()
    assert [
        (item.plugin_id, item.desired_state) for item in inventory.builtin_intent
    ] == [("coding.base", "installed_disabled")]


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
def test_old_builtin_intent_is_reviewed_and_selected_after_local_adoption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    binding = _real_binding(tmp_path)
    (lifecycle.package_root / "package-lock.json").write_bytes(
        (tmp_path / "old-package" / "package-lock.json").read_bytes()
    )
    _desired(
        tmp_path / "old-intent",
        PluginPackageRevisionRefV1(
            plugin_id=binding.plugin_id,
            plugin_version="1",
            package_content_digest=binding.content_digest,
            dependency_lock_digest=binding.dependency_lock.digest,
            package_source_identity=binding.source_identity,
        ),
        final_state="installed_enabled",
        scope_id=lifecycle.scope_id,
    )
    old_desired_path = tmp_path / "old-intent" / "old-desired.jsonl"
    old_desired = PluginDesiredStateLedger(old_desired_path)
    old_desired.commit(
        PluginDesiredStateMutationV1(
            operation_id="old-builtin-install",
            idempotency_key="old-builtin-install",
            expected_inventory_revision=old_desired.snapshot().inventory_revision,
            installation_key=PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id="coding.arch.default",
            ),
            desired_state="installed_disabled",
            package_revision=PluginPackageRevisionRefV1(
                plugin_id="coding.arch.default",
                plugin_version="1",
                package_content_digest="1" * 64,
                dependency_lock_digest="2" * 64,
                package_source_identity="embedded:coding.arch.default",
            ),
            actor_id="old-operator",
            policy_revision="old-policy:1",
        )
    )
    lifecycle.desired_state.write_bytes(old_desired_path.read_bytes())
    settings_path = tmp_path / "global-settings.json"
    settings = SettingsManager(
        global_settings_path=settings_path,
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    monkeypatch.setattr(
        "loushang.coding.package_legacy_local_adoption.default_global_settings_path",
        lambda: settings_path,
    )
    prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="b" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
        snapshot_admission=lambda prepared, snapshot: (
            admit_coding_single_legacy_skill_snapshot(
                lifecycle, prepared, snapshot, plugin_id=binding.plugin_id
            )
        ),
    )
    read_owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
        read_only=True,
    )
    try:
        review = review_coding_legacy_installed_local_source(
            lifecycle,
            read_owner,
            plugin_id=binding.plugin_id,
            policy_revision="coding-product-package-policy:1",
        )
        assert review.to_dict()["builtinIntent"] == [
            {"pluginId": "coding.arch.default", "desiredState": "installed_disabled"}
        ]
        assert CodingLegacyLocalAdoptionReviewV1.from_dict(review.to_dict()) == review
        with pytest.raises(ValueError, match="identity changed"):
            CodingLegacyLocalAdoptionReviewV1.from_dict(
                {
                    **review.to_dict(),
                    "builtinIntent": [
                        {
                            "pluginId": "coding.arch.default",
                            "desiredState": "installed_enabled",
                        }
                    ],
                }
            )
    finally:
        read_owner.close()
    adopted = adopt_coding_legacy_local_skill_review(
        lifecycle,
        workspace=workspace,
        plugin_id=binding.plugin_id,
        accepted_review_id=review.review_id,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    assert adopted.acceptance.review.builtin_intent == review.builtin_intent
    product_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        desired = product_owner.runtime_owner.product_owner.desired_state.snapshot()
        for plugin_id, expected in (
            (binding.plugin_id, "installed_enabled"),
            ("coding.arch.default", "installed_disabled"),
            ("coding.base", "installed_enabled"),
        ):
            assert (
                desired.installation(
                    PluginInstallationKeyV1(
                        product_id="coding",
                        installation_scope="workspace",
                        scope_id=lifecycle.scope_id,
                        plugin_id=plugin_id,
                    )
                ).selection.desired_state
                == expected
            )
    finally:
        product_owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
@pytest.mark.parametrize(
    "case",
    (
        "skill",
        "builtin_disable",
        "builtin_intent",
        "base_remove",
        "foreign_remove",
        "foreign_disable",
        "executable",
        "prompt",
        "theme",
        "extra_old_journal",
        "prompt_selection_of_skill",
        "prompt_selection_of_theme",
        "prompt_selection_of_executable",
    ),
)
def test_old_local_skill_prefence_admission_and_refusals(
    tmp_path: Path, case: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    binding = _real_binding(
        tmp_path,
        executable_member=case in {"executable", "prompt_selection_of_executable"},
        prompt_resource=case == "prompt",
        theme_resource=case in {"theme", "prompt_selection_of_theme"},
    )
    lock_bytes = (tmp_path / "old-package" / "package-lock.json").read_bytes()
    (lifecycle.package_root / "package-lock.json").write_bytes(lock_bytes)
    package_revision = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    _desired(
        tmp_path / "old-intent",
        package_revision,
        final_state="installed_enabled",
        scope_id=lifecycle.scope_id,
    )
    old_desired_path = tmp_path / "old-intent" / "old-desired.jsonl"
    if case == "builtin_intent":
        old_desired = PluginDesiredStateLedger(old_desired_path)
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-builtin-install",
                idempotency_key="old-builtin-install",
                expected_inventory_revision=old_desired.snapshot().inventory_revision,
                installation_key=PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=lifecycle.scope_id,
                    plugin_id="coding.arch.default",
                ),
                desired_state="installed_disabled",
                package_revision=PluginPackageRevisionRefV1(
                    plugin_id="coding.arch.default",
                    plugin_version="1",
                    package_content_digest="1" * 64,
                    dependency_lock_digest="2" * 64,
                    package_source_identity="embedded:coding.arch.default",
                ),
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    if case in {"base_remove", "foreign_remove"}:
        old_desired = PluginDesiredStateLedger(old_desired_path)
        old_desired.commit(
            PluginDesiredStateMutationV1(
                operation_id="old-foreign-remove",
                idempotency_key="old-foreign-remove",
                expected_inventory_revision=old_desired.snapshot().inventory_revision,
                installation_key=PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=lifecycle.scope_id,
                    plugin_id=(
                        "coding.base" if case == "base_remove" else "foreign.plugin"
                    ),
                ),
                desired_state="absent",
                package_revision=None,
                actor_id="old-operator",
                policy_revision="old-policy:1",
            )
        )
    desired_bytes = old_desired_path.read_bytes()
    lifecycle.desired_state.write_bytes(desired_bytes)
    if case == "extra_old_journal":
        lifecycle.management_operations.write_bytes(b"unsupported old operation\n")
    project_settings_path = workspace / ".loushang" / "settings.json"
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=project_settings_path,
    )
    if case in {"builtin_disable", "foreign_disable"}:
        project_settings_path.parent.mkdir(parents=True, exist_ok=True)
        disabled_id = (
            "coding.lsp.default" if case == "builtin_disable" else "foreign.plugin"
        )
        project_settings_path.write_text(
            json.dumps({"disabled_plugins": [disabled_id]}), encoding="utf-8"
        )

    def cutover():
        return prepare_and_cutover_coding_package_store_from_legacy(
            lifecycle,
            settings,
            namespace_id="b" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            snapshot_admission=lambda prepared, snapshot: (
                admit_coding_single_legacy_skill_snapshot(
                    lifecycle,
                    prepared,
                    snapshot,
                    plugin_id=binding.plugin_id,
                    resource_kind=(
                        "prompt" if case.startswith("prompt_selection_of_") else "skill"
                    ),
                )
            ),
        )

    if case in {"skill", "builtin_disable", "builtin_intent", "base_remove"}:
        assert cutover().attempt.result.disposition == "fenced"
        return
    with pytest.raises(PackagePosixEpochCutoverError) as refused:
        cutover()
    assert refused.value.code == (
        "coding_legacy_prompt_snapshot_refused"
        if case.startswith("prompt_selection_of_")
        else "coding_legacy_skill_snapshot_refused"
    )
    assert not (epoch.control_root / "epoch.jsonl").exists()
    assert not epoch.epoch_root("b" * 64).exists()
    assert (lifecycle.package_root / "package-lock.json").read_bytes() == lock_bytes
    assert lifecycle.desired_state.read_bytes() == desired_bytes


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
def test_inventory_reads_one_verified_first_b_snapshot_after_old_roots_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    binding = _real_binding(tmp_path)
    (lifecycle.package_root / "package-lock.json").write_bytes(
        (tmp_path / "old-package" / "package-lock.json").read_bytes()
    )
    package = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    desired = _desired(
        tmp_path / "old-intent",
        package,
        final_state="installed_enabled",
        scope_id=lifecycle.scope_id,
    )
    assert desired.snapshot.installations
    lifecycle.desired_state.write_bytes(
        (tmp_path / "old-intent" / "old-desired.jsonl").read_bytes()
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
        snapshot_admission=lambda prepared, snapshot: (
            admit_coding_single_legacy_skill_snapshot(
                lifecycle, prepared, snapshot, plugin_id=binding.plugin_id
            )
        ),
    )
    assert cutover.attempt.result.disposition == "fenced"
    lifecycle.desired_state.write_bytes(b"changed old desired state")
    (lifecycle.package_root / "package-lock.json").write_bytes(b"changed old lock")
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
        read_only=True,
    )
    try:
        evidence = read_coding_legacy_installation_inventory(lifecycle, owner)
        fence = owner.cutover_result.fence
        assert fence is not None
        assert evidence.first_fence_id == fence.fence_id
        assert evidence.snapshot_receipt_id == fence.request.snapshot_receipt_id
        snapshot = read_posix_product_pre_b_snapshot(
            snapshot_root=epoch.snapshot_root,
            store_id=epoch.store_id,
            snapshot_receipt_id=evidence.snapshot_receipt_id,
        )
        assert snapshot is not None
        observer = CodingFirstBLegacyStateObserver(lifecycle, owner)
        legacy_state = observer.observe(
            store_id=epoch.store_id,
            legacy_root_identity=fence.request.legacy_root_identity,
        )
        assert legacy_state.state_digest == snapshot.snapshot_tree_digest
        assert legacy_state.entry_count == snapshot.snapshot.entry_count
        assert legacy_state.byte_count == snapshot.snapshot.byte_count
        with pytest.raises(CodingLegacySnapshotError, match="authority changed"):
            observer.observe(
                store_id=epoch.store_id,
                legacy_root_identity="f" * 64,
            )
        assert evidence.inventory.active_local[0].binding == binding
        assert evidence.inventory.active_local[0].desired_state == "installed_enabled"
        assert evidence.inventory.desired_journal_digest == desired.journal_digest
        reacquired = reacquire_coding_legacy_installed_local_source(
            lifecycle, owner, plugin_id=binding.plugin_id
        )
        assert not (epoch.control_root / "product-sources").exists()
        assert reacquired.inventory_evidence == evidence
        assert reacquired.installation == evidence.inventory.active_local[0]
        assert reacquired.wheel.original_source_identity == binding.source_identity
        assert reacquired.wheel.source_content_digest == binding.content_digest
        review = review_coding_legacy_installed_local_source(
            lifecycle,
            owner,
            plugin_id=binding.plugin_id,
            policy_revision="coding-product-package-policy:1",
        )
        assert review.first_fence_id == evidence.first_fence_id
        assert review.snapshot_receipt_id == evidence.snapshot_receipt_id
        assert review.legacy_root_identity == legacy_state.legacy_root_identity
        assert review.legacy_state_evidence_id == legacy_state.evidence_id
        assert review.legacy_state_digest == legacy_state.state_digest
        assert review.legacy_entry_count == legacy_state.entry_count
        assert review.legacy_byte_count == legacy_state.byte_count
        assert review.desired_state == "installed_enabled"
        assert review.wheel_artifact_digest == reacquired.wheel.artifact_digest
        assert CodingLegacyLocalAdoptionReviewV1.from_dict(review.to_dict()) == review
        with pytest.raises(ValueError, match="identity changed"):
            CodingLegacyLocalAdoptionReviewV1.from_dict(
                {**review.to_dict(), "reviewId": "0" * 64}
            )
        with pytest.raises(ValueError, match="digest is invalid"):
            CodingLegacyLocalAdoptionReviewV1.from_dict(
                {**review.to_dict(), "legacyBindingDigest": "invalid"}
            )
        monkeypatch.setattr(
            "loushang.coding.cli.package_cutover.resolve_coding_plugin_lifecycle_state_layout",
            lambda _workspace: lifecycle,
        )
        assert (
            cutover_main(
                (
                    "--workspace",
                    str(workspace),
                    "--review-legacy-local-plugin",
                    binding.plugin_id,
                )
            )
            == 0
        )
        command_review = json.loads(capsys.readouterr().out)
        assert command_review["reviewId"] == review.review_id
        assert command_review["wheelArtifactDigest"] == review.wheel_artifact_digest
        assert not (epoch.control_root / "product-state").exists()
        assert not (epoch.control_root / "product-sources").exists()
        assert (
            read_coding_legacy_installed_local_acceptance(
                lifecycle,
                owner,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:1",
            )
            is None
        )
        write_owner = PackageProductPosixFencedRuntimeOwner.open(
            authority_root=epoch.authority_root,
            control_root=epoch.control_root,
            store_id=epoch.store_id,
            epochs_root_name=epoch.epochs_root_name,
        )
        try:
            with pytest.raises(
                CodingLegacyLocalAcceptanceError, match="review ID changed"
            ):
                accept_coding_legacy_installed_local_review(
                    lifecycle,
                    write_owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                    accepted_review_id="0" * 64,
                )
            desired_path = (
                write_owner.prepare_product_state_root() / "desired-state.jsonl"
            )
            PluginDesiredStateLedger(desired_path).commit(
                PluginDesiredStateMutationV1(
                    operation_id="preexisting-product-install",
                    idempotency_key="preexisting-product-install",
                    expected_inventory_revision=0,
                    installation_key=PluginInstallationKeyV1(
                        product_id="coding",
                        installation_scope="workspace",
                        scope_id=lifecycle.scope_id,
                        plugin_id=binding.plugin_id,
                    ),
                    desired_state="installed_disabled",
                    package_revision=package,
                    actor_id="test-owner",
                    policy_revision="test-policy:1",
                )
            )
            with pytest.raises(
                CodingLegacyLocalAcceptanceError, match="Desired history"
            ):
                accept_coding_legacy_installed_local_review(
                    lifecycle,
                    write_owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                    accepted_review_id=review.review_id,
                )
            # Reset this isolated fixture so the same first-B review can prove
            # its positive first acceptance and replay below.
            desired_path.unlink()
            acceptance_path = (
                epoch.control_root
                / "product-state"
                / f"legacy-local-acceptance-{sha256(binding.plugin_id.encode()).hexdigest()[:24]}.jsonl"
            )
            redirect = tmp_path / "receipt-redirect"
            redirect.write_bytes(b"must not read or write\n")
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
                if target == acceptance_path.name and not swapped:
                    swapped = True
                    acceptance_path.symlink_to(redirect)
                original_link(
                    source,
                    target,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                    follow_symlinks=follow_symlinks,
                )

            monkeypatch.setattr(local_acceptance_module.os, "link", swap_before_publish)
            try:
                with pytest.raises(FileExistsError):
                    accept_coding_legacy_installed_local_review(
                        lifecycle,
                        write_owner,
                        plugin_id=binding.plugin_id,
                        policy_revision="coding-product-package-policy:1",
                        accepted_review_id=review.review_id,
                    )
            finally:
                monkeypatch.setattr(local_acceptance_module.os, "link", original_link)
            assert swapped
            assert redirect.read_bytes() == b"must not read or write\n"
            acceptance_path.unlink()
            receipt = accept_coding_legacy_installed_local_review(
                lifecycle,
                write_owner,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:1",
                accepted_review_id=review.review_id,
            )
            assert receipt == CodingLegacyLocalAcceptanceV1.create(review)
            assert CodingLegacyLocalAcceptanceV1.from_dict(receipt.to_dict()) == receipt
            assert (
                accept_coding_legacy_installed_local_review(
                    lifecycle,
                    write_owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                    accepted_review_id=review.review_id,
                )
                == receipt
            )
            assert (
                read_coding_legacy_installed_local_acceptance(
                    lifecycle,
                    owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                )
                == receipt
            )
            acceptance_bytes = acceptance_path.read_bytes()
            assert not (
                epoch.control_root / "product-state" / "desired-state.jsonl"
            ).exists()
            assert not (epoch.control_root / "product-sources").exists()
            source_manifest = tmp_path / "source" / "plugin.json"
            original_source_manifest = source_manifest.read_bytes()
            source_manifest.write_text(
                json.dumps({"name": "review-pack", "version": "changed"})
            )
            try:
                with pytest.raises(ValueError, match="revision changed"):
                    bind_coding_accepted_legacy_local_source(
                        lifecycle,
                        write_owner,
                        plugin_id=binding.plugin_id,
                        policy_revision="coding-product-package-policy:1",
                    )
                assert not (epoch.control_root / "product-sources").exists()
            finally:
                source_manifest.write_bytes(original_source_manifest)
            stale_product_owner = open_coding_fenced_product_application_owner(
                lifecycle,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
            try:
                product_binding = bind_coding_accepted_legacy_local_source(
                    lifecycle,
                    write_owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                )
                assert not CodingFencedProductApplicationSelection._external_bindings_current(
                    stale_product_owner, lifecycle=lifecycle
                )
            finally:
                stale_product_owner.close()
            assert product_binding.approval_id == receipt.acceptance_id
            assert product_binding.artifact_digest == review.wheel_artifact_digest
            assert (
                bind_coding_accepted_legacy_local_source(
                    lifecycle,
                    write_owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                )
                == product_binding
            )
            product_owner = open_coding_fenced_product_application_owner(
                lifecycle,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
            try:
                assert (
                    CodingFencedProductApplicationSelection._external_bindings_current(
                        product_owner, lifecycle=lifecycle
                    )
                )
                assert binding.plugin_id in {
                    item.plugin_id
                    for item in product_owner.runtime_owner.product_owner.policy.bindings
                }
            finally:
                product_owner.close()
            with pytest.raises(
                CodingLegacyLocalInstallationError, match="handoff is not settled"
            ):
                enable_coding_accepted_legacy_local_skill(
                    lifecycle,
                    workspace=workspace,
                    plugin_id=binding.plugin_id,
                    runtime_version="2.0.0",
                    runtime_protocol_epoch=2,
                )
            install_receipt = install_coding_accepted_legacy_local_plugin(
                lifecycle,
                workspace=workspace,
                plugin_id=binding.plugin_id,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
            assert install_receipt.acceptance_id == receipt.acceptance_id
            assert install_receipt.package_revision.plugin_id == binding.plugin_id
            assert review.desired_state == "installed_enabled"
            assert (
                install_coding_accepted_legacy_local_plugin(
                    lifecycle,
                    workspace=workspace,
                    plugin_id=binding.plugin_id,
                    runtime_version="2.0.0",
                    runtime_protocol_epoch=2,
                )
                == install_receipt
            )
            tampered = json.loads(acceptance_path.read_bytes())
            tampered["acceptanceId"] = "0" * 64
            acceptance_path.write_text(json.dumps(tampered) + "\n")
            with pytest.raises(ValueError, match="Journal record is invalid"):
                accept_coding_legacy_installed_local_review(
                    lifecycle,
                    write_owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                    accepted_review_id=review.review_id,
                )
            with pytest.raises(ValueError, match="Journal record is invalid"):
                read_coding_legacy_installed_local_acceptance(
                    lifecycle,
                    owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                )
            acceptance_path.unlink()
            acceptance_path.symlink_to(redirect)
            with pytest.raises(OSError):
                accept_coding_legacy_installed_local_review(
                    lifecycle,
                    write_owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                    accepted_review_id=review.review_id,
                )
            with pytest.raises(OSError):
                read_coding_legacy_installed_local_acceptance(
                    lifecycle,
                    owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                )
            assert redirect.read_bytes() == b"must not read or write\n"
            acceptance_path.unlink()
            acceptance_path.write_bytes(acceptance_bytes)
            acceptance_path.chmod(0o600)
        finally:
            write_owner.close()
        assert (
            review.review_id
            == sha256(
                json.dumps(
                    {
                        key: value
                        for key, value in review.to_dict().items()
                        if key != "reviewId"
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        assert (
            replace(review, desired_state="installed_disabled").review_id
            != review.review_id
        )
        assert (
            replace(review, legacy_state_digest="f" * 64).review_id != review.review_id
        )
        assert (
            review_coding_legacy_installed_local_source(
                lifecycle,
                owner,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:2",
            ).review_id
            != review.review_id
        )
        manifest_path = tmp_path / "source" / "plugin.json"
        original_manifest = manifest_path.read_bytes()
        manifest_path.write_text(json.dumps({"name": "review-pack", "version": "2"}))
        try:
            with pytest.raises(ValueError, match="revision changed"):
                review_coding_legacy_installed_local_source(
                    lifecycle,
                    owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                )
            assert (
                cutover_main(
                    (
                        "--workspace",
                        str(workspace),
                        "--review-legacy-local-plugin",
                        binding.plugin_id,
                    )
                )
                == 1
            )
            assert "revision changed" in capsys.readouterr().err
            changed_owner = PackageProductPosixFencedRuntimeOwner.open(
                authority_root=epoch.authority_root,
                control_root=epoch.control_root,
                store_id=epoch.store_id,
                epochs_root_name=epoch.epochs_root_name,
            )
            try:
                with pytest.raises(ValueError, match="revision changed"):
                    accept_coding_legacy_installed_local_review(
                        lifecycle,
                        changed_owner,
                        plugin_id=binding.plugin_id,
                        policy_revision="coding-product-package-policy:1",
                        accepted_review_id=review.review_id,
                    )
            finally:
                changed_owner.close()
            assert (
                epoch.control_root / "product-sources" / review.wheel_filename
            ).exists()
        finally:
            manifest_path.write_bytes(original_manifest)
        shutil.rmtree(tmp_path / "source")
        assert (
            install_coding_accepted_legacy_local_plugin(
                lifecycle,
                workspace=workspace,
                plugin_id=binding.plugin_id,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
            == install_receipt
        )
        enabled_receipt = enable_coding_accepted_legacy_local_skill(
            lifecycle,
            workspace=workspace,
            plugin_id=binding.plugin_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        assert enabled_receipt.install_command_id == install_receipt.desired_command_id
        assert enabled_receipt.package_revision == install_receipt.package_revision
        assert (
            enable_coding_accepted_legacy_local_skill(
                lifecycle,
                workspace=workspace,
                plugin_id=binding.plugin_id,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
            == enabled_receipt
        )
        enabled_owner = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        try:
            product = enabled_owner.runtime_owner.product_owner
            factory = product.factory_for_session(
                session_id="legacy-skill-selection",
                cwd=workspace,
                runtime_id="legacy-skill-selection",
            )
            selected_runtime = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id="legacy-skill-selection",
                    cwd=str(workspace),
                )
            )
            try:
                selected_runtime.activate()
                assert selected_runtime.selected_external_data_plugin_ids() == (
                    binding.plugin_id,
                )
                selected_manifest = (
                    selected_runtime.capture_selected_plugin_manifest_for(
                        binding.plugin_id,
                        max_files=64,
                        max_total_bytes=1024 * 1024,
                    )
                )
                assert selected_manifest.source_trust_snapshot is not None
                assert (
                    selected_manifest.source_trust_snapshot.source_trust_class
                    == "legacy-local-reacquired"
                )
                assert selected_manifest.verified_data_only_declarations()[0][
                    0
                ].owner == ("resources.skill")
            finally:
                selected_runtime.dispose_runtime()
            for builtin_id, enable in (
                ("coding.base", False),
                ("coding.lsp.default", True),
                ("coding.arch.default", True),
            ):
                assert _bootstrap_coding_builtin_plugin(
                    enabled_owner, builtin_id, enable=enable
                )
            with CodingFencedProductReadOnlyPreviewOwner.open(
                lifecycle
            ) as preview_owner:
                preview = preview_owner.preview_current_data_resources(
                    workspace=workspace,
                    composition_set_id="coding-standard",
                )
            assert preview.disposition == "projected"
            assert ("skill", "review", "external_package") in preview.catalog_resources
            manager = asyncio.run(
                SessionManager.new(
                    session_dir=tmp_path / "legacy-skill-session",
                    cwd=str(workspace),
                    persist=False,
                )
            )
            model = Model(
                id="legacy-skill-model",
                name="Legacy Skill Model",
                provider="test",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    reasoning=True,
                    input=("text",),
                    context_window=128000,
                    max_tokens=4096,
                ),
            )
            session = create_agent_session(
                session_manager=manager,
                model=model,
                services=create_services(settings_manager=settings),
                composition_set="coding-standard",
                package_product_runtime_factory=enabled_owner.factory_for_session(
                    manager
                ),
            )
            try:
                assert session.resource_bundle is not None
                assert any(
                    item.name == "review" and item.source_kind == "external_package"
                    for item in session.resource_bundle.skills
                )

                async def load_review():
                    await session.prepare_model_call_runtime()
                    return await session._preflight_user_input_async("/skill:review")

                loaded = asyncio.run(load_review())
                assert len(loaded.loaded_skills) == 1
                assert "# Review" in loaded.loaded_skills[0].content
            finally:
                asyncio.run(session.dispose())
            base_key = PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id="coding.base",
            )
            base_enabled = product.management.submit(
                PluginManagementCommandV1(
                    action="enable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="enable-base-after-legacy-skill",
                        idempotency_key="enable-base-after-legacy-skill",
                        expected_inventory_revision=(
                            product.desired_state.snapshot().inventory_revision
                        ),
                        installation_key=base_key,
                        desired_state="installed_enabled",
                        package_revision=None,
                        actor_id="operator",
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert base_enabled.result is not None
            assert base_enabled.result.disposition == "succeeded"
            with CodingFencedProductReadOnlyPreviewOwner.open(
                lifecycle
            ) as preview_owner:
                base_preview = preview_owner.preview_current_data_resources(
                    workspace=workspace,
                    composition_set_id="coding-standard",
                )
            assert base_preview.disposition == "projected"
            assert ("skill", "review", "external_package") in (
                base_preview.catalog_resources
            )
            base_manager = asyncio.run(
                SessionManager.new(
                    session_dir=tmp_path / "legacy-skill-base-session",
                    cwd=str(workspace),
                    persist=False,
                )
            )
            base_session = create_agent_session(
                session_manager=base_manager,
                model=model,
                services=create_services(settings_manager=settings),
                composition_set="coding-standard",
                package_product_runtime_factory=enabled_owner.factory_for_session(
                    base_manager
                ),
            )
            try:
                assert base_session.resource_bundle is not None
                assert any(
                    item.name == "review" and item.source_kind == "external_package"
                    for item in base_session.resource_bundle.skills
                )
            finally:
                asyncio.run(base_session.dispose())
            ordinary_source = tmp_path / "auditpack-1-py3-none-any.whl"
            ordinary_source.write_bytes(
                build_coding_data_skill_wheel(
                    plugin_id="auditpack",
                    version="1",
                    contribution_id="audit-skill",
                    skill_name="audit",
                    skill_document=(
                        b"---\nname: audit\ndescription: audit files\n---\n# Audit\n"
                    ),
                )
            )
            admit_coding_external_data_wheel(lifecycle, source=ordinary_source)
            mixed_owner = open_coding_fenced_product_application_owner(
                lifecycle,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
            try:
                mixed_product = mixed_owner.runtime_owner.product_owner
                ordinary_binding = next(
                    item
                    for item in mixed_product.policy.bindings
                    if item.plugin_id == "auditpack"
                )
                mixed_factory = mixed_product.factory_for_session(
                    session_id="legacy-ordinary-mixed-install",
                    cwd=workspace,
                    runtime_id="legacy-ordinary-mixed-install",
                )
                mixed_runtime = mixed_factory.create(
                    PackageProductRuntimeRequestV1(
                        product_id="coding",
                        session_id="legacy-ordinary-mixed-install",
                        cwd=str(workspace),
                    )
                )
                try:
                    mixed_runtime.activate()
                    ordinary_outcome = mixed_runtime.lifecycle.route(
                        PackageProductLifecycleIntentV1(
                            operation_id="legacy-ordinary-mixed-install",
                            action="install",
                            source=ordinary_binding.source_identity,
                            scope="project",
                        ),
                        entrypoint="operations",
                    )
                    assert ordinary_outcome.handled
                    assert ordinary_outcome.record is not None
                    assert ordinary_outcome.record.lifecycle == "installed"
                finally:
                    mixed_runtime.dispose_runtime()
                ordinary_key = PluginInstallationKeyV1(
                    product_id="coding",
                    installation_scope="workspace",
                    scope_id=lifecycle.scope_id,
                    plugin_id="auditpack",
                )
                ordinary_enabled = mixed_product.management.submit(
                    PluginManagementCommandV1(
                        action="enable",
                        mutation=PluginDesiredStateMutationV1(
                            operation_id="legacy-ordinary-mixed-enable",
                            idempotency_key="legacy-ordinary-mixed-enable",
                            expected_inventory_revision=(
                                mixed_product.desired_state.snapshot().inventory_revision
                            ),
                            installation_key=ordinary_key,
                            desired_state="installed_enabled",
                            package_revision=None,
                            actor_id="operator",
                            policy_revision=mixed_product.desired_policy_revision,
                        ),
                    )
                )
                assert ordinary_enabled.result is not None
                assert ordinary_enabled.result.disposition == "succeeded"
                mixed_manager = asyncio.run(
                    SessionManager.new(
                        session_dir=tmp_path / "legacy-ordinary-mixed-session",
                        cwd=str(workspace),
                        persist=False,
                    )
                )
                mixed_session = create_agent_session(
                    session_manager=mixed_manager,
                    model=model,
                    services=create_services(settings_manager=settings),
                    composition_set="coding-standard",
                    package_product_runtime_factory=mixed_owner.factory_for_session(
                        mixed_manager
                    ),
                )
                try:
                    assert mixed_session.resource_bundle is not None
                    assert {"review", "audit"} <= {
                        item.name
                        for item in mixed_session.resource_bundle.skills
                        if item.source_kind == "external_package"
                    }
                finally:
                    asyncio.run(mixed_session.dispose())
            finally:
                mixed_owner.close()
            key = PluginInstallationKeyV1(
                product_id="coding",
                installation_scope="workspace",
                scope_id=lifecycle.scope_id,
                plugin_id=binding.plugin_id,
            )
            disabled = product.management.submit(
                PluginManagementCommandV1(
                    action="disable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="operator-disabled-legacy-skill",
                        idempotency_key="operator-disabled-legacy-skill",
                        expected_inventory_revision=(
                            product.desired_state.snapshot().inventory_revision
                        ),
                        installation_key=key,
                        desired_state="installed_disabled",
                        package_revision=None,
                        actor_id="operator",
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert disabled.result is not None
            assert disabled.result.disposition == "succeeded"
            with pytest.raises(
                CodingLegacyLocalInstallationError,
                match="disablement was independently changed",
            ):
                enable_coding_accepted_legacy_local_skill(
                    lifecycle,
                    workspace=workspace,
                    plugin_id=binding.plugin_id,
                    runtime_version="2.0.0",
                    runtime_protocol_epoch=2,
                )
            assert product.desired_state.snapshot().installation(
                key
            ).selection.desired_state == ("installed_disabled")
            with CodingFencedProductReadOnlyPreviewOwner.open(
                lifecycle
            ) as preview_owner:
                disabled_preview = preview_owner.preview_current_data_resources(
                    workspace=workspace,
                    composition_set_id="coding-standard",
                )
            assert ("skill", "review", "external_package") not in (
                disabled_preview.catalog_resources
            )
            next_manager = asyncio.run(
                SessionManager.new(
                    session_dir=tmp_path / "legacy-skill-disabled-session",
                    cwd=str(workspace),
                    persist=False,
                )
            )
            next_owner = open_coding_fenced_product_application_owner(
                lifecycle,
                workspace=workspace,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
            try:
                next_session = create_agent_session(
                    session_manager=next_manager,
                    model=model,
                    services=create_services(settings_manager=settings),
                    composition_set="coding-standard",
                    package_product_runtime_factory=next_owner.factory_for_session(
                        next_manager
                    ),
                )
                try:
                    assert next_session.resource_bundle is not None
                    active = {
                        item.name
                        for item in next_session.resource_bundle.skills
                        if item.source_kind == "external_package"
                    }
                    assert "review" not in active
                    assert "audit" in active
                finally:
                    asyncio.run(next_session.dispose())
            finally:
                next_owner.close()
        finally:
            enabled_owner.close()
        assert (
            reopen_coding_legacy_installed_local_acceptance(
                lifecycle,
                owner,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:1",
            )
            == receipt
        )
        with pytest.raises(FileNotFoundError):
            read_coding_legacy_installed_local_acceptance(
                lifecycle,
                owner,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:1",
            )
        with pytest.raises(FileNotFoundError):
            reacquire_coding_legacy_installed_local_source(
                lifecycle, owner, plugin_id=binding.plugin_id
            )
        with pytest.raises(CodingLegacyInventoryError, match="not an installed local"):
            reacquire_coding_legacy_installed_local_source(
                lifecycle, owner, plugin_id="unselected-plugin"
            )
    finally:
        owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
@pytest.mark.parametrize(
    "case", ("executable", "prompt", "theme", "old_disabled_skill")
)
def test_accepted_legacy_local_migration_respects_skill_and_enablement_gates(
    tmp_path: Path,
    case: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    binding = _real_binding(
        tmp_path,
        executable_member=case == "executable",
        prompt_resource=case == "prompt",
        theme_resource=case == "theme",
    )
    (lifecycle.package_root / "package-lock.json").write_bytes(
        (tmp_path / "old-package" / "package-lock.json").read_bytes()
    )
    old_package = PluginPackageRevisionRefV1(
        plugin_id=binding.plugin_id,
        plugin_version="1",
        package_content_digest=binding.content_digest,
        dependency_lock_digest=binding.dependency_lock.digest,
        package_source_identity=binding.source_identity,
    )
    _desired(
        tmp_path / "old-intent",
        old_package,
        final_state=(
            "installed_disabled"
            if case == "old_disabled_skill"
            else "installed_enabled"
        ),
        scope_id=lifecycle.scope_id,
    )
    lifecycle.desired_state.write_bytes(
        (tmp_path / "old-intent" / "old-desired.jsonl").read_bytes()
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="b" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    write_owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        review = review_coding_legacy_installed_local_source(
            lifecycle,
            write_owner,
            plugin_id=binding.plugin_id,
            policy_revision="coding-product-package-policy:1",
        )
        if case == "old_disabled_skill":
            accept_coding_legacy_installed_local_review(
                lifecycle,
                write_owner,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:1",
                accepted_review_id=review.review_id,
            )
            bind_coding_accepted_legacy_local_source(
                lifecycle,
                write_owner,
                plugin_id=binding.plugin_id,
                policy_revision="coding-product-package-policy:1",
            )
        else:
            with pytest.raises(CodingLegacyLocalAcceptanceError, match="Resource type"):
                accept_coding_legacy_installed_local_review(
                    lifecycle,
                    write_owner,
                    plugin_id=binding.plugin_id,
                    policy_revision="coding-product-package-policy:1",
                    accepted_review_id=review.review_id,
                )
    finally:
        write_owner.close()
    if case == "old_disabled_skill":
        installed = install_coding_accepted_legacy_local_plugin(
            lifecycle,
            workspace=workspace,
            plugin_id=binding.plugin_id,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        assert installed.plugin_id == binding.plugin_id
        with pytest.raises(
            CodingLegacyLocalInstallationError,
            match="no accepted enabled selection",
        ):
            enable_coding_accepted_legacy_local_skill(
                lifecycle,
                workspace=workspace,
                plugin_id=binding.plugin_id,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
    else:
        with pytest.raises(
            CodingLegacyLocalInstallationError, match="no accepted review"
        ):
            install_coding_accepted_legacy_local_plugin(
                lifecycle,
                workspace=workspace,
                plugin_id=binding.plugin_id,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
    product_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        product = product_owner.runtime_owner.product_owner
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=binding.plugin_id,
        )
        state = product.desired_state.snapshot()
        if case == "old_disabled_skill":
            assert (
                state.installation(key).selection.desired_state == "installed_disabled"
            )
        else:
            assert not any(item.installation_key == key for item in state.installations)
    finally:
        product_owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
@pytest.mark.parametrize("old_desired", (False, True))
def test_inventory_accepts_missing_lock_only_for_empty_old_state(
    tmp_path: Path, old_desired: bool
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    if old_desired:
        lifecycle.desired_state.write_bytes(b"old desired state\n")
    global_path = tmp_path / "global-settings.json"
    global_path.write_text('{"disabled_plugins":["coding.base"]}\n')
    settings = SettingsManager(
        global_settings_path=global_path,
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
    )
    try:
        if old_desired:
            with pytest.raises(CodingLegacyDesiredError, match="invalid"):
                read_coding_legacy_installation_inventory(lifecycle, owner)
            return
        evidence = read_coding_legacy_installation_inventory(lifecycle, owner)
        assert evidence.inventory.active_local == ()
        assert evidence.inventory.lockfile_digest is None
        assert evidence.inventory.desired_journal_digest is None
    finally:
        owner.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product cutover")
def test_inventory_reads_builtin_only_desired_without_old_lock(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    builtin = PluginPackageRevisionRefV1(
        plugin_id="coding.arch.default",
        plugin_version="1",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="embedded:coding.arch.default",
    )
    desired = _desired(
        tmp_path / "old-intent",
        builtin,
        final_state="installed_disabled",
        scope_id=lifecycle.scope_id,
    )
    lifecycle.desired_state.write_bytes(
        (tmp_path / "old-intent" / "old-desired.jsonl").read_bytes()
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
    owner = PackageProductPosixFencedRuntimeOwner.open(
        authority_root=epoch.authority_root,
        control_root=epoch.control_root,
        store_id=epoch.store_id,
        epochs_root_name=epoch.epochs_root_name,
        read_only=True,
    )
    try:
        inventory = read_coding_legacy_installation_inventory(
            lifecycle, owner
        ).inventory
        assert inventory.active_local == ()
        assert inventory.builtin_intent == (
            CodingLegacyBuiltinIntentV1("coding.arch.default", "installed_disabled"),
        )
        assert inventory.desired_journal_digest == desired.journal_digest
        assert inventory.lockfile_digest is None
    finally:
        owner.close()
