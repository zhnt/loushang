from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol, cast

from loushang.harness.permissions import (
    PermissionProfileScope,
    PermissionProfileSnapshot,
    permission_profile_snapshot,
)


class SessionSettingsSnapshotPort(Protocol):
    @property
    def compaction(self) -> object: ...


class SessionSettingsManagerPort(Protocol):
    def get_settings(self) -> SessionSettingsSnapshotPort: ...

    def get_retry_settings(self) -> object: ...


@dataclass
class SessionSettingsBinding:
    """Bind generic session settings controls to a Product settings store.

    Harness owns the access and fallback behavior.  A Product supplies its
    settings manager and value factories without making the shared session
    facade import Product config types.
    """

    settings_manager: SessionSettingsManagerPort | None = None
    create_settings_manager: Callable[[], SessionSettingsManagerPort] | None = None
    default_compaction: Callable[[], object] = lambda: _empty_settings(
        "compaction"
    )
    default_retry: Callable[[], object] = lambda: _empty_settings("retry")
    get_steering_mode_callback: Callable[[], str] | None = None
    set_steering_mode_callback: Callable[[str], None] | None = None
    get_follow_up_mode_callback: Callable[[], str] | None = None
    set_follow_up_mode_callback: Callable[[str], None] | None = None

    def get_settings_manager(self) -> SessionSettingsManagerPort | None:
        return self.settings_manager

    def get_compaction_settings(self) -> object:
        if self.settings_manager is None:
            return self.default_compaction()
        return getattr(self.settings_manager.get_settings(), "compaction")

    def get_compaction_policy_override(self) -> object | None:
        """Return the bound Product's field-level policy overrides.

        Compaction setting fields use ``None`` to inherit from the runtime
        capability, so a default settings manager does not shadow Product or
        OEM policy values.
        """

        if self.settings_manager is None:
            return None
        return getattr(self.settings_manager.get_settings(), "compaction")

    def get_retry_settings(self) -> object:
        if self.settings_manager is None:
            return self.default_retry()
        return self.settings_manager.get_retry_settings()

    def get_permission_profile_snapshot(self) -> PermissionProfileSnapshot:
        if self.settings_manager is None:
            return permission_profile_snapshot("standard")
        getter = getattr(
            self.settings_manager,
            "get_permission_profile_snapshot",
            None,
        )
        if not callable(getter):
            return permission_profile_snapshot("standard")
        snapshot = getter()
        if not isinstance(snapshot, PermissionProfileSnapshot):
            raise TypeError(
                "settings manager permission profile getter must return "
                "PermissionProfileSnapshot"
            )
        return snapshot

    def set_permission_profile(
        self,
        profile_id: str,
        *,
        scope: PermissionProfileScope = "session",
    ) -> None:
        manager = self.ensure_settings_manager()
        setter = getattr(manager, "set_permission_profile", None)
        if not callable(setter):
            raise RuntimeError(
                "The configured settings manager does not support "
                "permission profiles."
            )
        setter(profile_id, scope=scope)

    def ensure_settings_manager(self) -> SessionSettingsManagerPort:
        if self.settings_manager is None:
            if self.create_settings_manager is None:
                raise RuntimeError("A settings manager factory is not configured.")
            self.settings_manager = self.create_settings_manager()
        return self.settings_manager

    @property
    def auto_retry_enabled(self) -> bool:
        return bool(getattr(self.get_retry_settings(), "enabled", False))

    def set_auto_retry_enabled(self, enabled: bool) -> None:
        getattr(self.ensure_settings_manager(), "set_retry_enabled")(enabled)

    def set_auto_compaction_enabled(self, enabled: bool) -> None:
        manager = self.ensure_settings_manager()
        current = self.get_compaction_settings()
        getattr(manager, "update_settings")(
            scope="session",
            compaction=replace(
                cast(Any, current),
                enabled=enabled,
            ),
        )

    def persist_queue_mode(self, kind: str, mode: str) -> None:
        if self.settings_manager is None:
            return
        try:
            if kind == "steering":
                getattr(self.settings_manager, "set_steering_mode")(
                    mode, scope="global"
                )
            else:
                getattr(self.settings_manager, "set_follow_up_mode")(
                    mode, scope="global"
                )
        except ValueError:
            if kind == "steering":
                getattr(self.settings_manager, "set_steering_mode")(
                    mode, scope="session"
                )
            else:
                getattr(self.settings_manager, "set_follow_up_mode")(
                    mode, scope="session"
                )

    def get_steering_mode(self) -> str:
        if self.get_steering_mode_callback is not None:
            return self.get_steering_mode_callback()
        return _configured_mode(self.settings_manager, "steering_mode")

    def set_steering_mode(self, mode: str) -> None:
        if self.set_steering_mode_callback is not None:
            self.set_steering_mode_callback(mode)
        self.persist_queue_mode("steering", mode)

    def get_follow_up_mode(self) -> str:
        if self.get_follow_up_mode_callback is not None:
            return self.get_follow_up_mode_callback()
        return _configured_mode(self.settings_manager, "follow_up_mode")

    def set_follow_up_mode(self, mode: str) -> None:
        if self.set_follow_up_mode_callback is not None:
            self.set_follow_up_mode_callback(mode)
        self.persist_queue_mode("follow_up", mode)


def _empty_settings(name: str) -> object:
    """Return a neutral fallback for products without optional settings."""

    return type("EmptySettings", (), {"enabled": False, "name": name})()


def _configured_mode(manager: object | None, name: str) -> str:
    if manager is None:
        return "all"
    settings = getattr(manager, "get_settings")()
    value = getattr(settings, name, "all")
    return value if isinstance(value, str) else "all"


__all__ = ["SessionSettingsBinding"]
