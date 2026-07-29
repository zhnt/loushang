"""Product-neutral remote UI interaction context for headless hosts."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Mapping


class RemoteUiContext:
    """Maintain remote UI state and resolve client-supplied dialog responses.

    Product hosts choose the exact output schema through ``emit``.  This class
    only owns request correlation, timeout behavior, and state snapshots shared
    by headless extension or plugin hosts.
    """

    def __init__(self, emit: Callable[[dict[str, object]], None]) -> None:
        self._emit = emit
        self._pending: dict[str, asyncio.Future[object]] = {}
        self._notifications: list[dict[str, object]] = []
        self._statuses: dict[str, str] = {}
        self._widgets: dict[str, dict[str, object]] = {}
        self._title: str | None = None
        self._editor_text = ""

    async def select(
        self, title: str, options: list[str], *, timeout: float | None = None
    ) -> str | None:
        response = await self._request_dialog(
            {
                "method": "select",
                "title": title,
                "options": list(options),
                **_timeout_payload(timeout),
            },
            timeout=timeout,
            default={"cancelled": True},
        )
        if response.get("cancelled") is True:
            return None
        value = response.get("value")
        return value if isinstance(value, str) else None

    async def confirm(
        self, title: str, message: str, *, timeout: float | None = None
    ) -> bool:
        response = await self._request_dialog(
            {
                "method": "confirm",
                "title": title,
                "message": message,
                **_timeout_payload(timeout),
            },
            timeout=timeout,
            default={"confirmed": False},
        )
        return (
            bool(response.get("confirmed", False))
            if response.get("cancelled") is not True
            else False
        )

    async def input(
        self,
        title: str,
        placeholder: str | None = None,
        *,
        timeout: float | None = None,
    ) -> str | None:
        payload: dict[str, object] = {
            "method": "input",
            "title": title,
            **_timeout_payload(timeout),
        }
        if placeholder is not None:
            payload["placeholder"] = placeholder
        return await self._optional_text_dialog(payload, timeout=timeout)

    async def editor(
        self, title: str, prefill: str | None = None, *, timeout: float | None = None
    ) -> str | None:
        payload: dict[str, object] = {"method": "editor", "title": title}
        if prefill is not None:
            payload["prefill"] = prefill
        payload.update(_timeout_payload(timeout))
        return await self._optional_text_dialog(payload, timeout=timeout)

    def notify(self, message: str, notify_type: str | None = None) -> None:
        payload: dict[str, object] = {"method": "notify", "message": message}
        if notify_type is not None:
            payload["notifyType"] = notify_type
        self._notifications.append(
            {key: value for key, value in payload.items() if key != "method"}
        )
        self.emit_request(payload)

    def set_status(self, key: str, text: str | None) -> None:
        payload: dict[str, object] = {"method": "setStatus", "statusKey": key}
        if text is None:
            self._statuses.pop(key, None)
        else:
            payload["statusText"] = text
            self._statuses[key] = text
        self.emit_request(payload)

    def set_widget(
        self, key: str, lines: list[str] | None, *, placement: str | None = None
    ) -> None:
        payload: dict[str, object] = {"method": "setWidget", "widgetKey": key}
        if lines is None:
            self._widgets.pop(key, None)
        else:
            payload["widgetLines"] = list(lines)
            widget: dict[str, object] = {"lines": list(lines)}
            if placement is not None:
                widget["placement"] = placement
            self._widgets[key] = widget
        if placement is not None:
            payload["widgetPlacement"] = placement
        self.emit_request(payload)

    def set_title(self, title: str) -> None:
        self._title = title
        self.emit_request({"method": "setTitle", "title": title})

    def set_editor_text(self, text: str) -> None:
        self._editor_text = text
        self.emit_request({"method": "set_editor_text", "text": text})

    def get_editor_text(self) -> str:
        return self._editor_text

    def get_snapshot(self) -> dict[str, object]:
        return {
            "notifications": list(self._notifications),
            "statuses": dict(self._statuses),
            "widgets": {key: dict(value) for key, value in self._widgets.items()},
            "title": self._title,
            "editorText": self._editor_text,
        }

    def resolve_response(self, response: Mapping[str, object]) -> None:
        request_id = response.get("id")
        if not isinstance(request_id, str):
            return
        future = self._pending.pop(request_id, None)
        if future is not None and not future.done():
            future.set_result(dict(response))

    def emit_request(self, payload: dict[str, object]) -> str:
        request_id = str(uuid.uuid4())
        self._emit({"type": "remote_ui_request", "id": request_id, **payload})
        return request_id

    async def _optional_text_dialog(
        self, payload: dict[str, object], *, timeout: float | None
    ) -> str | None:
        response = await self._request_dialog(
            payload, timeout=timeout, default={"cancelled": True}
        )
        if response.get("cancelled") is True:
            return None
        value = response.get("value")
        return value if isinstance(value, str) else None

    async def _request_dialog(
        self,
        payload: dict[str, object],
        *,
        timeout: float | None,
        default: dict[str, object],
    ) -> dict[str, object]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[object] = loop.create_future()
        request_id = str(uuid.uuid4())
        self._pending[request_id] = future
        try:
            self._emit({"type": "remote_ui_request", "id": request_id, **payload})
            result = (
                await asyncio.wait_for(future, timeout=timeout)
                if timeout is not None
                else await future
            )
        except TimeoutError:
            self._pending.pop(request_id, None)
            return default
        except BaseException:
            self._pending.pop(request_id, None)
            raise
        return result if isinstance(result, dict) else {}


def _timeout_payload(timeout: float | None) -> dict[str, float]:
    return {} if timeout is None else {"timeout": timeout}


__all__ = ["RemoteUiContext"]
