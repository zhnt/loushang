"""Coding policy bound to the shared HarnessTUI conversation components."""

from __future__ import annotations

import asyncio
import inspect
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO, cast

from loushang.ai.types import ImagePart
from loushang.coding.diagnostics.debug_status import debug_status_text
from loushang.coding.package_product_repair_ui import (
    execute_coding_package_repair_ui_command,
)
from loushang.coding.plugin_management_read_sdk import (
    open_coding_plugin_management_read_client,
)
from loushang.coding.plugin_management_ui import (
    execute_coding_plugin_management_ui_command,
)
from loushang.foundation.observability import get_log
from loushang.harness.commands import CommandEffectKind
from loushang.harness.host.types import HostActionResult
from loushang.harness.session import (
    SessionControlPort,
    SessionOperationAvailability,
    SessionOperationResolver,
    current_session_operation_resolver,
    require_active_session,
    session_operation_resolver,
)
from loushang.harnesstui.commands.catalog import ConversationCommandCatalog
from loushang.harnesstui.conversation.action_presentation import (
    ConversationActionPresentationPort,
    PresentedConversationActionHost,
    build_standard_presented_conversation_action_host,
)
from loushang.harnesstui.conversation.agent_binding import (
    agent_image_parts_from_prompt_attachments,
)
from loushang.harnesstui.conversation.controller import (
    ConversationUiController,
    build_standard_conversation_ui_controller,
)
from loushang.harnesstui.conversation.intents import (
    ConversationIntent,
    DebugIntent,
)

_LOG = get_log(__name__).bind(component="CodingUiController")
_PLUGIN_USAGE = (
    "Usage: /plugins [list | explain OPERATION_ID | enable ID | disable ID | "
    "remove ID | repair OPERATION_ID | repair-package ACTION OPERATION_ID]"
)


@dataclass(frozen=True, slots=True)
class ScreenCodingDebugBinding:
    """Late-bound Product effects for the Native screen ``/debug`` command."""

    current_session: Callable[[], object]
    current_cwd: Callable[[], str]
    enable: Callable[..., Path]
    disable: Callable[[], None]


def build_coding_ui_controller(
    *,
    session: Any,
    runtime: Any | None = None,
    verbose: bool = False,
    plugin_workspace: str | Path | None = None,
    plugin_preview: Callable[[], dict[str, object]] | None = None,
    plugin_management_snapshot: Callable[[], dict[str, object]] | None = None,
    plugin_operation_explanation: Callable[[str], dict[str, object]] | None = None,
    plugin_command: Callable[[str], HostActionResult] | None = None,
    plugin_package_repair_command: Callable[[str], HostActionResult] | None = None,
) -> ConversationUiController:
    get_operations = build_coding_session_operation_resolver(
        session=session,
        runtime=runtime,
    )

    def current_session() -> Any:
        return _current_coding_session(session=session, runtime=runtime)

    def plugin_scope() -> tuple[Any, Path]:
        current = current_session()
        manager = getattr(current, "session_manager", None)
        get_cwd = getattr(manager, "get_cwd", None)
        value = get_cwd() if callable(get_cwd) else plugin_workspace
        if value is None:
            raise RuntimeError("Plugin workspace is unavailable")
        return current, Path(value).resolve(strict=True)

    def assert_plugin_scope(bound_session: Any, workspace: Path) -> None:
        current, current_workspace = plugin_scope()
        if current is not bound_session or current_workspace != workspace:
            raise RuntimeError("Plugin Session workspace changed")

    async def dispatch_session_command(
        intent: object,
    ) -> HostActionResult | None:
        text = getattr(intent, "text", None)
        if isinstance(text, str) and (
            text == "/plugins" or text.startswith("/plugins ")
        ):
            if getattr(intent, "images", None):
                return HostActionResult(error_message="/plugins does not accept attachments.")
            provider = getattr(current_session(), "list_commands", None)
            if callable(provider) and any(
                getattr(command, "name", None) == "plugins"
                for command in provider()
            ):
                return HostActionResult(
                    error_message="/plugins conflicts with a selected Session command."
                )
            if text not in {"/plugins", "/plugins list"}:
                words = text.split()
                if len(words) == 4 and words[1] == "repair-package":
                    package_command = plugin_package_repair_command
                    if package_command is None and plugin_workspace is not None:
                        def package_command(text: str) -> HostActionResult:
                            bound_session, workspace = plugin_scope()
                            assert_plugin_scope(bound_session, workspace)
                            result = execute_coding_package_repair_ui_command(
                                workspace, text
                            )
                            assert_plugin_scope(bound_session, workspace)
                            return result

                    if package_command is None:
                        return HostActionResult(
                            error_message="Package repair is unavailable."
                        )
                    try:
                        return await asyncio.to_thread(package_command, text)
                    except Exception:
                        return HostActionResult(
                            error_message="Package repair refused: package_repair_unavailable"
                        )
                if len(words) == 3 and words[1] == "explain":
                    operation_id = words[2]
                    if (
                        not 0 < len(operation_id) <= 256
                        or not operation_id.isascii()
                        or not operation_id.isprintable()
                    ):
                        return HostActionResult(error_message=_PLUGIN_USAGE)
                    explain = plugin_operation_explanation
                    if explain is None and plugin_workspace is not None:
                        def explain(operation_id: str) -> dict[str, object]:
                            bound_session, workspace = plugin_scope()
                            assert_plugin_scope(bound_session, workspace)
                            result = open_coding_plugin_management_read_client(
                                workspace
                            ).explain_operation(
                                operation_id,
                                correlation_id="coding:tui:plugins:explain",
                            )
                            assert_plugin_scope(bound_session, workspace)
                            return result

                    if explain is None:
                        return HostActionResult(
                            error_message="Plugin explanation is unavailable."
                        )
                    try:
                        document = await asyncio.to_thread(explain, operation_id)
                        return HostActionResult(status_message=(
                            _format_coding_plugin_operation_explanation(
                                document, operation_id=operation_id
                            )
                        ))
                    except Exception:
                        return HostActionResult(
                            error_message="Plugin explanation is unavailable."
                        )
                if len(words) != 3 or words[1] not in {
                    "enable", "disable", "remove", "repair"
                }:
                    return HostActionResult(error_message=_PLUGIN_USAGE)
                command = plugin_command
                if command is None and plugin_workspace is not None:
                    def command(text: str) -> HostActionResult:
                        bound_session, workspace = plugin_scope()
                        assert_plugin_scope(bound_session, workspace)
                        result = execute_coding_plugin_management_ui_command(
                            workspace, text
                        )
                        assert_plugin_scope(bound_session, workspace)
                        return result

                if command is None:
                    return HostActionResult(
                        error_message="Plugin commands are unavailable."
                    )
                try:
                    return await asyncio.to_thread(command, text)
                except Exception:
                    return HostActionResult(
                        error_message="Plugin command failed: plugin_management_unavailable"
                    )
            read = (
                plugin_preview
                if text == "/plugins"
                else plugin_management_snapshot
            )
            if read is None and plugin_workspace is not None:
                if text == "/plugins":

                    def read() -> dict[str, object]:
                        bound_session, workspace = plugin_scope()
                        assert_plugin_scope(bound_session, workspace)
                        result = open_coding_plugin_management_read_client(
                            workspace
                        ).preview_current(correlation_id="coding:tui:plugins")
                        assert_plugin_scope(bound_session, workspace)
                        return result

                else:

                    def read() -> dict[str, object]:
                        bound_session, workspace = plugin_scope()
                        assert_plugin_scope(bound_session, workspace)
                        current = current_session()
                        result = open_coding_plugin_management_read_client(
                            workspace
                        ).management_snapshot(
                            correlation_id="coding:tui:plugins:list",
                            settings_manager=getattr(current, "settings_manager", None),
                        )
                        assert_plugin_scope(bound_session, workspace)
                        return result
            if read is None:
                return HostActionResult(error_message="Plugin preview is unavailable.")
            try:
                document = await asyncio.to_thread(read)
                return HostActionResult(
                    status_message=(
                        _format_coding_plugin_preview(document)
                        if text == "/plugins"
                        else _format_coding_plugin_management_list(document)
                    )
                )
            except Exception:
                return HostActionResult(error_message="Plugin preview is unavailable.")
        if getattr(intent, "images", None):
            return None
        current = current_session()
        command_provider = getattr(current, "list_commands", None)
        executor = getattr(current, "execute_command_async", None)
        if not callable(command_provider) or not callable(executor):
            return None
        catalog = ConversationCommandCatalog(session_commands=command_provider)
        effect = catalog.effect_for_route("dispatch", intent)
        if effect is None or effect.kind is not CommandEffectKind.SESSION:
            return None
        if effect.command.source not in {"builtin", "extension"}:
            return None
        invocation_name = effect.payload.get("invocation_name")
        args = effect.payload.get("args", "")
        if not isinstance(invocation_name, str) or not isinstance(args, str):
            return None
        execution = executor(invocation_name, args)
        if inspect.isawaitable(execution):
            execution = await execution
        return _coding_result_from_command_execution(
            execution,
            invocation_name=invocation_name,
        )

    async def execute_bash(command: str) -> None:
        execution = current_session().execute_bash(
            command,
            exclude_from_context=True,
        )
        if inspect.isawaitable(execution):
            await execution

    def abort_command() -> None:
        current = current_session()
        command_execution = getattr(current, "command_execution", None)
        abort = getattr(command_execution, "abort", None)
        if not callable(abort):
            abort = getattr(current, "abort_bash", None)
        if callable(abort):
            abort()

    return build_standard_conversation_ui_controller(
        get_operations=get_operations,
        dispatch_session_command=dispatch_session_command,
        execute_bash=execute_bash,
        abort_command=abort_command,
        verbose=verbose,
        problem_code_prefix="coding_ui",
        problem_logger=_LOG,
    )


def build_coding_session_operation_resolver(
    *,
    session: Any,
    runtime: Any | None = None,
    availability: SessionOperationAvailability | None = None,
) -> SessionOperationResolver:
    """Bind Coding to an explicit dynamic or fixed Session operation mode."""

    if runtime is not None:
        return current_session_operation_resolver(
            runtime,
            availability=availability,
        )

    control = cast(
        SessionControlPort,
        getattr(session, "session_control", session),
    )
    return session_operation_resolver(
        lambda: control,
        availability=availability,
    )


def _current_coding_session(*, session: Any, runtime: Any | None) -> Any:
    return session if runtime is None else require_active_session(runtime)


def _coding_result_from_command_execution(
    execution: object,
    *,
    invocation_name: str,
) -> HostActionResult:
    result = getattr(execution, "result", None)
    if result is None and not hasattr(execution, "result"):
        result = execution
    if isinstance(result, dict):
        display = result.get("display")
        if isinstance(display, str) and display:
            return HostActionResult(status_message=display)
        message = result.get("message")
        if isinstance(message, str) and message:
            if result.get("status") == "error":
                return HostActionResult(error_message=message)
            return HostActionResult(status_message=message)
    return HostActionResult(status_message=f"Command /{invocation_name} completed.")


def _format_coding_plugin_preview(preview: dict[str, object]) -> str:
    """Render the Product's sanitized partial read without claiming live use."""

    if preview.get("snapshotStatus") != "partial_evidence":
        raise ValueError("Plugin preview status is unsupported")

    def strings(key: str) -> list[str]:
        value = preview.get(key)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.isprintable() for item in value
        ):
            raise ValueError("Plugin preview field is invalid")
        return value

    plugins = strings("compiledPluginIds")
    diagnostics = strings("catalogDiagnosticCodes")
    gaps = strings("evidenceGaps")
    raw_resources = preview.get("catalogResources")
    if not isinstance(raw_resources, list):
        raise ValueError("Plugin preview Catalog resources are invalid")
    resources: list[str] = []
    for item in raw_resources:
        if not isinstance(item, dict):
            raise ValueError("Plugin preview Catalog resource is invalid")
        kind, name = item.get("resourceKind"), item.get("name")
        if not all(
            isinstance(value, str) and value.isprintable() and value
            for value in (kind, name)
        ):
            raise ValueError("Plugin preview Catalog resource is invalid")
        resources.append(f"{kind}:{name}")
    disposition = preview.get("disposition")
    if disposition not in {"projected", "blocked"}:
        raise ValueError("Plugin preview disposition is invalid")
    parts = ["Plugin preview (partial)", "compiled: " + (", ".join(plugins) or "none")]
    if resources:
        parts.append("Catalog: " + ", ".join(resources))
    if disposition == "blocked":
        owner, code = preview.get("blockingOwner"), preview.get("blockingCode")
        if not all(isinstance(value, str) and value.isprintable() for value in (owner, code)):
            raise ValueError("Plugin preview blocker is invalid")
        parts.append(f"blocked: {owner}/{code}")
    if diagnostics:
        parts.append("diagnostics: " + ", ".join(diagnostics))
    if gaps:
        parts.append("evidence gaps: " + ", ".join(gaps))
    return " | ".join(parts)


def _format_coding_plugin_operation_explanation(
    document: dict[str, object], *, operation_id: str
) -> str:
    """Render only path-free owner codes from the partial A2/A1 read model."""

    if (
        document.get("operationId") != operation_id
        or document.get("explanationVersion") != 1
        or document.get("snapshotStatus") != "partial_evidence"
    ):
        raise ValueError("Plugin operation explanation changed request identity")
    package = document.get("package")
    if not isinstance(package, dict) or package.get("operationId") != operation_id:
        raise ValueError("Plugin Package explanation changed request identity")
    package_status = package.get("status")
    management_status = document.get("managementStatus")
    handoff = document.get("handoffEvidence")
    join = document.get("joinStatus")
    if (
        package_status not in {"observed", "unknown"}
        or management_status not in {"observed", "unknown"}
        or handoff not in {
            "not_queried", "absent", "incomplete", "settled", "identity_conflict"
        }
        or join not in {
            "same_identity", "package_only", "management_only", "unknown",
            "identity_conflict"
        }
    ):
        raise ValueError("Plugin operation owner status is invalid")
    gaps = document.get("evidenceGaps")
    if not isinstance(gaps, list) or any(
        not _safe_plugin_explanation_code(item) for item in gaps
    ):
        raise ValueError("Plugin operation evidence gaps are invalid")
    phase = package.get("phase")
    disposition = package.get("disposition")
    failure = package.get("failureCode")
    owner_action = package.get("operatorAction")
    management_disposition = document.get("managementDisposition")
    for value in (phase, disposition, failure, owner_action, management_disposition):
        if value is not None and not _safe_plugin_explanation_code(value):
            raise ValueError("Plugin operation owner code is invalid")
    if package_status == "observed" and (phase is None or disposition is None):
        raise ValueError("Observed Package operation lacks status")
    package_text = (
        "unknown" if package_status == "unknown" else f"{phase} / {disposition}"
    )
    management_text = (
        "unknown"
        if management_status == "unknown"
        else f"observed / {management_disposition or 'pending'}"
    )
    parts = [
        f"Plugin operation {operation_id} (partial evidence)",
        f"Package: {package_text}",
        f"Management: {management_text}",
        f"Handoff: {handoff}; join: {join}",
    ]
    if failure is not None:
        suffix = f"; owner action: {owner_action}" if owner_action is not None else ""
        parts.append(f"Package failure: {failure}{suffix}")
    parts.append("Evidence gaps: " + (", ".join(gaps) if gaps else "none"))
    return "\n".join(parts)


def _safe_plugin_explanation_code(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 96
        and value.isascii()
        and all(character.islower() or character.isdigit() or character == "_" for character in value)
    )


def _format_coding_plugin_management_list(document: dict[str, object]) -> str:
    """Summarize the management owner's Desired State and unknown evidence."""

    if document.get("projectionVersion") != 1:
        raise ValueError("Plugin management projection is unsupported")
    revisions = document.get("ownerRevisions")
    revision = revisions.get("desiredState") if isinstance(revisions, dict) else None
    if type(revision) is not int or revision < 0:
        raise ValueError("Plugin management Desired State revision is invalid")
    installations = document.get("installations")
    if not isinstance(installations, list):
        raise ValueError("Plugin management Installations are invalid")
    entries: list[str] = []
    for item in installations:
        if not isinstance(item, dict):
            raise ValueError("Plugin management Installation is invalid")
        key = item.get("installationKey")
        plugin_id = key.get("pluginId") if isinstance(key, dict) else None
        desired = item.get("desiredState")
        convergence = item.get("convergence")
        unknown = item.get("unknownDimensions")
        operations = item.get("operations")
        if (
            not all(
                isinstance(value, str) and value and value.isprintable()
                for value in (plugin_id, desired, convergence)
            )
            or not isinstance(unknown, list)
            or any(
                not isinstance(value, str) or not value.isprintable()
                for value in unknown
            )
            or not isinstance(operations, list)
        ):
            raise ValueError("Plugin management Installation is invalid")
        pending: list[str] = []
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("Plugin management operation is invalid")
            if operation.get("status") in {"accepted", "running"}:
                operation_id = operation.get("operationId")
                if (
                    not isinstance(operation_id, str)
                    or not operation_id.isprintable()
                ):
                    raise ValueError("Plugin management operation is invalid")
                pending.append(operation_id)
        suffix = f" ({convergence}"
        if unknown:
            suffix += "; unknown: " + ", ".join(unknown)
        backup = item.get("backupRetention")
        if backup is not None:
            if (
                not isinstance(backup, dict)
                or set(backup)
                != {"installationKey", "status", "expiryReceiptId"}
                or backup["installationKey"] != key
            ):
                raise ValueError("Plugin management backup retention is invalid")
            backup_status = backup["status"]
            expiry_receipt_id = backup["expiryReceiptId"]
            if backup_status not in {
                "retained",
                "expiry_pending",
                "expired",
                "unknown",
            } or (
                (backup_status == "expired")
                != (isinstance(expiry_receipt_id, str) and bool(expiry_receipt_id))
            ):
                raise ValueError("Plugin management backup retention is invalid")
            suffix += f"; backup: {backup_status}"
        if pending:
            suffix += "; pending: " + ", ".join(pending)
        entries.append(f"{plugin_id}: {desired}{suffix})")
    skew = document.get("skew")
    if not isinstance(skew, list):
        raise ValueError("Plugin management skew is invalid")
    skew_codes: list[str] = []
    for item in skew:
        code = item.get("code") if isinstance(item, dict) else None
        if not isinstance(code, str) or not code or not code.isprintable():
            raise ValueError("Plugin management skew is invalid")
        skew_codes.append(code)
    parts = [
        f"Plugin management (Desired State revision {revision})",
        " | ".join(entries) or "none",
    ]
    if skew_codes:
        parts.append("skew: " + ", ".join(skew_codes))
    return " | ".join(parts)


def build_screen_coding_action_host(
    *,
    presenter: ConversationActionPresentationPort,
    controller: ConversationUiController,
    stderr: TextIO,
    verbose: bool,
    debug: ScreenCodingDebugBinding | None = None,
) -> PresentedConversationActionHost[
    ConversationIntent,
    tuple[ImagePart, ...] | None,
]:
    async def dispatch_intent(intent: ConversationIntent) -> HostActionResult:
        if not isinstance(intent, DebugIntent) or debug is None:
            return await controller.dispatch(intent)
        try:
            if not intent.enabled:
                debug.disable()
                return HostActionResult(status_message="Debug logging disabled.")
            debug_path = debug.enable(
                session=debug.current_session(),
                scopes=intent.scopes,
            )
            return HostActionResult(
                status_message=debug_status_text(
                    debug_path,
                    scopes=intent.scopes,
                    cwd=debug.current_cwd(),
                )
            )
        except Exception as error:
            message = str(error) or error.__class__.__name__
            _LOG.problem(
                "coding_ui_debug_failed",
                source="tui",
                message=message,
                recoverable=True,
                exc=error,
            )
            return HostActionResult(
                error_message=message,
                traceback_text=traceback.format_exc() if verbose else None,
            )

    return build_standard_presented_conversation_action_host(
        presenter=presenter,
        controller=controller,
        stderr=stderr,
        verbose=verbose,
        attachments=agent_image_parts_from_prompt_attachments,
        dispatch_intent=dispatch_intent,
    )


__all__ = [
    "build_coding_session_operation_resolver",
    "build_coding_ui_controller",
    "build_screen_coding_action_host",
    "ScreenCodingDebugBinding",
]
