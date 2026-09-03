"""Product-owned PLC9A2 runtime activation at the Session bootstrap boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleInventoryPort,
    PackageProductLifecycleMode,
    PackageProductLifecycleOperationPort,
)

PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION = 1
PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION = 1


class PackageProductRuntimeActivationError(RuntimeError):
    """Stable refusal raised before the standard Session activation graph."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageProductRuntimeRequestV1:
    """Identity-only request used by a Product to select its runtime owners."""

    product_id: str
    session_id: str
    cwd: str
    request_version: int = PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.product_id, "Package Product id"),
            (self.session_id, "Package Product Session id"),
            (self.cwd, "Package Product cwd"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        cwd = Path(self.cwd)
        if not cwd.is_absolute():
            raise ValueError("Package Product cwd must be absolute")
        object.__setattr__(self, "cwd", str(cwd.resolve(strict=False)))
        if self.request_version != PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION:
            raise ValueError("Unsupported Package Product runtime request")


@dataclass(frozen=True, slots=True)
class PackageProductRuntimeBindingV1:
    """One aggregate binding for lifecycle, inventory, and rollout policy."""

    product_id: str
    lifecycle: PackageProductLifecycleOperationPort
    inventory: PackageProductLifecycleInventoryPort
    mode: PackageProductLifecycleMode
    binding_version: int = PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.product_id, str) or not self.product_id:
            raise ValueError("Package Product runtime id must be non-empty")
        if self.mode not in {"dark", "enforced"}:
            raise ValueError("Activated Package Product runtime cannot use legacy mode")
        if not callable(getattr(self.lifecycle, "activate", None)):
            raise TypeError("Package Product lifecycle activation is required")
        lifecycle_binding = getattr(self.lifecycle, "binding_id", None)
        inventory_binding = getattr(self.inventory, "binding_id", None)
        if (
            not isinstance(lifecycle_binding, str)
            or not lifecycle_binding
            or inventory_binding != lifecycle_binding
        ):
            raise ValueError("Package Product runtime owners changed binding")
        if self.binding_version != PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION:
            raise ValueError("Unsupported Package Product runtime binding")

    @property
    def binding_id(self) -> str:
        return self.lifecycle.binding_id

    def activate(self) -> PackageProductRuntimeBindingV1:
        """Activate recovery/admission and re-attest the aggregate afterwards."""

        try:
            self.lifecycle.activate()
            active = self.lifecycle.active
            lifecycle_binding = self.lifecycle.binding_id
            inventory_binding = self.inventory.binding_id
        except BaseException as error:
            raise PackageProductRuntimeActivationError(
                "Package Product runtime activation failed",
                code="package_product_runtime_activation_failed",
            ) from error
        if not active:
            raise PackageProductRuntimeActivationError(
                "Package Product lifecycle did not become active",
                code="package_product_runtime_activation_incomplete",
            )
        if inventory_binding != lifecycle_binding:
            raise PackageProductRuntimeActivationError(
                "Package Product runtime owners changed binding",
                code="package_product_runtime_binding_changed",
            )
        return self


class PackageProductRuntimeFactoryPort(Protocol):
    """Product policy seam that constructs one aggregate runtime per Session."""

    def create(
        self,
        request: PackageProductRuntimeRequestV1,
    ) -> PackageProductRuntimeBindingV1: ...


def activate_package_product_runtime(
    factory: PackageProductRuntimeFactoryPort,
    request: PackageProductRuntimeRequestV1,
) -> PackageProductRuntimeBindingV1:
    """Create exactly once, validate exactly, then activate before bootstrap."""

    create = getattr(factory, "create", None)
    if not callable(create):
        raise TypeError("Package Product runtime factory is required")
    try:
        binding = create(request)
    except BaseException as error:
        raise PackageProductRuntimeActivationError(
            "Package Product runtime factory failed",
            code="package_product_runtime_factory_failed",
        ) from error
    if not isinstance(binding, PackageProductRuntimeBindingV1):
        raise PackageProductRuntimeActivationError(
            "Package Product runtime factory returned an invalid binding",
            code="package_product_runtime_binding_invalid",
        )
    if binding.product_id != request.product_id:
        raise PackageProductRuntimeActivationError(
            "Package Product runtime changed Product identity",
            code="package_product_runtime_product_changed",
        )
    return binding.activate()


__all__ = [
    "PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION",
    "PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION",
    "PackageProductRuntimeActivationError",
    "PackageProductRuntimeBindingV1",
    "PackageProductRuntimeFactoryPort",
    "PackageProductRuntimeRequestV1",
    "activate_package_product_runtime",
]
