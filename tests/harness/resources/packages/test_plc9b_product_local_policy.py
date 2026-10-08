from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    PackageAcquisitionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencyResolutionError,
    PackageDependencySelectionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleIngressRequestV2,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleAction,
    PackageProductLifecycleIntentV1,
)


def _policy(tmp_path: Path):
    from loushang.harness.resources.packages.product_local_wheel_policy import (
        PackageProductLocalWheelBindingV1,
        PackageProductLocalWheelPolicy,
    )

    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700, exist_ok=True)
    source = source_root / "acme_plugin-1.0-py3-none-any.whl"
    source.write_bytes(b"pinned-wheel-bytes")
    return PackageProductLocalWheelPolicy(
        product_id="coding",
        project_scope_id="workspace:test",
        source_root=source_root,
        bindings=(
            PackageProductLocalWheelBindingV1(
                source_identity=str(source),
                requested_package="acme-plugin==1.0",
                plugin_id="acme.plugin",
                artifact_digest=sha256(source.read_bytes()).hexdigest(),
            ),
        ),
        policy_revision="coding-local-wheel:1",
        quota_profile_revision="coding-local-wheel-quota:1",
        resolution_environment_fingerprint="a" * 64,
        authority_id="coding-local-wheel-policy",
        classifier_epoch=1,
    )


def _intent(
    source: str,
    *,
    operation_id: str,
    scope: str = "project",
    action: PackageProductLifecycleAction = "install",
) -> PackageProductLifecycleIntentV1:
    return PackageProductLifecycleIntentV1(
        operation_id=operation_id,
        action=action,
        source=source,
        scope=scope,
    )


def test_source_trust_requires_explicit_product_binding(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    binding = policy.bindings[0]
    assert binding.source_trust_class is None
    trusted = replace(
        policy,
        bindings=(replace(binding, source_trust_class="host-equivalent-local"),),
    )
    assert trusted.authority_revision != policy.authority_revision
    with pytest.raises(ValueError, match="source trust class"):
        replace(binding, source_trust_class="host equivalent local")


def test_worker_wheel_policy_requires_exact_separate_product_admission(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.packages.product_local_wheel_policy import (
        PackageProductLocalWorkerAdmissionV1,
    )

    policy = _policy(tmp_path)
    binding = policy.bindings[0]
    admission = PackageProductLocalWorkerAdmissionV1(
        contribution_id="query-provider",
        owner_id="coding.lsp",
        native_platform="linux-x86_64",
    )
    with pytest.raises(ValueError, match="requires exact admission"):
        replace(binding, source_trust_class="local-worker-candidate")
    with pytest.raises(ValueError, match="requires Worker candidate trust"):
        replace(binding, worker_admission=admission)
    selected = replace(
        binding,
        source_trust_class="local-worker-candidate",
        plugin_manifest_path="acme_plugin/plugin.json",
        worker_admission=admission,
    )
    worker_policy = replace(policy, bindings=(selected,))
    assert worker_policy.authority_revision != policy.authority_revision
    assert (
        replace(
            worker_policy,
            bindings=(
                replace(
                    selected,
                    worker_admission=replace(
                        admission, contribution_id="other-provider"
                    ),
                ),
            ),
        ).authority_revision
        != worker_policy.authority_revision
    )


def test_configured_local_wheel_is_plugin_bound_by_durable_product_facts(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path)
    source = str(tmp_path / "sources" / "acme_plugin-1.0-py3-none-any.whl")
    journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal, classification_authority=policy, enabled=True
    )

    status = owner.submit(policy.create(_intent(source, operation_id="operation:known")))
    assert status.classification is not None
    assert status.classification.decision == "plugin_bound"
    assert status.classification.basis_facts.facts[0].present
    request = journal.request("operation:known")
    assert request is not None
    assert policy.recheck(request, status.classification) == status.classification


def test_product_rebind_preflight_proves_original_policy_and_current_root_bytes(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.packages.product_local_wheel_policy import (
        PackageProductRebindSourceError,
    )

    policy = _policy(tmp_path)
    source = policy.bindings[0].source_identity
    journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal, classification_authority=policy, enabled=True
    )
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        policy.create(_intent(source, operation_id="operation:rebind-proof")),
        runtime_admission_request_id="f" * 64,
    )
    classified = owner.submit(ingress)
    interrupted = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    request = journal.request(classified.operation_id)
    assert request is not None
    journal_before = journal.path.read_bytes()

    proof = policy.prove_rebind_root_source(
        request, interrupted, max_bytes=1024
    )
    assert proof.artifact_digest == policy.bindings[0].artifact_digest
    assert proof.source_ref == sha256(source.encode()).hexdigest()
    assert journal.path.read_bytes() == journal_before

    changed_policy = replace(policy, policy_revision="coding-local-wheel:2")
    with pytest.raises(PackageProductRebindSourceError) as changed_authority:
        changed_policy.prove_rebind_root_source(
            request, interrupted, max_bytes=1024
        )
    assert changed_authority.value.code == "package_rebind_source_policy_changed"

    Path(source).write_bytes(b"changed")
    with pytest.raises(PackageProductRebindSourceError) as changed_bytes:
        policy.prove_rebind_root_source(request, interrupted, max_bytes=1024)
    assert changed_bytes.value.code == "package_source_digest_mismatch"


def test_product_rebind_preflight_proves_selected_dependency_bytes(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.packages.product_local_wheel_policy import (
        PackageProductLocalWheelDependencyV1,
        PackageProductRebindSourceError,
    )

    policy = _policy(tmp_path)
    dependency_source = policy.source_root / "helper-2.0-py3-none-any.whl"
    dependency_source.write_bytes(b"pinned-dependency-bytes")
    policy = replace(
        policy,
        dependencies=(
            PackageProductLocalWheelDependencyV1(
                source_identity=str(dependency_source),
                project_name="helper",
                version="2.0",
                artifact_digest=sha256(dependency_source.read_bytes()).hexdigest(),
            ),
        ),
    )
    journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal, classification_authority=policy, enabled=True
    )
    ingress = PackageLifecycleIngressRequestV2.bind_runtime_admission(
        policy.create(
            _intent(policy.bindings[0].source_identity, operation_id="operation:deps")
        ),
        runtime_admission_request_id="f" * 64,
    )
    classified = owner.submit(ingress)
    failed = owner.interrupt(
        classified.operation_id,
        expected_phase=classified.phase,
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    request = journal.request(failed.operation_id)
    assert request is not None
    selection = policy.resolve(
        PackageDependencySelectionRequestV1(
            operation_id=failed.operation_id,
            attempt_epoch=failed.attempt_epoch,
            parent_node_id="root",
            request_fingerprint=failed.request_fingerprint,
            resolution_environment_fingerprint=(
                policy.resolution_environment_fingerprint
            ),
            requirement=NormalizedPackageRequirementV1.parse("helper==2.0"),
        )
    )
    journal_before = journal.path.read_bytes()

    proofs = policy.prove_rebind_selected_sources(
        request, failed, selections=(selection,), max_bytes=1024
    )
    assert tuple(item.artifact_digest for item in proofs) == (
        policy.bindings[0].artifact_digest,
        policy.dependencies[0].artifact_digest,
    )
    assert journal.path.read_bytes() == journal_before

    with pytest.raises(PackageProductRebindSourceError) as changed_selection:
        policy.prove_rebind_selected_sources(
            request,
            failed,
            selections=(replace(selection, resolver_revision="stale"),),
            max_bytes=1024,
        )
    assert changed_selection.value.code == "package_rebind_dependency_selection_changed"

    dependency_source.write_bytes(b"changed-dependency")
    with pytest.raises(PackageProductRebindSourceError) as changed_bytes:
        policy.prove_rebind_selected_sources(
            request, failed, selections=(selection,), max_bytes=1024
        )
    assert changed_bytes.value.code == "package_source_digest_mismatch"

    dependency_source.write_bytes(b"pinned-dependency-bytes")
    with pytest.raises(PackageProductRebindSourceError) as over_budget:
        policy.prove_rebind_selected_sources(
            request, failed, selections=(selection,), max_bytes=25
        )
    assert over_budget.value.code == "package_source_size_limit"


def test_plugin_manifest_path_is_an_exact_product_policy_fact(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    (binding,) = policy.bindings
    with pytest.raises(ValueError, match="manifest path is invalid"):
        replace(binding, plugin_manifest_path="../plugin.json")
    with pytest.raises(ValueError, match="must name plugin.json"):
        replace(binding, plugin_manifest_path="acme_plugin/declarations.json")

    selected = replace(binding, plugin_manifest_path="acme_plugin/plugin.json")
    updated = replace(policy, bindings=(selected,))
    assert updated.authority_revision != policy.authority_revision


def test_unknown_or_wrong_scope_source_is_durably_indeterminate(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path)
    journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal, classification_authority=policy, enabled=True
    )
    known = str(tmp_path / "sources" / "acme_plugin-1.0-py3-none-any.whl")
    unknown = "https://user:secret@example.test/unknown.whl?token=hidden"

    for operation_id, source, scope in (
        ("operation:unknown", unknown, "project"),
        ("operation:alias", f"{known}?token=hidden", "project"),
        ("operation:wrong-scope", known, "user"),
    ):
        status = owner.submit(
            policy.create(_intent(source, operation_id=operation_id, scope=scope))
        )
        assert status.classification is not None
        assert status.classification.decision == "indeterminate"
        assert status.disposition == "rejected"
        assert status.failure is not None
        assert status.failure.code == "package_target_classification_indeterminate"
        request = journal.request(operation_id)
        assert request is not None
        assert policy.recheck(request, status.classification).decision == "indeterminate"
    assert b"secret" not in journal.path.read_bytes()
    assert b"hidden" not in journal.path.read_bytes()


def test_forged_ingress_or_changed_product_config_loses_classification(
    tmp_path: Path,
) -> None:
    policy = _policy(tmp_path)
    source = str(tmp_path / "sources" / "acme_plugin-1.0-py3-none-any.whl")
    ingress = policy.create(_intent(source, operation_id="operation:forged"))
    forged = replace(ingress, requested_plugin_id="other.plugin")
    assert not policy.classification_facts(forged).facts[0].present

    journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal, classification_authority=policy, enabled=True
    )
    status = owner.submit(ingress)
    assert status.classification is not None
    request = journal.request(status.operation_id)
    assert request is not None
    changed = replace(
        policy,
        policy_revision="coding-local-wheel:2",
    )
    assert changed.recheck(request, status.classification) != status.classification


def test_local_wheel_binding_does_not_authorize_removal(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    source = str(tmp_path / "sources" / "acme_plugin-1.0-py3-none-any.whl")
    journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    owner = PackageLifecycleOwner(
        journal=journal, classification_authority=policy, enabled=True
    )

    for action in ("remove", "uninstall"):
        intent = _intent(source, operation_id=f"operation:{action}", action=action)
        status = owner.submit(policy.create(intent))
        assert status.classification is not None
        assert status.classification.decision == "indeterminate"
        assert status.disposition == "rejected"


def test_local_wheel_dependency_selection_uses_same_product_source_policy(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.packages.product_local_wheel_policy import (
        PackageProductLocalWheelDependencyV1,
    )

    root_policy = _policy(tmp_path)
    source = root_policy.source_root / "dependency-2.0-py3-none-any.whl"
    source.write_bytes(b"dependency-wheel-bytes")
    policy = replace(
        root_policy,
        dependencies=(
            PackageProductLocalWheelDependencyV1(
                source_identity=str(source),
                project_name="dependency",
                version="2.0",
                artifact_digest=sha256(source.read_bytes()).hexdigest(),
            ),
        ),
    )
    request = PackageDependencySelectionRequestV1(
        operation_id="operation:dependency",
        attempt_epoch=1,
        parent_node_id="root",
        request_fingerprint="b" * 64,
        resolution_environment_fingerprint=(
            policy.resolution_environment_fingerprint
        ),
        requirement=NormalizedPackageRequirementV1.parse("dependency>=2.0"),
    )

    selected = policy.resolve(request)
    assert selected.matches(request)
    assert selected.canonical_source_identity == str(source)
    assert selected.expected_artifact_digest == policy.dependencies[0].artifact_digest
    assert selected.resolver_revision == policy.authority_revision
    acquisition = PackageAcquisitionRequestV1(
        operation_id=request.operation_id,
        attempt_epoch=request.attempt_epoch,
        node_id=selected.node_id,
        canonical_source_identity=selected.canonical_source_identity,
        request_fingerprint=request.request_fingerprint,
        requested_locator_digest=sha256(str(source).encode()).hexdigest(),
        policy_revision=policy.policy_revision,
    )
    assert (
        policy.source_authority()
        .authorize(acquisition)
        .envelope.expected_artifact_digest
        == selected.expected_artifact_digest
    )

    for refused in (
        replace(request, requirement=NormalizedPackageRequirementV1.parse("other>=1")),
        replace(request, requirement=NormalizedPackageRequirementV1.parse("dependency<2")),
        replace(request, resolution_environment_fingerprint="c" * 64),
    ):
        with pytest.raises(PackageDependencyResolutionError):
            policy.resolve(refused)

    with pytest.raises(ValueError, match="Source roles"):
        replace(
            root_policy,
            dependencies=(
                replace(
                    policy.dependencies[0],
                    source_identity=root_policy.bindings[0].source_identity,
                ),
            ),
        )


def test_local_wheel_dependency_selection_retains_multiple_exact_versions(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.packages.product_local_wheel_policy import (
        PackageProductLocalWheelDependencyV1,
    )

    root_policy = _policy(tmp_path)
    dependencies = []
    for version in ("1.0", "10.0", "2.0"):
        source = root_policy.source_root / f"dependency-{version}-py3-none-any.whl"
        source.write_bytes(f"dependency-{version}".encode())
        dependencies.append(
            PackageProductLocalWheelDependencyV1(
                source_identity=str(source),
                project_name="dependency",
                version=version,
                artifact_digest=sha256(source.read_bytes()).hexdigest(),
            )
        )
    policy = replace(root_policy, dependencies=tuple(dependencies))
    request = PackageDependencySelectionRequestV1(
        operation_id="operation:versioned-dependency",
        attempt_epoch=1,
        parent_node_id="root",
        request_fingerprint="b" * 64,
        resolution_environment_fingerprint=(
            policy.resolution_environment_fingerprint
        ),
        requirement=NormalizedPackageRequirementV1.parse("dependency>=1"),
    )

    assert policy.resolve(request).version == "10.0"
    assert policy.resolve(
        replace(
            request,
            requirement=NormalizedPackageRequirementV1.parse("dependency<3"),
        )
    ).version == "2.0"
    for dependency in dependencies:
        exact = replace(
            request,
            requirement=NormalizedPackageRequirementV1.parse(
                f"dependency=={dependency.version}"
            ),
        )
        selected = policy.resolve(exact)
        acquisition = PackageAcquisitionRequestV1(
            operation_id=exact.operation_id,
            attempt_epoch=exact.attempt_epoch,
            node_id=selected.node_id,
            canonical_source_identity=selected.canonical_source_identity,
            request_fingerprint=exact.request_fingerprint,
            requested_locator_digest=sha256(
                selected.canonical_source_identity.encode()
            ).hexdigest(),
            policy_revision=policy.policy_revision,
        )
        assert (
            policy.source_authority()
            .authorize(acquisition)
            .envelope.expected_artifact_digest
            == dependency.artifact_digest
        )

    with pytest.raises(ValueError, match="uniquely ordered"):
        replace(root_policy, dependencies=tuple(reversed(dependencies)))
    with pytest.raises(ValueError, match="uniquely ordered"):
        replace(
            policy,
            dependencies=(
                *dependencies,
                replace(dependencies[-1], version="2.0.0"),
            ),
        )
