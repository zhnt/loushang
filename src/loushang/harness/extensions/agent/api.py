from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from loushang.agent.types import ThinkingLevel
from loushang.harness.extensions.api import ExtensionContributionAPI
from loushang.harness.extensions.types import RegisteredRuntimeCapabilityReplacement
from loushang.harness.runtime import SIDE_QUESTION_PROVIDER_SLOT
from loushang.harness.runtime.registration import (
    RegistrationLease,
    RegistrationLeaseCollector,
)


class ExtensionAPI(ExtensionContributionAPI):
    """Agent session additions to the product-neutral contribution API."""

    def __init__(
        self,
        *,
        name: str,
        source_path: Path,
        entry_path: Path | None = None,
    ) -> None:
        super().__init__(
            name=name,
            source_path=source_path,
            entry_path=entry_path,
        )
        self._pending_provider_actions: list[tuple[str, str, object | None]] = []
        self._admission_provider_actions: list[tuple[str, str, object | None]] = []

    def bind_runtime_state(
        self,
        runtime_state: object,
        registrations: RegistrationLeaseCollector | None = None,
    ) -> None:
        super().bind_runtime_state(runtime_state, registrations)
        self._flush_pending_provider_actions()

    async def append_entry(self, custom_type: str, data: object | None = None) -> None:
        callback = getattr(self._runtime_bindings(), "append_entry", None)
        if callable(callback):
            await callback(custom_type, data)

    async def send_message(
        self, message: object, options: object | None = None
    ) -> None:
        callback = getattr(self._runtime_bindings(), "send_message", None)
        if callable(callback):
            await callback(message, options)

    async def send_user_message(
        self, content: object, options: object | None = None
    ) -> None:
        callback = getattr(self._runtime_bindings(), "send_user_message", None)
        if callable(callback):
            await callback(content, options)

    async def set_model(self, selection: object) -> None:
        callback = getattr(self._runtime_bindings(), "set_model", None)
        if callable(callback):
            await callback(selection)

    def get_thinking_level(self) -> ThinkingLevel:
        callback = getattr(self._runtime_bindings(), "get_thinking_level", None)
        value = callback() if callable(callback) else None
        if value in {"off", "minimal", "low", "medium", "high", "xhigh"}:
            return value
        return "off"

    async def set_thinking_level(self, level: ThinkingLevel) -> None:
        callback = getattr(self._runtime_bindings(), "set_thinking_level", None)
        if callable(callback):
            await callback(level)

    async def set_session_name(self, name: str | None) -> None:
        callback = getattr(self._runtime_bindings(), "set_session_name", None)
        if callable(callback):
            await callback(name)

    def get_session_name(self) -> str | None:
        callback = getattr(self._runtime_bindings(), "get_session_name", None)
        value = callback() if callable(callback) else None
        return value if isinstance(value, str) else None

    async def set_label(self, entry_id: str, label: str | None) -> None:
        callback = getattr(self._runtime_bindings(), "set_label", None)
        if callable(callback):
            await callback(entry_id, label)

    def register_provider(self, name: str, config: object) -> None:
        if not self._apply_provider_action("register", name, config):
            self._pending_provider_actions.append(("register", name, config))

    def unregister_provider(self, name: str) -> None:
        if not self._apply_provider_action("unregister", name, None):
            self._pending_provider_actions.append(("unregister", name, None))

    def register_side_question_provider(
        self,
        name: str,
        *,
        create: Callable[[], object],
        dispose: Callable[[object], None] | None = None,
        implementation_version: int = 1,
        priority: int = 0,
    ) -> None:
        """Declare one candidate for the Agent side-question capability.

        Registration is data-only. Coding admission decides whether the loaded
        Extension may select the slot, and the selected factory is not invoked
        until the final Session capability profile binds.
        """

        self._register_runtime_capability_replacement(
            RegisteredRuntimeCapabilityReplacement(
                slot=SIDE_QUESTION_PROVIDER_SLOT.key,
                name=name,
                create=create,
                dispose=dispose,
                implementation_version=implementation_version,
                priority=priority,
            )
        )

    def _flush_pending_provider_actions(self) -> None:
        if self._runtime_bindings() is None or not self._pending_provider_actions:
            return
        pending = list(self._pending_provider_actions)
        self._pending_provider_actions.clear()
        for index, (action, name, config) in enumerate(pending):
            try:
                applied = self._apply_provider_action(action, name, config)
            except BaseException:
                self._pending_provider_actions.extend(pending[index:])
                raise
            if not applied:
                self._pending_provider_actions.extend(pending[index:])
                return
            self._admission_provider_actions.append((action, name, config))

    def _rollback_runtime_admission(self) -> None:
        """Replay declarative Provider actions after initial admission rollback."""

        self._pending_provider_actions = [
            *self._admission_provider_actions,
            *self._pending_provider_actions,
        ]
        self._admission_provider_actions.clear()

    def _commit_runtime_admission(self) -> None:
        self._admission_provider_actions.clear()

    def _apply_provider_action(
        self, action: str, name: str, config: object | None
    ) -> bool:
        bindings = self._runtime_bindings()
        if bindings is None:
            return False
        if action == "register":
            binder = getattr(bindings, "bind_provider", None)
            registrations = self._registrations
            if callable(binder) and registrations is not None:
                lease = binder(name, config, registrations.owner)
                if not isinstance(lease, RegistrationLease):
                    raise TypeError(
                        "live provider binding must return a RegistrationLease"
                    )
                registrations.capture(lease)
                return True
            callback = getattr(bindings, "register_provider", None)
            if not callable(callback):
                return False
            callback(name, config)
            return True
        registrations = self._registrations
        remover = getattr(bindings, "bind_provider_removal", None)
        if callable(remover) and registrations is not None:
            lease = remover(name, registrations.owner)
            if not isinstance(lease, RegistrationLease):
                raise TypeError(
                    "live provider removal must return a RegistrationLease"
                )
            registrations.capture(lease)
            return True
        callback = getattr(bindings, "unregister_provider", None)
        if not callable(callback):
            return False
        callback(name)
        return True


__all__ = ["ExtensionAPI"]
