from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from loushang.harness.resources.packages.product_runtime import (
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
    activate_package_product_runtime,
)


class _Lifecycle:
    def __init__(
        self,
        binding_id: str = "owner:one",
        *,
        fail: BaseException | None = None,
        publish_active: bool = True,
    ) -> None:
        self.binding_id = binding_id
        self.active = False
        self.fail = fail
        self.publish_active = publish_active
        self.activations = 0

    def activate(self) -> object:
        self.activations += 1
        if self.fail is not None:
            raise self.fail
        self.active = self.publish_active
        return object()


class _Inventory:
    def __init__(self, binding_id: str = "owner:one") -> None:
        self.binding_id = binding_id


class _Factory:
    def __init__(
        self,
        binding: object,
        *,
        fail: BaseException | None = None,
    ) -> None:
        self.binding = binding
        self.fail = fail
        self.requests: list[PackageProductRuntimeRequestV1] = []

    def create(
        self,
        request: PackageProductRuntimeRequestV1,
    ) -> PackageProductRuntimeBindingV1:
        self.requests.append(request)
        if self.fail is not None:
            raise self.fail
        return cast(PackageProductRuntimeBindingV1, self.binding)


def _binding(
    lifecycle: _Lifecycle | None = None,
    inventory: _Inventory | None = None,
    *,
    product_id: str = "product:test",
) -> PackageProductRuntimeBindingV1:
    return PackageProductRuntimeBindingV1(
        product_id=product_id,
        lifecycle=cast(Any, lifecycle or _Lifecycle()),
        inventory=cast(Any, inventory or _Inventory()),
        mode="enforced",
    )


def test_package_product_runtime_activates_one_aggregate_before_use(
    tmp_path: Path,
) -> None:
    lifecycle = _Lifecycle()
    binding = _binding(lifecycle)
    factory = _Factory(binding)
    request = PackageProductRuntimeRequestV1(
        product_id="product:test",
        session_id="session:test",
        cwd=str(tmp_path),
    )

    result = activate_package_product_runtime(cast(Any, factory), request)

    assert result is binding
    assert factory.requests == [request]
    assert lifecycle.activations == 1
    assert lifecycle.active
    assert result.binding_id == "owner:one"


def test_package_product_runtime_rejects_split_owner_binding() -> None:
    with pytest.raises(ValueError, match="changed binding"):
        _binding(_Lifecycle("owner:one"), _Inventory("owner:two"))


def test_package_product_runtime_rejects_product_substitution(tmp_path: Path) -> None:
    factory = _Factory(_binding(product_id="product:other"))

    with pytest.raises(PackageProductRuntimeActivationError) as raised:
        activate_package_product_runtime(
            cast(Any, factory),
            PackageProductRuntimeRequestV1(
                product_id="product:test",
                session_id="session:test",
                cwd=str(tmp_path),
            ),
        )

    assert raised.value.code == "package_product_runtime_product_changed"
    assert factory.requests[0].product_id == "product:test"


def test_package_product_runtime_factory_failure_is_opaque(tmp_path: Path) -> None:
    factory = _Factory(
        _binding(),
        fail=RuntimeError("file:///private?token=secret"),
    )

    with pytest.raises(PackageProductRuntimeActivationError) as raised:
        activate_package_product_runtime(
            cast(Any, factory),
            PackageProductRuntimeRequestV1(
                product_id="product:test",
                session_id="session:test",
                cwd=str(tmp_path),
            ),
        )

    assert raised.value.code == "package_product_runtime_factory_failed"
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize(
    ("lifecycle", "code"),
    [
        (
            _Lifecycle(fail=RuntimeError("file:///private?token=secret")),
            "package_product_runtime_activation_failed",
        ),
        (
            _Lifecycle(publish_active=False),
            "package_product_runtime_activation_incomplete",
        ),
    ],
)
def test_package_product_runtime_activation_fails_closed_without_detail(
    tmp_path: Path,
    lifecycle: _Lifecycle,
    code: str,
) -> None:
    factory = _Factory(_binding(lifecycle))

    with pytest.raises(PackageProductRuntimeActivationError) as raised:
        activate_package_product_runtime(
            cast(Any, factory),
            PackageProductRuntimeRequestV1(
                product_id="product:test",
                session_id="session:test",
                cwd=str(tmp_path),
            ),
        )

    assert raised.value.code == code
    assert "secret" not in str(raised.value)


def test_package_product_runtime_request_requires_absolute_cwd() -> None:
    with pytest.raises(ValueError, match="must be absolute"):
        PackageProductRuntimeRequestV1(
            product_id="product:test",
            session_id="session:test",
            cwd="relative",
        )
