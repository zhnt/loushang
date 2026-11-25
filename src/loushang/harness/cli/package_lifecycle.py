"""Shared Package lifecycle and standalone operator command execution."""

from __future__ import annotations

import inspect
import json
import re
import secrets
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from functools import partial
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, TextIO, TypeVar
from uuid import uuid4

from loushang.foundation.json import _unique_json_object_hook
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleAction,
    PackageProductLifecycleRecordV1,
    canonicalize_package_product_scope,
)
from loushang.harness.workspace.paths import require_workspace_directory

if TYPE_CHECKING:
    from loushang.harness.package_product._application_runtime import (
        FencedOrdinaryProductApplication,
        FencedProductManagementApplication,
        PackageChangeFailureEvidence,
        PackageRemovalFailureEvidence,
    )
    from loushang.harness.plugin_management.application import (
        PluginManagementInstallationViewV1,
    )
    from loushang.harness.plugin_management.desired_command import (
        PluginDesiredCommandAuthorityV1,
    )

_OPERATOR_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{1,127}\Z")
_RecordT = TypeVar("_RecordT")

PRIVATE_DATA_ACCESS_ACTIONS = frozenset({
    "preview", "backup", "backup-status", "backup-verify",
    "restore-preview", "backup-expiry-preview",
})


def add_private_data_operator_commands(
    parser: ArgumentParser, *, installation_name: str
) -> None:
    commands = parser.add_subparsers(dest="action", required=True)
    for action, help_text, required in (
        ("preview", "read exact Installation deletion target", ()),
        ("backup", "retain a verified Installation backup", ()),
        ("backup-status", "read verified backup retention", ()),
        ("backup-verify", "verify one exact backup", ("--backup-id",)),
        ("backup-expiry-preview", "read an exact, confirmed restore-backed backup expiry plan",
         ("--backup-id", "--confirmation-id")),
        ("backup-expiry-confirm", "confirm one exact backup expiry plan",
         ("--plan-file", "--accept-fingerprint")),
        ("backup-expire", f"expire only a separately confirmed {installation_name} backup",
         ("--plan-file", "--confirmation-file")),
        ("restore-preview", "read one exact, offline backup restore plan", ("--backup-id",)),
        ("restore", "restore only a previewed, accepted backup into absent data",
         ("--plan-file", "--accept-fingerprint")),
        ("restore-confirm", f"confirm one completed and verified {installation_name} restore",
         ("--backup-id",)),
        ("restore-confirm-verify", "reopen one exact restore confirmation",
         ("--backup-id", "--confirmation-id")),
        ("confirm", "separately confirm one unchanged preview fingerprint",
         ("--plan-file", "--accept-fingerprint")),
        ("delete", "delete only the separately confirmed, removed Installation",
         ("--plan-file", "--confirmation-file")),
    ):
        command = commands.add_parser(action, help=help_text)
        for option in required:
            command.add_argument(option, required=True)
        if action in {"restore-confirm", "restore-confirm-verify"}:
            command.add_argument("--plan-file")


class _PrivateDataRecord(Protocol):
    def to_dict(self) -> dict[str, object]: ...


class _PrivateDataPlan(_PrivateDataRecord, Protocol):
    @property
    def fingerprint(self) -> str: ...


class _PrivateDataAccess(Protocol):
    def status(self) -> _PrivateDataRecord: ...
    def retain(self) -> _PrivateDataRecord: ...
    def verify(self, backup_id: str, /) -> _PrivateDataRecord: ...
    def deletion_preview(self) -> _PrivateDataPlan: ...
    def restore_preview(self, backup_id: str, /) -> _PrivateDataPlan: ...
    def backup_expiry_preview(self, backup_id: str, confirmation_id: str, /) -> _PrivateDataPlan: ...


def run_private_data_access(
    client: _PrivateDataAccess, args: Namespace
) -> dict[str, object]:
    """Use the supplied Product client and the existing operator record shapes."""
    action = args.action
    if action == "preview":
        field, plan = "plan", client.deletion_preview()
    elif action == "backup-status":
        return {"backupRetention": client.status().to_dict()}
    elif action == "backup":
        return {"backupReceipt": client.retain().to_dict()}
    elif action == "backup-verify":
        return {"backupReceipt": client.verify(args.backup_id).to_dict()}
    elif action == "restore-preview":
        field, plan = "restorePlan", client.restore_preview(args.backup_id)
    elif action == "backup-expiry-preview":
        plan = client.backup_expiry_preview(args.backup_id, args.confirmation_id)
        return {"backupExpiryPlan": plan.to_dict(), "fingerprint": plan.fingerprint}
    else:
        raise ValueError("private-data access command is invalid")
    return {"fingerprint": plan.fingerprint, field: plan.to_dict()}


def run_private_data_expiry(
    args: Namespace,
    plan: _PrivateDataPlan,
    *,
    confirm: Callable[[], _PrivateDataRecord],
    expire: Callable[[Path], _PrivateDataRecord],
    refused: str,
) -> dict[str, object]:
    """Require explicit acceptance for confirmation and read a separate record for expiry."""
    if args.action == "backup-expiry-confirm":
        if args.accept_fingerprint != plan.fingerprint:
            raise ValueError(refused)
        return {"expiryConfirmation": confirm().to_dict()}
    return {"expiryReceipt": expire(Path(args.confirmation_file)).to_dict()}


def package_operator_workspace(value: str, *, not_directory: str) -> Path:
    return require_workspace_directory(value, unavailable=not_directory)


def package_operator_error_code(error: Exception, *, fallback: str) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and _OPERATOR_ERROR_CODE.fullmatch(code) is not None:
        return code
    return fallback


def write_package_operator_result(
    document: dict[str, object],
    *,
    compact: bool = False,
    stream: TextIO | None = None,
    ensure_ascii: bool = True,
    sort_keys: bool = True,
) -> int:
    encoded = json.dumps(
        document,
        ensure_ascii=ensure_ascii,
        sort_keys=sort_keys,
        separators=(",", ":") if compact else None,
    )
    output = sys.stdout if stream is None else stream
    output.write(encoded + "\n")
    return 0


@dataclass(frozen=True, slots=True)
class PackageOperatorRecordInput:
    """Read a bounded command document and verify its embedded record."""

    label: str
    maximum_bytes: int

    def read(
        self,
        path: Path,
        field: str,
        decode: Callable[[object], _RecordT],
        *,
        label: str,
        fingerprint: Callable[[_RecordT], str] | None = None,
    ) -> _RecordT:
        with path.open("rb") as handle:
            raw = handle.read(self.maximum_bytes + 1)
        if len(raw) > self.maximum_bytes:
            raise ValueError(f"{self.label} input is too large")
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object_hook(
                lambda: f"{self.label} has duplicate JSON keys"
            ),
        )
        expected = {field} if fingerprint is None else {field, "fingerprint"}
        if type(document) is not dict or set(document) != expected:
            raise ValueError(f"{label} document is invalid")
        record = decode(document[field])
        if fingerprint is not None and document["fingerprint"] != fingerprint(record):
            raise ValueError(f"{label} fingerprint changed")
        return record


def run_package_operator_command(
    workspace: str,
    execute: Callable[[Path], dict[str, object]],
    *,
    not_directory: str,
    refused: str,
    failure_reason: Callable[[Exception], object] | str,
    compact: bool = False,
) -> int:
    """Resolve and execute one admitted command with its Product's output contract."""
    try:
        resolved = package_operator_workspace(workspace, not_directory=not_directory)
        document = execute(resolved)
    except (OSError, RuntimeError, ValueError, PackageNotFoundError) as error:
        reason = failure_reason(error) if callable(failure_reason) else failure_reason
        sys.stderr.write(f"{refused}: {reason}\n")
        return 1
    return write_package_operator_result(document, compact=compact)


class _AdmittedPackageWheel(Protocol):
    @property
    def wheel_filename(self) -> str: ...

    @property
    def plugin_id(self) -> str: ...

    @property
    def artifact_digest(self) -> str: ...


def run_fenced_package_changes(
    sources: Sequence[str],
    *,
    action: Literal["install", "update"],
    admit_source: Callable[[Path], _AdmittedPackageWheel],
    open_application: Callable[[], FencedOrdinaryProductApplication],
    management: FencedProductManagementApplication,
    product_id: str,
    operation_prefix: str,
    runtime_prefix: str,
    output: FencedPackageOperatorOutput,
) -> int:
    """Admit the batch, then settle each routed operation within its own runtime."""
    from loushang.harness.package_product._plugin_bootstrap import route_project_package
    from loushang.harness.package_product.product_runtime import (
        hold_local_wheel_product_runtime,
    )

    operation_id: str | None = None
    try:
        admitted = tuple(admit_source(Path(raw)) for raw in sources)
        with closing(open_application()) as owner:
            product = owner.runtime_owner.product_owner
            for wheel in admitted:
                operation_id = f"{operation_prefix}{action}:{secrets.token_hex(16)}"
                with hold_local_wheel_product_runtime(
                    product,
                    product_id=product_id,
                    session_id=f"{runtime_prefix}{secrets.token_hex(16)}",
                ) as runtime:
                    outcome = route_project_package(
                        runtime,
                        operation_id=operation_id,
                        action=action,
                        source=str(
                            owner.epoch_runtime.control_root
                            / "product-sources"
                            / wheel.wheel_filename
                        ),
                        entrypoint="cli",
                    )
                record = outcome.record
                if not outcome.handled or record is None:
                    raise RuntimeError(f"Package Product {action} was not handled")
                if record.lifecycle == "failed":
                    output.package_failure(
                        operation_id,
                        record.failure_code or "package_operation_failed",
                        management.observe_package_change_failure(operation_id),
                    )
                    return 1
                output.package_success(action, wheel, record)
            return 0
    except (OSError, RuntimeError, ValueError) as error:
        if operation_id is None:
            output.unstarted(error)
        else:
            output.package_failure(
                operation_id,
                package_operator_error_code(error, fallback="package_operation_incomplete"),
                management.observe_package_change_failure(operation_id),
            )
        return 1


@dataclass(frozen=True, slots=True)
class FencedPackageOperatorOutput:
    """Render the Package and Desired State owner evidence used by the CLI."""

    program: str
    explain_command: tuple[str, ...]
    repair_handoff_command: tuple[str, ...]
    repair_desired_command: tuple[str, ...]
    gc_command: tuple[str, ...]
    stdout: TextIO
    stderr: TextIO

    def _list_plugins(self) -> list[str]:
        return [self.program, "--list-plugins", "--list-plugins-format", "json"]

    def _write(
        self, document: dict[str, object], *, failure: bool = False, sort_keys: bool = False
    ) -> None:
        write_package_operator_result(
            document,
            stream=self.stderr if failure else self.stdout,
            ensure_ascii=False,
            sort_keys=sort_keys,
        )

    def unstarted(self, error: BaseException) -> None:
        self.stderr.write(f"Error: {error}\n")

    def package_success(
        self,
        action: Literal["install", "update"],
        wheel: _AdmittedPackageWheel,
        record: PackageProductLifecycleRecordV1,
    ) -> None:
        next_commands = [
            " ".join(self._list_plugins()),
            " ".join((*self.explain_command, record.operation_id)),
        ]
        if action == "install":
            next_commands.insert(0, f"{self.program} --enable-plugin {wheel.plugin_id}")
        self._write(
            {
                "command": f"{action}_package",
                "operationKind": "A2",
                "pluginId": wheel.plugin_id,
                "sourceSha256": wheel.artifact_digest,
                "stage": "package_operation_recorded",
                "record": record.to_dict(),
                "nextCommands": next_commands,
            }
        )

    def package_failure(
        self,
        operation_id: str,
        error_code: str,
        evidence: PackageChangeFailureEvidence,
    ) -> None:
        next_commands = [[*self.explain_command, operation_id], self._list_plugins()]
        if evidence.stage == "desired_committed":
            next_commands.append([*self.repair_handoff_command, operation_id])
        self.stderr.write(f"Error: {error_code} (Package operation: {operation_id})\n")
        self._write(
            {
                "operationKind": "A2",
                "operationId": operation_id,
                "stage": evidence.stage,
                "desiredInventoryRevision": evidence.desired_inventory_revision,
                "committedRevision": evidence.committed_revision,
                "handoffReceiptId": evidence.handoff_receipt_id,
                "handoffEvidence": evidence.handoff_evidence,
                "joinStatus": evidence.join_status,
                "nextCommands": next_commands,
            },
            failure=True,
            sort_keys=True,
        )

    def removal_success(
        self,
        plugin_id: str,
        operation_id: str,
        installed: PluginManagementInstallationViewV1 | None,
    ) -> None:
        self._write(
            {
                "command": "uninstall_package",
                "operationKind": "A1",
                "stage": "desired_absent",
                "retirementStatus": (
                    {
                        "evidence": "observed",
                        "retirementStates": list(installed.retirement_states),
                        "cleanupDebtIds": list(installed.cleanup_debt_ids),
                        "unknownDimensions": list(installed.unknown_dimensions),
                    }
                    if installed is not None
                    else {"evidence": "not_checked"}
                ),
                "gcStatus": "not_checked",
                "nextCommands": [self._list_plugins()],
                "gcStatusCommand": [*self.gc_command, "list"],
                "gcPrepareCommand": [*self.gc_command, "prepare"],
                "gcStatusPrerequisite": "close_active_sessions_and_prepare_gc",
                "record": {
                    "pluginId": plugin_id,
                    "desiredState": "absent",
                    "operationId": operation_id,
                },
            }
        )

    def removal_failure(
        self,
        operation_id: str,
        evidence: PackageRemovalFailureEvidence,
        *,
        expected_actor_id: str,
    ) -> None:
        next_commands = [[*self.explain_command, operation_id], self._list_plugins()]
        if evidence.pending_operation and evidence.actor_id == expected_actor_id:
            next_commands.append([*self.repair_desired_command, operation_id])
        committed = evidence.committed_revision is not None
        self.stderr.write(
            f"Error: plugin_uninstall_incomplete (Desired operation: {operation_id})\n"
        )
        self._write(
            {
                "operationKind": "A1",
                "operationId": operation_id,
                "actorId": evidence.actor_id,
                "operationStatus": evidence.operation_status,
                "stage": "desired_absent" if committed else "unknown",
                "desiredInventoryRevision": evidence.committed_revision,
                "retirementEvidence": (
                    "incomplete" if committed and evidence.pending_operation else "not_checked"
                ),
                "nextCommands": next_commands,
            },
            failure=True,
        )


def run_fenced_package_removals(
    plugin_ids: Sequence[str],
    *,
    application: FencedProductManagementApplication,
    authority: PluginDesiredCommandAuthorityV1,
    max_attempts: int,
    operation_id_for_revision: Callable[[str, int], str],
    output: FencedPackageOperatorOutput,
) -> int:
    """Remove each exact selection and report any surviving operation evidence."""
    from loushang.harness.plugin_management.application import PluginManagementQueryV1
    from loushang.harness.plugin_management.desired_command import (
        PluginPackageRemovalAttempt,
        remove_installed_plugin_package,
    )

    ports = application.bind_ports()
    attempt = PluginPackageRemovalAttempt()
    try:
        for plugin_id in plugin_ids:
            attempt = PluginPackageRemovalAttempt()
            correlation_id = f"cli:uninstall-package:{plugin_id}"
            installed = remove_installed_plugin_package(
                ports,
                attempt,
                query=PluginManagementQueryV1(
                    correlation_id=f"{correlation_id}:query",
                    product_id=authority.product_id,
                    installation_scope=authority.installation_scope,
                    scope_id=authority.scope_id,
                    plugin_ids=(plugin_id,),
                ),
                correlation_id=correlation_id,
                actor_id=authority.actor_id,
                policy_revision=authority.policy_revision,
                max_attempts=max_attempts,
                operation_id_for_revision=partial(operation_id_for_revision, plugin_id),
            )
            assert attempt.operation_id is not None
            output.removal_success(plugin_id, attempt.operation_id, installed)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        operation_id = attempt.operation_id
        if operation_id is None:
            output.unstarted(error)
        else:
            evidence = application.observe_package_removal_failure(
                ports, operation_id, pending_operation=attempt.pending
            )
            output.removal_failure(
                operation_id, evidence, expected_actor_id=authority.actor_id
            )
        return 1


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
            session,
            command=method_name,
            scope=request.scope,
            outputs=outputs,
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
                scope=request.scope,
                outputs=outputs,
            )
            outputs.append(_record_output(command, record, outputs=outputs))

    return PackageLifecycleResult(tuple(outputs))


async def _invoke_source_operation(
    session: object,
    *,
    command: str,
    source: str,
    scope: str,
    outputs: Sequence[dict[str, object]],
) -> object:
    try:
        product_route_required = _product_route_required(session)
        executor = getattr(session, "execute_package_lifecycle", None)
        if product_route_required and not callable(executor):
            raise PackageLifecycleError("Package Product lifecycle executor is unavailable")
        if callable(executor):
            action = _lifecycle_action(command)
            canonicalize_package_product_scope(scope)
            result = executor(
                action,
                source,
                entrypoint="cli",
                operation_id=uuid4().hex,
                scope=scope,
            )
        else:
            method = _require_method(
                session,
                "uninstall_package_async"
                if command == "uninstall_package"
                else command,
                fallback=command if command == "uninstall_package" else None,
            )
            result = (
                method(source, scope=scope)
                if command in {"install_package", "uninstall_package"}
                else method(source)
            )
        if inspect.isawaitable(result):
            return await result
    except PackageLifecycleError as error:
        error = PackageLifecycleError(str(error), outputs=tuple(outputs))
        raise error from None
    except Exception as error:
        raise PackageLifecycleError(str(error), outputs=tuple(outputs)) from error
    return result


def _lifecycle_action(command: str) -> PackageProductLifecycleAction:
    actions: dict[str, PackageProductLifecycleAction] = {
        "install_package": "install",
        "materialize_package": "materialize",
        "update_package": "update",
        "remove_package": "remove",
        "uninstall_package": "uninstall",
    }
    try:
        return actions[command]
    except KeyError as exc:
        raise PackageLifecycleError(
            f"Unsupported Package lifecycle command: {command}"
        ) from exc


def _product_route_required(session: object) -> bool:
    mode = getattr(session, "package_product_lifecycle_mode", "legacy")
    binding = getattr(session, "package_product_binding_id", None)
    if (
        mode not in {"legacy", "dark", "enforced"}
        or (binding is not None and (not isinstance(binding, str) or not binding))
        or (mode == "enforced" and binding is None)
    ):
        raise PackageLifecycleError("Package Product lifecycle executor is unavailable")
    return binding is not None


async def _invoke_operation(
    session: object,
    *,
    command: str,
    scope: str,
    outputs: Sequence[dict[str, object]],
) -> object:
    try:
        product_route_required = _product_route_required(session)
        collection = getattr(session, "execute_package_lifecycle_collection", None)
        if product_route_required and not callable(collection):
            raise PackageLifecycleError("Package Product collection executor is unavailable")
        if command in {"update_packages", "check_package_updates"} and callable(
            collection
        ):
            canonicalize_package_product_scope(scope)
            result = collection(
                "update" if command == "update_packages" else "check",
                entrypoint="cli",
                operation_id=uuid4().hex,
                scope=scope,
            )
        else:
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


def _require_method(
    session: object,
    command: str,
    *,
    fallback: str | None = None,
) -> Callable[..., object]:
    method = getattr(session, command, None)
    if not callable(method) and fallback is not None:
        method = getattr(session, fallback, None)
    if not callable(method):
        exposed_name = fallback or command
        raise PackageLifecycleError(f"{exposed_name} is not available.")
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
