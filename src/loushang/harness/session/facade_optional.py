"""Optional capability groups for the Product-facing session facade.

The core facade is always backed by runtime, transcript, command, retry, and
maintenance ports.  Products may independently admit the capabilities in this
module.  Keeping their forwarding and unavailable-capability behavior together
prevents the core surface from becoming the owner of Product-specific policy.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from loushang.agent import ThinkingLevel
from loushang.harness.diagnostics.types import (
    DiagnosticRecord,
    DiagnosticsQuery,
    DiagnosticSummary,
    ErrorReport,
)


class SessionSettingsPort(Protocol):
    """Optional queue/settings controls supplied by a Product config store."""

    def get_settings_manager(self) -> object | None: ...

    def get_steering_mode(self) -> str: ...

    def set_steering_mode(self, mode: str) -> None: ...

    def get_follow_up_mode(self) -> str: ...

    def set_follow_up_mode(self, mode: str) -> None: ...


class SessionModelPort(Protocol):
    """Optional model and thinking selection supplied by a Product/AI port."""

    def get_model_selection(self) -> object | None: ...

    async def set_model(self, model: object) -> None: ...

    async def cycle_model(self, direction: str = "forward") -> object | None: ...

    async def set_thinking_level(self, level: ThinkingLevel) -> None: ...

    async def cycle_thinking_level(self) -> ThinkingLevel | None: ...

    def supports_thinking(self) -> bool: ...

    def get_available_thinking_levels(self) -> Sequence[object]: ...

    def get_available_models(self) -> Sequence[object]: ...

    def get_available_model_details(self) -> Sequence[object]: ...

    def get_scoped_models(self) -> list[dict[str, object]]: ...

    def set_scoped_models(self, scoped_models: list[dict[str, object]]) -> None: ...


class SessionExtensionPort(Protocol):
    """Optional extension and resource watcher lifecycle supplied by a Product."""

    async def start_extension_runtime(self, *, reason: str = "startup") -> None: ...

    async def reload_extension_runtime(self) -> None: ...

    async def poll_resource_changes(self) -> bool: ...

    def start_resource_watcher(self, *, interval_seconds: float = 1.0) -> None: ...

    async def stop_resource_watcher(self) -> None: ...

    def set_extension_ui_context(self, ui_context: object | None) -> None: ...

    def set_extension_runtime_host(self, runtime_host: object | None) -> None: ...


class SessionApplicationInputPort(Protocol):
    """Optional normalized application/user input supplied by a Product."""

    async def send_message(
        self, message: object, options: object | None = None
    ) -> None: ...

    async def send_user_message(
        self, content: object, options: object | None = None
    ) -> None: ...

    def has_pending_messages(self) -> bool: ...


class SessionDiagnosticsPort(Protocol):
    """Optional session-scoped diagnostics queries supplied by a Product."""

    def get_last_diagnostics(self, limit: int = 50) -> list[DiagnosticRecord]: ...

    def get_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]: ...

    def get_session_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]: ...

    def get_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary: ...

    def get_session_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary: ...

    def get_last_error_report(self) -> ErrorReport | None: ...


class SessionPackagePort(Protocol):
    """Optional package operations bound by a Product resource policy."""

    def get_packages(
        self, *, catalog_path: str | None = None
    ) -> list[dict[str, object]]: ...

    async def materialize_package(self, source: str) -> dict[str, object]: ...

    async def install_package(
        self, source: str, *, scope: str = "project"
    ) -> dict[str, object]: ...

    async def update_package(self, source: str) -> dict[str, object]: ...

    async def update_packages(self) -> list[dict[str, object]]: ...

    async def check_package_updates(self) -> list[dict[str, object]]: ...

    def remove_package(self, source: str) -> dict[str, object]: ...

    def uninstall_package(
        self, source: str, *, scope: str = "project"
    ) -> dict[str, object]: ...


class SessionFacadeOptionalOperations:
    """Forward independently admitted capability groups with stable fallbacks."""

    diagnostics: SessionDiagnosticsPort | None
    packages: SessionPackagePort | None
    model_selection: SessionModelPort | None
    extensions: SessionExtensionPort | None
    settings: SessionSettingsPort | None
    application_input: SessionApplicationInputPort | None

    async def send_message(
        self, message: object, options: object | None = None
    ) -> None:
        await self._require_application_input().send_message(message, options)

    async def send_user_message(
        self, content: object, options: object | None = None
    ) -> None:
        await self._require_application_input().send_user_message(content, options)

    def has_pending_messages(self) -> bool:
        return self._require_application_input().has_pending_messages()

    def _require_application_input(self) -> SessionApplicationInputPort:
        if self.application_input is None:
            raise RuntimeError("Application input is not available.")
        return self.application_input

    @property
    def settings_manager(self) -> object | None:
        return self.settings.get_settings_manager() if self.settings else None

    @property
    def steering_mode(self) -> str:
        return self._require_settings().get_steering_mode()

    def set_steering_mode(self, mode: str) -> None:
        self._require_settings().set_steering_mode(mode)

    @property
    def follow_up_mode(self) -> str:
        return self._require_settings().get_follow_up_mode()

    def set_follow_up_mode(self, mode: str) -> None:
        self._require_settings().set_follow_up_mode(mode)

    def _require_settings(self) -> SessionSettingsPort:
        if self.settings is None:
            raise RuntimeError("Session settings are not available.")
        return self.settings

    def list_extensions(self) -> list[dict[str, object]]:
        getter = getattr(self.extensions, "list_extensions", None)
        if not callable(getter):
            return []
        return list(getter())

    def get_model_selection(self) -> object | None:
        return self._require_model_selection().get_model_selection()

    async def set_model(self, model: object) -> None:
        await self._require_model_selection().set_model(model)

    async def cycle_model(self, direction: str = "forward") -> object | None:
        return await self._require_model_selection().cycle_model(direction)

    async def set_thinking_level(self, level: ThinkingLevel) -> None:
        await self._require_model_selection().set_thinking_level(level)

    async def cycle_thinking_level(self) -> ThinkingLevel | None:
        return await self._require_model_selection().cycle_thinking_level()

    def supports_thinking(self) -> bool:
        return self._require_model_selection().supports_thinking()

    def get_available_thinking_levels(self) -> list[object]:
        return list(
            self._require_model_selection().get_available_thinking_levels()
        )

    def get_available_models(self) -> list[object]:
        return list(self._require_model_selection().get_available_models())

    def get_available_model_details(self) -> list[object]:
        return list(self._require_model_selection().get_available_model_details())

    @property
    def scoped_models(self) -> list[dict[str, object]]:
        return self._require_model_selection().get_scoped_models()

    def set_scoped_models(self, scoped_models: list[dict[str, object]]) -> None:
        self._require_model_selection().set_scoped_models(scoped_models)

    def _require_model_selection(self) -> SessionModelPort:
        if self.model_selection is None:
            raise RuntimeError("Model selection is not available.")
        return self.model_selection

    def get_last_diagnostics(self, limit: int = 50) -> list[DiagnosticRecord]:
        return self.diagnostics.get_last_diagnostics(limit) if self.diagnostics else []

    def get_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]:
        return self.diagnostics.get_diagnostics(query) if self.diagnostics else []

    def get_session_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]:
        return (
            self.diagnostics.get_session_diagnostics(query)
            if self.diagnostics
            else []
        )

    def get_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary:
        return (
            self.diagnostics.get_diagnostics_summary(query)
            if self.diagnostics
            else DiagnosticSummary(0, 0, 0, 0)
        )

    def get_session_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary:
        return (
            self.diagnostics.get_session_diagnostics_summary(query)
            if self.diagnostics
            else DiagnosticSummary(0, 0, 0, 0)
        )

    def get_last_error_report(self) -> ErrorReport | None:
        return self.diagnostics.get_last_error_report() if self.diagnostics else None

    def get_packages(
        self, *, catalog_path: str | None = None
    ) -> list[dict[str, object]]:
        return self.packages.get_packages(catalog_path=catalog_path) if self.packages else []

    async def materialize_package(self, source: str) -> dict[str, object]:
        return await self._require_packages().materialize_package(source)

    async def install_package(
        self, source: str, *, scope: str = "project"
    ) -> dict[str, object]:
        return await self._require_packages().install_package(source, scope=scope)

    async def update_package(self, source: str) -> dict[str, object]:
        return await self._require_packages().update_package(source)

    async def update_packages(self) -> list[dict[str, object]]:
        return await self._require_packages().update_packages()

    async def check_package_updates(self) -> list[dict[str, object]]:
        return await self._require_packages().check_package_updates()

    def remove_package(self, source: str) -> dict[str, object]:
        return self._require_packages().remove_package(source)

    def uninstall_package(
        self, source: str, *, scope: str = "project"
    ) -> dict[str, object]:
        return self._require_packages().uninstall_package(source, scope=scope)

    def _require_packages(self) -> SessionPackagePort:
        if self.packages is None:
            raise RuntimeError("Package operations are not available.")
        return self.packages

    async def start_extension_runtime(self, *, reason: str = "startup") -> None:
        await self._require_extensions().start_extension_runtime(reason=reason)

    async def reload_extension_runtime(self) -> None:
        await self._require_extensions().reload_extension_runtime()

    async def poll_resource_changes(self) -> bool:
        return await self._require_extensions().poll_resource_changes()

    def start_resource_watcher(self, *, interval_seconds: float = 1.0) -> None:
        self._require_extensions().start_resource_watcher(
            interval_seconds=interval_seconds
        )

    async def stop_resource_watcher(self) -> None:
        await self._require_extensions().stop_resource_watcher()

    def set_extension_ui_context(self, ui_context: object | None) -> None:
        self._require_extensions().set_extension_ui_context(ui_context)

    def set_extension_runtime_host(self, runtime_host: object | None) -> None:
        self._require_extensions().set_extension_runtime_host(runtime_host)

    def _require_extensions(self) -> SessionExtensionPort:
        if self.extensions is None:
            raise RuntimeError("Extension runtime is not available.")
        return self.extensions


__all__ = [
    "SessionApplicationInputPort",
    "SessionDiagnosticsPort",
    "SessionExtensionPort",
    "SessionFacadeOptionalOperations",
    "SessionModelPort",
    "SessionPackagePort",
    "SessionSettingsPort",
]
