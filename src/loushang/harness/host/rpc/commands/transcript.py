"""Transcript query and export commands for the shared RPC host."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from loushang.harness.host.rpc.arguments import optional_string
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.host.rpc.wire import camelize, project_json_value
from loushang.harness.transcript import create_agent_transcript_message_codec

_MESSAGE_CODEC = create_agent_transcript_message_codec()


class _TranscriptCapabilityUnavailable(RuntimeError):
    pass


class _TranscriptQueries(Protocol):
    """Semantic transcript capabilities consumed by this command group."""

    def get_messages(self) -> object: ...

    def get_last_assistant_text(self) -> object: ...

    def get_fork_messages(self) -> object: ...

    def export_html(self, output_path: str | None) -> object: ...


class _DynamicTranscriptQueries:
    """Resolve transcript reads against the current Product session."""

    def __init__(
        self,
        *,
        get_session: Callable[[], object],
        get_messages: Callable[[object], object],
    ) -> None:
        self._get_session = get_session
        self._get_messages = get_messages

    def get_messages(self) -> object:
        session = self._get_session()
        return self._get_messages(session)

    def get_last_assistant_text(self) -> object:
        method = self._resolve("get_last_assistant_text")
        return method() if method is not None else None

    def get_fork_messages(self) -> object:
        method = self._resolve("get_user_messages_for_forking")
        if method is None:
            raise _TranscriptCapabilityUnavailable
        return method()

    def export_html(self, output_path: str | None) -> object:
        method = self._resolve("export_to_html")
        if method is None:
            raise _TranscriptCapabilityUnavailable
        return method(output_path)

    def _resolve(self, name: str) -> Callable[..., object] | None:
        method = getattr(self._get_session(), name, None)
        return method if callable(method) else None


class RpcTranscriptCommands:
    """Project transcript reads without owning Session or wire lifecycle."""

    def __init__(
        self,
        *,
        get_session: Callable[[], object],
        get_messages: Callable[[object], object],
        output: RpcOutput,
    ) -> None:
        self._queries: _TranscriptQueries = _DynamicTranscriptQueries(
            get_session=get_session,
            get_messages=get_messages,
        )
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return (
            ("get_messages", self.get_messages),
            ("get_last_assistant_text", self.get_last_assistant_text),
            ("get_fork_messages", self.get_fork_messages),
            ("export_html", self.export_html),
        )

    def get_messages(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        messages = self._queries.get_messages()
        if not isinstance(messages, list):
            self._error(
                command_id,
                "get_messages",
                "Message log returned an invalid response.",
            )
            return
        serialized_messages: list[dict[str, Any]] = []
        for message in messages:
            try:
                serialized_messages.append(_MESSAGE_CODEC.serialize(message))
            except Exception:
                continue
        self._output.success(
            request_id=command_id,
            command="get_messages",
            data={"messages": serialized_messages},
        )

    def get_last_assistant_text(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        try:
            text = self._queries.get_last_assistant_text()
        except Exception as error:
            self._error(
                command_id,
                "get_last_assistant_text",
                f"Failed to read last assistant text: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="get_last_assistant_text",
            data={"text": text},
        )

    def get_fork_messages(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        try:
            raw_messages = self._queries.get_fork_messages()
        except _TranscriptCapabilityUnavailable:
            self._error(
                command_id,
                "get_fork_messages",
                "Fork messages are not available.",
            )
            return
        except Exception as error:
            self._error(
                command_id,
                "get_fork_messages",
                f"Failed to query fork messages: {error}",
            )
            return
        if not isinstance(raw_messages, list):
            self._error(
                command_id,
                "get_fork_messages",
                "Fork messages returned an invalid response.",
            )
            return
        self._output.success(
            request_id=command_id,
            command="get_fork_messages",
            data={"messages": camelize(project_json_value(raw_messages))},
        )

    def export_html(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        output_path = optional_string(payload, "outputPath", "output_path")
        try:
            path = self._queries.export_html(output_path)
        except _TranscriptCapabilityUnavailable:
            self._error(
                command_id,
                "export_html",
                "HTML export is not available.",
            )
            return
        except Exception as error:
            self._error(
                command_id,
                "export_html",
                f"Failed to export HTML: {error}",
            )
            return
        if not isinstance(path, str):
            if isinstance(path, Path):
                path = str(path)
            else:
                self._error(
                    command_id,
                    "export_html",
                    "Export returned an invalid response.",
                )
                return
        self._output.success(
            request_id=command_id,
            command="export_html",
            data={"path": path},
        )

    def _error(self, command_id: str | None, command: str, error: str) -> None:
        self._output.error(
            request_id=command_id,
            command=command,
            error=error,
        )


__all__ = ["RpcTranscriptCommands"]
