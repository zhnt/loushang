"""Shared asynchronous package lifecycle command orchestration."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


class PackageLifecycleError(RuntimeError):
    """Raised when a package lifecycle operation cannot be completed."""

    def __init__(
        self,
        message: str,
        *,
        outputs: tuple[dict[str, object], ...] = (),
    ) -> None:
        super().__init__(message)
        self.outputs = outputs


@dataclass(frozen=True, slots=True)
class PackageLifecycleRequest:
    """Product-neutral package lifecycle inputs."""

    install: tuple[str, ...] = ()
    materialize: tuple[str, ...] = ()
    update: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()
    uninstall: tuple[str, ...] = ()
    check_updates: bool = False
    update_all: bool = False
    scope: str = "global"

    @property
    def has_operations(self) -> bool:
        return bool(
            self.install
            or self.materialize
            or self.update
            or self.remove
            or self.uninstall
            or self.check_updates
            or self.update_all
        )


@dataclass(frozen=True, slots=True)
class PackageLifecycleResult:
    """Structured operation outputs; a Product chooses the wire formatter."""

    outputs: tuple[dict[str, object], ...] = ()


async def run_package_lifecycle(
    session: object,
    request: PackageLifecycleRequest,
    *,
    evaluate_install_source: Callable[[str], str | None] | None = None,
    on_policy_denied: Callable[[str, str | None], None] | None = None,
) -> PackageLifecycleResult:
    """Run package operations against an injected session capability.

    The runtime owns operation ordering and error semantics. Product code owns
    source policy and serializes the returned output records.
    """

    outputs: list[dict[str, object]] = []

    for source in request.install:
        if evaluate_install_source is not None:
            reason = evaluate_install_source(source)
            if reason is not None:
                if on_policy_denied is not None:
                    on_policy_denied(source, reason)
                raise PackageLifecycleError(reason, outputs=tuple(outputs))
        record = await _invoke_source_operation(
            session,
            command="install_package",
            source=source,
            scope=request.scope,
            outputs=outputs,
        )
        outputs.append(_record_output("install_package", record, outputs=outputs))

    for command, method_name in (
        ("check_package_updates", "check_package_updates"),
        ("update_packages", "update_packages"),
    ):
        if (command == "check_package_updates" and not request.check_updates) or (
            command == "update_packages" and not request.update_all
        ):
            continue
        records = await _invoke_operation(
            session, command=method_name, outputs=outputs
        )
        if command == "update_packages" and isinstance(records, list):
            _raise_for_failed_records(records, outputs=outputs)
        outputs.append({"command": command, "records": records})

    for command, sources in (
        ("materialize_package", request.materialize),
        ("update_package", request.update),
        ("remove_package", request.remove),
        ("uninstall_package", request.uninstall),
    ):
        for source in sources:
            record = await _invoke_source_operation(
                session,
                command=command,
                source=source,
                scope=request.scope if command == "uninstall_package" else None,
                outputs=outputs,
            )
            outputs.append(_record_output(command, record, outputs=outputs))

    return PackageLifecycleResult(tuple(outputs))


async def _invoke_source_operation(
    session: object,
    *,
    command: str,
    source: str,
    scope: str | None,
    outputs: Sequence[dict[str, object]],
) -> object:
    try:
        method = _require_method(session, command)
        result = method(source, scope=scope) if scope is not None else method(source)
        if inspect.isawaitable(result):
            return await result
    except PackageLifecycleError as error:
        error = PackageLifecycleError(str(error), outputs=tuple(outputs))
        raise error from None
    except Exception as error:
        raise PackageLifecycleError(str(error), outputs=tuple(outputs)) from error
    return result


async def _invoke_operation(
    session: object,
    *,
    command: str,
    outputs: Sequence[dict[str, object]],
) -> object:
    try:
        method = _require_method(session, command)
        result = method()
        if inspect.isawaitable(result):
            return await result
    except PackageLifecycleError as error:
        error = PackageLifecycleError(str(error), outputs=tuple(outputs))
        raise error from None
    except Exception as error:
        raise PackageLifecycleError(str(error), outputs=tuple(outputs)) from error
    return result


def _require_method(session: object, command: str) -> Callable[..., object]:
    method = getattr(session, command, None)
    if not callable(method):
        raise PackageLifecycleError(f"{command} is not available.")
    return method


def _record_output(
    command: str,
    record: object,
    *,
    outputs: Sequence[dict[str, object]],
) -> dict[str, object]:
    failure = package_lifecycle_failure(record)
    if failure is not None:
        raise PackageLifecycleError(failure, outputs=tuple(outputs))
    return {"command": command, "record": record}


def _raise_for_failed_records(
    records: Sequence[object], *, outputs: list[dict[str, object]]
) -> None:
    for record in records:
        failure = package_lifecycle_failure(record)
        if failure is not None:
            raise PackageLifecycleError(failure, outputs=tuple(outputs))


def package_lifecycle_failure(record: object) -> str | None:
    """Return a stable message for a failed lifecycle record, if present."""

    if not isinstance(record, Mapping) or record.get("lifecycle") != "failed":
        return None
    message = record.get("errorMessage", record.get("error_message"))
    return (
        str(message)
        if isinstance(message, str) and message
        else "Package lifecycle failed."
    )


__all__ = [
    "PackageLifecycleError",
    "PackageLifecycleRequest",
    "PackageLifecycleResult",
    "package_lifecycle_failure",
    "run_package_lifecycle",
]
