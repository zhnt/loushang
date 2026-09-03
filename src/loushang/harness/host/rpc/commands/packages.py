"""Package inventory and lifecycle commands for the shared RPC host."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

from loushang.harness.host.rpc.arguments import optional_string, require_string
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.resources.packages.product_contract import (
    PACKAGE_PRODUCT_LIFECYCLE_FAILURE_CODES,
    PACKAGE_PRODUCT_UPDATE_CHECK_VERSION,
    PackageProductLifecycleAction,
    PackageProductLifecycleRecordV1,
    PackageProductUpdateCheckV1,
    canonicalize_package_product_scope,
)


class _PackageCapabilityUnavailable(RuntimeError):
    pass


class _ProductPackageOperationError(RuntimeError):
    """Opaque marker that prevents Product exceptions crossing RPC."""


@dataclass(frozen=True)
class _PackageCollectionResult:
    value: object
    product_bound: bool


@dataclass(frozen=True)
class _PackageLifecycleResult:
    value: object
    product_bound: bool


class _PackageCapabilities(Protocol):
    """Semantic package capabilities consumed by this command group."""

    def get_packages(self, *, catalog_path: str | None) -> object: ...

    def materialize_package(
        self, source: str, *, operation_id: str, scope: str
    ) -> object: ...

    def install_package(
        self, source: str, *, operation_id: str, scope: str
    ) -> object: ...

    def update_package(
        self, source: str, *, operation_id: str, scope: str
    ) -> object: ...

    def remove_package(
        self, source: str, *, operation_id: str, scope: str
    ) -> object: ...

    def uninstall_package(
        self, source: str, *, operation_id: str, scope: str
    ) -> object: ...

    def update_packages(self, *, operation_id: str, scope: str) -> object: ...

    def check_package_updates(self, *, operation_id: str, scope: str) -> object: ...


class _DynamicPackageCapabilities:
    """Resolve optional Product package operations at the invocation boundary."""

    def __init__(self, *, runtime: object, get_session: Callable[[], object]) -> None:
        self._runtime = runtime
        self._get_session = get_session

    def get_packages(self, *, catalog_path: str | None) -> object:
        return self._invoke("get_packages", catalog_path=catalog_path)

    def materialize_package(
        self, source: str, *, operation_id: str, scope: str
    ) -> object:
        return self._invoke_lifecycle(
            "materialize", source, operation_id=operation_id, scope=scope
        )

    def install_package(self, source: str, *, operation_id: str, scope: str) -> object:
        return self._invoke_lifecycle(
            "install", source, operation_id=operation_id, scope=scope
        )

    def update_package(self, source: str, *, operation_id: str, scope: str) -> object:
        return self._invoke_lifecycle(
            "update", source, operation_id=operation_id, scope=scope
        )

    def remove_package(self, source: str, *, operation_id: str, scope: str) -> object:
        return self._invoke_lifecycle(
            "remove", source, operation_id=operation_id, scope=scope
        )

    def uninstall_package(
        self, source: str, *, operation_id: str, scope: str
    ) -> object:
        return self._invoke_lifecycle(
            "uninstall", source, operation_id=operation_id, scope=scope
        )

    def update_packages(self, *, operation_id: str, scope: str) -> object:
        return self._invoke_collection(
            "update", operation_id=operation_id, scope=scope
        )

    def check_package_updates(self, *, operation_id: str, scope: str) -> object:
        return self._invoke_collection(
            "check", operation_id=operation_id, scope=scope
        )

    def _invoke(self, name: str, *args: object, **kwargs: object) -> object:
        return self._invoke_first((name,), *args, **kwargs)

    def _invoke_first(
        self,
        names: tuple[str, ...],
        *args: object,
        **kwargs: object,
    ) -> object:
        session = self._get_session()
        for owner in (self._runtime, session):
            for name in names:
                method = getattr(owner, name, None)
                if callable(method):
                    return method(*args, **kwargs)
        raise _PackageCapabilityUnavailable

    def _invoke_lifecycle(
        self,
        action: PackageProductLifecycleAction,
        source: str,
        *,
        operation_id: str,
        scope: str,
    ) -> object:
        session = self._get_session()
        executor = getattr(session, "execute_package_lifecycle", None)
        runtime_executor = getattr(self._runtime, "execute_package_lifecycle", None)
        product_owner = self._product_owner(session)
        if product_owner is not None:
            product_executor = getattr(
                product_owner, "execute_package_lifecycle", None
            )
            if (
                not callable(product_executor)
                and product_owner is session
                and getattr(session, "package_product_binding_id", None)
                == getattr(self._runtime, "package_product_binding_id", None)
            ):
                product_executor = runtime_executor
            if not callable(product_executor):
                raise _PackageCapabilityUnavailable
            try:
                result = product_executor(
                    action,
                    source,
                    entrypoint="rpc",
                    operation_id=operation_id,
                    scope=scope,
                )
            except Exception as exc:
                raise _ProductPackageOperationError from exc
            return _resolve_lifecycle(result, product_bound=True)
        if callable(executor):
            return executor(
                action,
                source,
                entrypoint="rpc",
                operation_id=operation_id,
                scope=scope,
            )
        if callable(runtime_executor):
            return runtime_executor(
                action,
                source,
                entrypoint="rpc",
                operation_id=operation_id,
                scope=scope,
            )
        method_names = {
            "materialize": ("materialize_package",),
            "install": ("install_package",),
            "update": ("update_package",),
            "remove": ("remove_package",),
            "uninstall": ("uninstall_package_async", "uninstall_package"),
        }[action]
        return self._invoke_first(method_names, source)

    def _invoke_collection(
        self,
        action: str,
        *,
        operation_id: str,
        scope: str,
    ) -> object:
        session = self._get_session()
        collection = getattr(session, "execute_package_lifecycle_collection", None)
        runtime_collection = getattr(
            self._runtime, "execute_package_lifecycle_collection", None
        )
        product_owner = self._product_owner(session)
        if product_owner is not None:
            product_collection = getattr(
                product_owner, "execute_package_lifecycle_collection", None
            )
            if (
                not callable(product_collection)
                and product_owner is session
                and getattr(session, "package_product_binding_id", None)
                == getattr(self._runtime, "package_product_binding_id", None)
            ):
                product_collection = runtime_collection
            if not callable(product_collection):
                raise _PackageCapabilityUnavailable
            try:
                result = product_collection(
                    action,
                    entrypoint="rpc",
                    operation_id=operation_id,
                    scope=scope,
                )
            except Exception as exc:
                raise _ProductPackageOperationError from exc
            return _resolve_collection(result, product_bound=True)
        if callable(collection):
            return _resolve_collection(
                collection(
                    action,
                    entrypoint="rpc",
                    operation_id=operation_id,
                    scope=scope,
                ),
                product_bound=False,
            )
        if callable(runtime_collection):
            return _resolve_collection(
                runtime_collection(
                    action,
                    entrypoint="rpc",
                    operation_id=operation_id,
                    scope=scope,
                ),
                product_bound=False,
            )
        return _resolve_collection(
            self._invoke(
                "update_packages"
                if action == "update"
                else "check_package_updates"
            ),
            product_bound=False,
        )

    def _product_owner(self, session: object) -> object | None:
        declarations: list[tuple[object, str | None, str]] = []
        for owner in (session, self._runtime):
            mode = getattr(owner, "package_product_lifecycle_mode", "legacy")
            binding = getattr(owner, "package_product_binding_id", None)
            if mode not in {"legacy", "dark", "enforced"}:
                raise _PackageCapabilityUnavailable
            if binding is not None and (not isinstance(binding, str) or not binding):
                raise _PackageCapabilityUnavailable
            if mode == "enforced" and binding is None:
                raise _PackageCapabilityUnavailable
            declarations.append((owner, binding, mode))
        _session_owner, session_binding, _session_mode = declarations[0]
        _runtime_owner, runtime_binding, runtime_mode = declarations[1]
        if session_binding is None:
            if runtime_binding is not None or runtime_mode == "enforced":
                raise _PackageCapabilityUnavailable
            return None
        if runtime_binding is not None and runtime_binding != session_binding:
            raise _PackageCapabilityUnavailable
        # The current Session must explicitly attest every runtime Product
        # executor. A runtime-only declaration cannot bypass Session rollout.
        return session


async def _resolve_collection(
    value: object,
    *,
    product_bound: bool,
) -> _PackageCollectionResult:
    try:
        if inspect.isawaitable(value):
            value = await value
    except Exception as exc:
        if product_bound:
            raise _ProductPackageOperationError from exc
        raise
    return _PackageCollectionResult(value=value, product_bound=product_bound)


async def _resolve_lifecycle(
    value: object,
    *,
    product_bound: bool,
) -> _PackageLifecycleResult:
    try:
        if inspect.isawaitable(value):
            value = await value
    except Exception as exc:
        if product_bound:
            raise _ProductPackageOperationError from exc
        raise
    return _PackageLifecycleResult(value=value, product_bound=product_bound)


@dataclass(frozen=True)
class _LifecycleSpec:
    command: str
    action: PackageProductLifecycleAction
    operation: Callable[[_PackageCapabilities, str, str, str], object]
    unavailable: str
    failure: str
    invalid: str
    failure_code: str
    invalid_code: str


@dataclass(frozen=True)
class _CollectionSpec:
    command: str
    operation: Callable[[_PackageCapabilities, str, str], object]
    data_key: str
    unavailable: str
    failure: str
    invalid: str
    failure_code: str
    invalid_code: str


_LIFECYCLE_SPECS = (
    _LifecycleSpec(
        "materialize_package",
        "materialize",
        lambda capabilities, source, operation_id, scope: (
            capabilities.materialize_package(
                source, operation_id=operation_id, scope=scope
            )
        ),
        "Package materialization is not available.",
        "Failed to materialize package",
        "Package materialization returned an invalid response.",
        "package_materialization_failed",
        "invalid_package_materialization_response",
    ),
    _LifecycleSpec(
        "install_package",
        "install",
        lambda capabilities, source, operation_id, scope: capabilities.install_package(
            source, operation_id=operation_id, scope=scope
        ),
        "Package installation is not available.",
        "Failed to install package",
        "Package installation returned an invalid response.",
        "package_installation_failed",
        "invalid_package_installation_response",
    ),
    _LifecycleSpec(
        "update_package",
        "update",
        lambda capabilities, source, operation_id, scope: capabilities.update_package(
            source, operation_id=operation_id, scope=scope
        ),
        "Package update is not available.",
        "Failed to update package",
        "Package update returned an invalid response.",
        "package_update_failed",
        "invalid_package_update_response",
    ),
    _LifecycleSpec(
        "remove_package",
        "remove",
        lambda capabilities, source, operation_id, scope: capabilities.remove_package(
            source, operation_id=operation_id, scope=scope
        ),
        "Package removal is not available.",
        "Failed to remove package",
        "Package removal returned an invalid response.",
        "package_removal_failed",
        "invalid_package_removal_response",
    ),
    _LifecycleSpec(
        "uninstall_package",
        "uninstall",
        lambda capabilities, source, operation_id, scope: (
            capabilities.uninstall_package(
                source, operation_id=operation_id, scope=scope
            )
        ),
        "Package uninstallation is not available.",
        "Failed to uninstall package",
        "Package uninstallation returned an invalid response.",
        "package_uninstallation_failed",
        "invalid_package_uninstallation_response",
    ),
)

_COLLECTION_SPECS = (
    _CollectionSpec(
        "update_packages",
        lambda capabilities, operation_id, scope: capabilities.update_packages(
            operation_id=operation_id, scope=scope
        ),
        "records",
        "Package update is not available.",
        "Failed to update packages",
        "Package update returned an invalid response.",
        "package_update_failed",
        "invalid_package_update_response",
    ),
    _CollectionSpec(
        "check_package_updates",
        lambda capabilities, operation_id, scope: (
            capabilities.check_package_updates(
                operation_id=operation_id,
                scope=scope,
            )
        ),
        "updates",
        "Package update check is not available.",
        "Failed to check package updates",
        "Package update check returned an invalid response.",
        "package_update_check_failed",
        "invalid_package_update_check_response",
    ),
)


class RpcPackageCommands:
    """Resolve package capabilities from runtime first, then current session."""

    def __init__(
        self,
        *,
        runtime: object,
        get_session: Callable[[], object],
        output: RpcOutput,
    ) -> None:
        self._capabilities: _PackageCapabilities = _DynamicPackageCapabilities(
            runtime=runtime,
            get_session=get_session,
        )
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return (
            ("get_packages", self.get_packages),
            *(
                (spec.command, self._lifecycle_handler(spec))
                for spec in _LIFECYCLE_SPECS
            ),
            *(
                (spec.command, self._collection_handler(spec))
                for spec in _COLLECTION_SPECS
            ),
        )

    def get_packages(self, command_id: str | None, payload: dict[str, Any]) -> None:
        catalog_path = optional_string(payload, "catalogPath", "catalog_path")
        try:
            packages = self._capabilities.get_packages(catalog_path=catalog_path)
        except _PackageCapabilityUnavailable:
            self._output.error(
                request_id=command_id,
                command="get_packages",
                error="Package listing is not available.",
            )
            return
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="get_packages",
                error=f"Failed to query packages: {error}",
                code="package_query_failed",
            )
            return
        if not isinstance(packages, list):
            self._output.error(
                request_id=command_id,
                command="get_packages",
                error="Package listing returned an invalid response.",
                code="invalid_package_query_response",
            )
            return
        self._output.success(
            request_id=command_id,
            command="get_packages",
            data={"packages": packages},
        )

    def _lifecycle_handler(self, spec: _LifecycleSpec) -> LegacyRpcHandler:
        async def handle(command_id: str | None, payload: dict[str, Any]) -> None:
            source = require_string(payload, "source")
            operation_id = _rpc_operation_id(command_id, spec.command)
            try:
                scope = optional_string(payload, "scope") or "project"
                canonicalize_package_product_scope(scope)
                record = spec.operation(
                    self._capabilities,
                    source,
                    operation_id,
                    scope,
                )
                if inspect.isawaitable(record):
                    record = await record
            except _PackageCapabilityUnavailable:
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.unavailable,
                )
                return
            except _ProductPackageOperationError:
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.failure,
                    code=spec.failure_code,
                )
                return
            except Exception as error:
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=f"{spec.failure}: {error}",
                    code=spec.failure_code,
                )
                return
            product_bound = False
            if isinstance(record, _PackageLifecycleResult):
                product_bound = record.product_bound
                record = record.value
            if not isinstance(record, dict):
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.invalid,
                    code=spec.invalid_code,
                )
                return
            if product_bound:
                projected = _validate_product_lifecycle_records(
                    [record],
                    action=spec.action,
                    parent_operation_id=operation_id,
                    collection=False,
                )
                if projected is None:
                    self._output.error(
                        request_id=command_id,
                        command=spec.command,
                        error=spec.invalid,
                        code=spec.invalid_code,
                    )
                    return
                record = projected[0]
            if failure := _lifecycle_failure(record):
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=(
                        spec.failure
                        if product_bound
                        else f"{spec.failure}: {failure}"
                    ),
                    code=spec.failure_code,
                )
                return
            self._output.success(
                request_id=command_id,
                command=spec.command,
                data={"record": record},
            )

        return handle

    def _collection_handler(self, spec: _CollectionSpec) -> LegacyRpcHandler:
        async def handle(command_id: str | None, payload: dict[str, Any]) -> None:
            operation_id = _rpc_operation_id(command_id, spec.command)
            try:
                scope = optional_string(payload, "scope") or "project"
                canonicalize_package_product_scope(scope)
                result = spec.operation(
                    self._capabilities,
                    operation_id,
                    scope,
                )
                if inspect.isawaitable(result):
                    result = await result
            except _PackageCapabilityUnavailable:
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.unavailable,
                )
                return
            except _ProductPackageOperationError:
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.failure,
                    code=spec.failure_code,
                )
                return
            except Exception as error:
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=f"{spec.failure}: {error}",
                    code=spec.failure_code,
                )
                return
            product_bound = False
            if isinstance(result, _PackageCollectionResult):
                product_bound = result.product_bound
                result = result.value
            if not isinstance(result, list):
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.invalid,
                    code=spec.invalid_code,
                )
                return
            if spec.data_key == "updates" and product_bound:
                checked = _validate_product_update_checks(result)
                if checked is None:
                    self._output.error(
                        request_id=command_id,
                        command=spec.command,
                        error=spec.invalid,
                        code=spec.invalid_code,
                    )
                    return
                result = checked
            if spec.data_key == "records" and product_bound:
                projected_records = _validate_product_lifecycle_records(
                    result,
                    action="update",
                    parent_operation_id=operation_id,
                    collection=True,
                )
                if projected_records is None:
                    self._output.error(
                        request_id=command_id,
                        command=spec.command,
                        error=spec.invalid,
                        code=spec.invalid_code,
                    )
                    return
                result = projected_records
            if spec.data_key == "records" and any(
                isinstance(record, dict) and _lifecycle_failure(record) is not None
                for record in result
            ):
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.failure,
                    code=spec.failure_code,
                )
                return
            self._output.success(
                request_id=command_id,
                command=spec.command,
                data={spec.data_key: result},
            )

        return handle


def _rpc_operation_id(command_id: str | None, command: str) -> str:
    if command_id is None:
        return uuid4().hex
    return sha256(f"rpc:{command}:{command_id}".encode()).hexdigest()


def _lifecycle_failure(record: dict[str, Any]) -> str | None:
    if record.get("lifecycle") != "failed":
        return None
    message = record.get("errorMessage", record.get("error_message"))
    return (
        str(message)
        if isinstance(message, str) and message
        else "Package lifecycle failed."
    )


def _validate_product_update_checks(
    value: list[object],
) -> list[dict[str, object]] | None:
    checked: list[dict[str, object]] = []
    expected_fields = {
        "checkVersion",
        "errorCode",
        "name",
        "scope",
        "source",
        "updateAvailable",
    }
    for item in value:
        if not isinstance(item, dict) or set(item) != expected_fields:
            return None
        source = item["source"]
        scope = item["scope"]
        available = item["updateAvailable"]
        error_code = item["errorCode"]
        if (
            type(item["checkVersion"]) is not int
            or item["checkVersion"] != PACKAGE_PRODUCT_UPDATE_CHECK_VERSION
            or not isinstance(source, str)
            or not isinstance(scope, str)
            or type(available) is not bool
            or error_code not in {"", "package_update_check_failed"}
        ):
            return None
        try:
            projected = PackageProductUpdateCheckV1(
                target_ref=source,
                scope=scope,
                update_available=available,
                failure_code=(None if error_code == "" else "failed"),
            ).to_dict()
        except (TypeError, ValueError):
            return None
        if item != projected:
            return None
        checked.append(projected)
    return checked


def _validate_product_lifecycle_records(
    value: Sequence[object],
    *,
    action: PackageProductLifecycleAction,
    parent_operation_id: str,
    collection: bool,
) -> list[dict[str, object]] | None:
    records: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        if item.get("kind") == "plugin_package":
            projected = _validate_plugin_lifecycle_record(
                item,
                action=action,
                parent_operation_id=parent_operation_id,
                collection=collection,
            )
        else:
            projected = _project_non_plugin_lifecycle_record(
                item,
                action=action,
                parent_operation_id=parent_operation_id,
                collection=collection,
            )
        if projected is None:
            return None
        records.append(projected)
    return records


def _validate_plugin_lifecycle_record(
    item: dict[str, object],
    *,
    action: PackageProductLifecycleAction,
    parent_operation_id: str,
    collection: bool,
) -> dict[str, object] | None:
    fields = {
        "action",
        "errorCode",
        "errorMessage",
        "kind",
        "lifecycle",
        "name",
        "operationId",
        "packageLifecycleDisposition",
        "packageLifecyclePhase",
        "path",
        "recordVersion",
        "source",
    }
    if set(item) != fields or item["action"] != action or item["path"] != "":
        return None
    source = item["source"]
    operation_id = item["operationId"]
    error_code = item["errorCode"]
    if (
        not isinstance(source, str)
        or not isinstance(operation_id, str)
        or not isinstance(error_code, str)
        or item["errorMessage"] != error_code
        or (
            error_code
            and error_code not in PACKAGE_PRODUCT_LIFECYCLE_FAILURE_CODES
        )
    ):
        return None
    expected_name = (
        f"plugin-{source.removeprefix('sha256:')[:12]}"
        if source.startswith("sha256:")
        else ""
    )
    if item["name"] != expected_name:
        return None
    expected_operation_id = (
        sha256(f"{parent_operation_id}\0{source}".encode()).hexdigest()
        if collection
        else parent_operation_id
    )
    if operation_id != expected_operation_id:
        return None
    try:
        record = PackageProductLifecycleRecordV1(
            operation_id=operation_id,
            action=action,
            source_identity=source,
            name=item["name"],  # type: ignore[arg-type]
            lifecycle=item["lifecycle"],  # type: ignore[arg-type]
            phase=item["packageLifecyclePhase"],  # type: ignore[arg-type]
            disposition=item["packageLifecycleDisposition"],  # type: ignore[arg-type]
            failure_code=error_code or None,
            record_version=item["recordVersion"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError):
        return None
    projected = record.to_dict()
    return projected if item == projected else None


def _project_non_plugin_lifecycle_record(
    item: dict[str, object],
    *,
    action: PackageProductLifecycleAction,
    parent_operation_id: str,
    collection: bool,
) -> dict[str, object] | None:
    legacy_fields = {
        "dirty",
        "errorMessage",
        "installedCommit",
        "installedDistributions",
        "installer",
        "lastUpdatedAt",
        "lifecycle",
        "name",
        "pinned",
        "requestedRef",
        "requirement",
        "resolvedCommit",
        "resolvedName",
        "resolvedVersion",
        "security",
        "source",
        "sourceType",
        "targetPath",
    }
    source = item.get("source")
    lifecycle = item.get("lifecycle")
    if (
        set(item) != legacy_fields
        or not isinstance(source, str)
        or not source
        or lifecycle not in {"installed", "remote_registered", "failed"}
    ):
        return None
    source_ref = f"sha256:{sha256(source.encode()).hexdigest()}"
    operation_id = (
        sha256(f"{parent_operation_id}\0{source_ref}".encode()).hexdigest()
        if collection
        else parent_operation_id
    )
    failed = lifecycle == "failed"
    return {
        "action": action,
        "errorCode": "package_non_plugin_operation_failed" if failed else "",
        "errorMessage": "package_non_plugin_operation_failed" if failed else "",
        "kind": "non_plugin_package",
        "lifecycle": lifecycle,
        "name": f"package-{source_ref.removeprefix('sha256:')[:12]}",
        "operationId": operation_id,
        "path": "",
        "recordVersion": 1,
        "source": source_ref,
    }


__all__ = ["RpcPackageCommands"]
