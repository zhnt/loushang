"""Product authority for the exact logical Plugin root of a Package set."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV1,
    PluginBoundPackageClassificationV1,
    canonical_json_bytes,
    classify_package_request,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackagePluginRootTargetV1,
)

PackageProductInstallationScope = Literal["process", "tenant", "workspace"]
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


@dataclass(frozen=True, slots=True)
class PackageProductRootTargetAuthority:
    """Issue a stable Installation identity only for exact Plugin classification."""

    product_id: str
    installation_scope: PackageProductInstallationScope
    authority_id: str
    authority_revision: str

    def __post_init__(self) -> None:
        if self.installation_scope not in {"process", "tenant", "workspace"}:
            raise ValueError("Package Product installation scope is invalid")
        for value, name in (
            (self.product_id, "Product identity"),
            (self.authority_id, "root target authority identity"),
            (self.authority_revision, "root target authority revision"),
        ):
            if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
                raise ValueError(f"Package Product {name} is invalid")

    def issue_target(
        self,
        request: PackageLifecycleRequestV1,
        classification: PluginBoundPackageClassificationV1,
    ) -> PackagePluginRootTargetV1:
        if not isinstance(request, PackageLifecycleRequestV1) or not isinstance(
            classification, PluginBoundPackageClassificationV1
        ):
            raise TypeError("Package Product request and classification are required")
        if request.product_id != self.product_id:
            raise ValueError("Package Product root target changed Product identity")
        if (
            request.action not in {"install", "update"}
            or request.requested_plugin_id is None
            or classification.decision != "plugin_bound"
            or classification != classify_package_request(request)
        ):
            raise ValueError("Package Product root target changed classification")
        installation_id = "installation:" + sha256(
            canonical_json_bytes(
                {
                    "installationScope": self.installation_scope,
                    "pluginId": request.requested_plugin_id,
                    "productId": request.product_id,
                    "scopeId": request.scope_id,
                }
            )
        ).hexdigest()
        return PackagePluginRootTargetV1.create(
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            product_id=request.product_id,
            scope_id=request.scope_id,
            installation_id=installation_id,
            plugin_id=request.requested_plugin_id,
            authority_id=self.authority_id,
            authority_revision=self.authority_revision,
        )


__all__ = ["PackageProductRootTargetAuthority"]
