"""Capability-aware preparation of narrow Resource Catalog source inputs."""

from __future__ import annotations

from dataclasses import dataclass, field

from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    ResourceContributionSpec,
)
from loushang.harness.resources._catalog_package_source import (
    VerifiedPackageResourceInput,
    acquire_verified_package_resource_input,
)
from loushang.harness.resources.plugins.revisions import VerifiedRevisionHandle
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


@dataclass(frozen=True, slots=True, init=False)
class AdmittedPackageResource:
    """Exact owner admission paired with its source-owned verified lease."""

    admission: OwnerContributionAdmissionRecord = field(repr=False)
    verified_input: VerifiedPackageResourceInput = field(repr=False)

    def __init__(self) -> None:
        raise TypeError("Admitted package Resources are owner-prepared")

    @property
    def revision_handle(self) -> VerifiedRevisionHandle:
        return self.verified_input.revision_handle

    @property
    def source_root_order(self) -> int:
        return self.verified_input.source_root_order

    def policy_payload(self) -> dict[str, object]:
        return self.verified_input.policy_payload()

    def close(self) -> None:
        self.verified_input.revision_handle.close()


def acquire_admitted_package_resource(
    *,
    admission: OwnerContributionAdmissionRecord,
    revision_handle: VerifiedRevisionHandle,
    source_root_order: int = 0,
) -> AdmittedPackageResource:
    """Validate owner evidence, then acquire one independently disposable lease."""

    if not isinstance(admission, OwnerContributionAdmissionRecord):
        raise TypeError("Package Resource requires an owner admission")
    contribution = admission.candidate.contribution
    if admission.contribution_kind != "resource_item" or not isinstance(
        contribution,
        ResourceContributionSpec,
    ):
        raise ValueError("Package Resource admission must contain resource_item")
    if not isinstance(revision_handle, VerifiedRevisionHandle):
        raise TypeError("Package Resource requires a verified revision handle")
    if revision_handle.closed:
        raise ValueError("Package Resource revision handle must be live")
    if admission.candidate.package_content_digest != revision_handle.content_digest:
        raise ValueError("Package Resource admission must match its revision")
    instance_ref = admission.candidate.instance_revision_ref
    if instance_ref.plugin_id != admission.plugin_id:
        raise ValueError("Package Resource instance must match its Plugin")
    verified = acquire_verified_package_resource_input(
        revision_handle=revision_handle,
        product_id=admission.product_id,
        resource_contribution_id=admission.contribution_id,
        resource_admission_fingerprint=admission.fingerprint,
        plugin_instance_revision_ref=_instance_revision_text(instance_ref),
        resource_kind=contribution.resource_kind,
        locator=contribution.locator,
        locator_kind=contribution.locator_kind,
        media_type=contribution.media_type,
        schema_id=contribution.schema_id,
        schema_version=contribution.schema_version,
        managed_skill_actions=contribution.managed_skill_actions,
        source_root_order=source_root_order,
    )
    value = object.__new__(AdmittedPackageResource)
    object.__setattr__(value, "admission", admission)
    object.__setattr__(value, "verified_input", verified)
    return value


def _instance_revision_text(ref: PluginInstanceRevisionRef) -> str:
    return f"{ref.instance_id}:{ref.plugin_id}@{ref.revision}"


__all__ = [
    "AdmittedPackageResource",
    "acquire_admitted_package_resource",
]
