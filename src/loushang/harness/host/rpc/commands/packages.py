"""Package inventory and lifecycle commands for the shared RPC host."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from loushang.harness.host.rpc.arguments import optional_string, require_string
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler


class _PackageCapabilityUnavailable(RuntimeError):
    pass


class _PackageCapabilities(Protocol):
    """Semantic package capabilities consumed by this command group."""

    def get_packages(self, *, catalog_path: str | None) -> object: ...

    def materialize_package(self, source: str) -> object: ...

    def install_package(self, source: str) -> object: ...

    def update_package(self, source: str) -> object: ...

    def remove_package(self, source: str) -> object: ...

    def uninstall_package(self, source: str) -> object: ...

    def update_packages(self) -> object: ...

    def check_package_updates(self) -> object: ...


class _DynamicPackageCapabilities:
    """Resolve optional Product package operations at the invocation boundary."""

    def __init__(
        self, *, runtime: object, get_session: Callable[[], object]
    ) -> None:
        self._runtime = runtime
        self._get_session = get_session

    def get_packages(self, *, catalog_path: str | None) -> object:
        return self._invoke("get_packages", catalog_path=catalog_path)

    def materialize_package(self, source: str) -> object:
        return self._invoke("materialize_package", source)

    def install_package(self, source: str) -> object:
        return self._invoke("install_package", source)

    def update_package(self, source: str) -> object:
        return self._invoke("update_package", source)

    def remove_package(self, source: str) -> object:
        return self._invoke("remove_package", source)

    def uninstall_package(self, source: str) -> object:
        return self._invoke("uninstall_package", source)

    def update_packages(self) -> object:
        return self._invoke("update_packages")

    def check_package_updates(self) -> object:
        return self._invoke("check_package_updates")

    def _invoke(self, name: str, *args: object, **kwargs: object) -> object:
        method = getattr(self._runtime, name, None)
        if not callable(method):
            method = getattr(self._get_session(), name, None)
        if not callable(method):
            raise _PackageCapabilityUnavailable
        return method(*args, **kwargs)


@dataclass(frozen=True)
class _LifecycleSpec:
    command: str
    operation: Callable[[_PackageCapabilities, str], object]
    unavailable: str
    failure: str
    invalid: str
    failure_code: str
    invalid_code: str


@dataclass(frozen=True)
class _CollectionSpec:
    command: str
    operation: Callable[[_PackageCapabilities], object]
    data_key: str
    unavailable: str
    failure: str
    invalid: str
    failure_code: str
    invalid_code: str


_LIFECYCLE_SPECS = (
    _LifecycleSpec(
        "materialize_package",
        lambda capabilities, source: capabilities.materialize_package(source),
        "Package materialization is not available.",
        "Failed to materialize package",
        "Package materialization returned an invalid response.",
        "package_materialization_failed",
        "invalid_package_materialization_response",
    ),
    _LifecycleSpec(
        "install_package",
        lambda capabilities, source: capabilities.install_package(source),
        "Package installation is not available.",
        "Failed to install package",
        "Package installation returned an invalid response.",
        "package_installation_failed",
        "invalid_package_installation_response",
    ),
    _LifecycleSpec(
        "update_package",
        lambda capabilities, source: capabilities.update_package(source),
        "Package update is not available.",
        "Failed to update package",
        "Package update returned an invalid response.",
        "package_update_failed",
        "invalid_package_update_response",
    ),
    _LifecycleSpec(
        "remove_package",
        lambda capabilities, source: capabilities.remove_package(source),
        "Package removal is not available.",
        "Failed to remove package",
        "Package removal returned an invalid response.",
        "package_removal_failed",
        "invalid_package_removal_response",
    ),
    _LifecycleSpec(
        "uninstall_package",
        lambda capabilities, source: capabilities.uninstall_package(source),
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
        lambda capabilities: capabilities.update_packages(),
        "records",
        "Package update is not available.",
        "Failed to update packages",
        "Package update returned an invalid response.",
        "package_update_failed",
        "invalid_package_update_response",
    ),
    _CollectionSpec(
        "check_package_updates",
        lambda capabilities: capabilities.check_package_updates(),
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

    def get_packages(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
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
        async def handle(
            command_id: str | None, payload: dict[str, Any]
        ) -> None:
            source = require_string(payload, "source")
            try:
                record = spec.operation(self._capabilities, source)
                if inspect.isawaitable(record):
                    record = await record
            except _PackageCapabilityUnavailable:
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.unavailable,
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
            if not isinstance(record, dict):
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.invalid,
                    code=spec.invalid_code,
                )
                return
            if failure := _lifecycle_failure(record):
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=f"{spec.failure}: {failure}",
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
        async def handle(
            command_id: str | None, payload: dict[str, Any]
        ) -> None:
            del payload
            try:
                result = spec.operation(self._capabilities)
                if inspect.isawaitable(result):
                    result = await result
            except _PackageCapabilityUnavailable:
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.unavailable,
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
            if not isinstance(result, list):
                self._output.error(
                    request_id=command_id,
                    command=spec.command,
                    error=spec.invalid,
                    code=spec.invalid_code,
                )
                return
            self._output.success(
                request_id=command_id,
                command=spec.command,
                data={spec.data_key: result},
            )

        return handle


def _lifecycle_failure(record: dict[str, Any]) -> str | None:
    if record.get("lifecycle") != "failed":
        return None
    message = record.get("errorMessage", record.get("error_message"))
    return (
        str(message)
        if isinstance(message, str) and message
        else "Package lifecycle failed."
    )


__all__ = ["RpcPackageCommands"]
