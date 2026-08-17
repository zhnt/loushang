from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass

from loushang.harness.runtime import SessionOperationResult

RuntimeHostProvider = Callable[[], object | None]


@dataclass
class ExtensionReplacementRuntime:
    get_runtime_host: RuntimeHostProvider

    def create_context(self, session: object) -> object:
        runner = getattr(session, "extension_runner", None)
        if runner is None:
            return session
        session_manager = getattr(session, "session_manager", None)
        fallback_cwd = session_manager.get_cwd() if session_manager is not None else ""
        context = runner.create_command_context(fallback_cwd=fallback_cwd)
        send_message = getattr(session, "_send_message_from_extension", None)
        send_user_message = getattr(
            session, "_send_user_message_from_extension_async", None
        )
        if not callable(send_message) or not callable(send_user_message):
            raise RuntimeError(
                "Session replacement callback requires a valid AgentSession instance."
            )

        def _assert_context_active() -> None:
            getattr(context, "cwd")

        async def _send_message(message: object, options: object | None = None) -> None:
            _assert_context_active()
            await send_message(message, options)

        async def _send_user_message(
            content: object, options: object | None = None
        ) -> None:
            _assert_context_active()
            await send_user_message(content, options)

        context.send_message = _send_message
        context.send_user_message = _send_user_message
        return context

    async def fork(
        self, entry_id: str, options: object | None = None
    ) -> dict[str, object]:
        runtime_host = self.get_runtime_host()
        fork_session_operation = (
            getattr(runtime_host, "fork_session_operation", None)
            if runtime_host is not None
            else None
        )
        if not callable(fork_session_operation):
            return {"cancelled": True}
        opts = options if isinstance(options, dict) else {}
        position = opts.get("position", "before")
        if position not in {"at", "before"}:
            raise ValueError(f"Unsupported fork position: {position}")
        with_session = _with_session_callback(opts)
        _require_async_callback(with_session, name="withSession")
        operation = await fork_session_operation(
            entry_id,
            position=position,
            with_session=with_session,
        )
        return _operation_payload(operation, include_selected_text=True)

    async def new_session(self, options: object | None = None) -> dict[str, object]:
        runtime_host = self.get_runtime_host()
        new_session_operation = (
            getattr(runtime_host, "new_session_operation", None)
            if runtime_host is not None
            else None
        )
        if not callable(new_session_operation):
            return {"cancelled": True}
        opts = options if isinstance(options, dict) else {}
        setup = opts.get("setup")
        with_session = _with_session_callback(opts)
        _require_async_callback(setup, name="setup")
        _require_async_callback(with_session, name="withSession")
        operation = await new_session_operation(
            parent_session=_optional_string(
                opts.get("parentSession", opts.get("parent_session"))
            ),
            setup=setup,
            with_session=with_session,
        )
        return _operation_payload(operation)

    async def switch_session(
        self, session_path: str, options: object | None = None
    ) -> dict[str, object]:
        runtime_host = self.get_runtime_host()
        restore_session_operation = (
            getattr(runtime_host, "restore_session_operation", None)
            if runtime_host is not None
            else None
        )
        if not callable(restore_session_operation):
            return {"cancelled": True}
        opts = options if isinstance(options, dict) else {}
        with_session = _with_session_callback(opts)
        _require_async_callback(with_session, name="withSession")
        operation = await restore_session_operation(
            session_path,
            with_session=with_session,
        )
        return _operation_payload(operation)

    async def clone_session(self) -> dict[str, object]:
        runtime_host = self.get_runtime_host()
        fork_session_operation = (
            getattr(runtime_host, "fork_session_operation", None)
            if runtime_host is not None
            else None
        )
        if not callable(fork_session_operation):
            return {"cancelled": True}
        operation = await fork_session_operation(None, position="at")
        return _operation_payload(operation)

    async def import_session(
        self,
        input_path: str,
        cwd_override: str | None = None,
    ) -> dict[str, object]:
        runtime_host = self.get_runtime_host()
        import_session_operation = (
            getattr(runtime_host, "import_session_operation", None)
            if runtime_host is not None
            else None
        )
        if not callable(import_session_operation):
            return {"cancelled": True}
        operation = await import_session_operation(
            input_path, cwd_override=cwd_override
        )
        return _operation_payload(operation)


def _operation_payload(
    operation: SessionOperationResult[object, object],
    *,
    include_selected_text: bool = False,
) -> dict[str, object]:
    result: dict[str, object] = {"cancelled": operation.cancelled}
    if include_selected_text and isinstance(operation.payload, str):
        result["selected_text"] = operation.payload
    return result


def _with_session_callback(options: dict[str, object]) -> object | None:
    return options.get("withSession") or options.get("with_session")


def _require_async_callback(callback: object | None, *, name: str) -> None:
    if callback is None:
        return
    if inspect.iscoroutinefunction(callback):
        return
    call = getattr(callback, "__call__", None)
    if inspect.iscoroutinefunction(call):
        return
    raise TypeError(f"{name} callback must be an async callable.")


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
