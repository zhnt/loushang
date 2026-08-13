from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from loushang.ai.model import ModelSelection
from loushang.ai.model.domain import (
    Endpoint,
    Model,
)
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.harness.commands import CommandSourceInfo, SessionCommandDescriptor
from loushang.harness.conversation import ConversationRecord
from loushang.harness.diagnostics import (
    DiagnosticRecord,
    DiagnosticsQuery,
    DiagnosticSummary,
    ErrorReport,
)
from loushang.harness.resources.types import (
    ResourceBundle,
)
from loushang.harness.runtime import SessionOperationResult
from loushang.harness.runtime.types import RunState
from loushang.harness.session.inspection import AgentSessionState
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    CompactionResult,
    SessionQuery,
)


def _assistant_message(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _user_message(text: str) -> UserMessage:
    return UserMessage(
        role="user",
        content=[TextPart(type="text", text=text)],
        timestamp=0.0,
    )


def _message_record(record_id: str, message: UserMessage) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-05-21T00:00:00Z",
        payload=message,
    )


def _parse_jsonl(stream: StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _command_descriptor(item: dict[str, object]) -> SessionCommandDescriptor:
    source_info = item.get("source_info")
    path = (
        source_info.get("path", "")
        if isinstance(source_info, dict)
        else item.get("path", "")
    )
    path_text = str(path)
    return SessionCommandDescriptor(
        name=item.get("name") if isinstance(item.get("name"), str) else "",
        description=item.get("description")
        if isinstance(item.get("description"), str)
        else None,
        source=item.get("source") if isinstance(item.get("source"), str) else "",
        source_info=CommandSourceInfo(
            path=path_text, base_dir=str(Path(path_text).parent) if path_text else None
        ),
    )


class FakeSessionManager:
    def __init__(self, cwd: str, owner: "FakeSession") -> None:
        self._cwd = cwd
        self._owner = owner
        self.session_info_calls: list[str | None] = []
        self._leaf_id: str | None = "leaf-1"
        self._entries_by_id: dict[str, object] = {}

    def get_cwd(self) -> str:
        return self._cwd

    def get_leaf_id(self) -> str | None:
        return self._leaf_id

    def set_leaf_id(self, leaf_id: str | None) -> None:
        self._leaf_id = leaf_id

    def get_entry(self, entry_id: str):
        return self._entries_by_id.get(entry_id)

    def set_entry(self, entry_id: str, entry: object) -> None:
        self._entries_by_id[entry_id] = entry

    async def append_session_info(self, name: str | None) -> str:
        self.session_info_calls.append(name)
        self._owner.session_name = name
        return "session-info-1"


class FakeAgent:
    def __init__(self) -> None:
        self.steering_mode = "one-at-a-time"
        self.follow_up_mode = "one-at-a-time"


class FakeModelRegistry:
    def __init__(
        self,
        models: list[ModelSelection] | None = None,
        resolved_models: dict[tuple[str, str, str], Model] | None = None,
        endpoints: dict[tuple[str, str], Endpoint] | None = None,
    ) -> None:
        self._models = list(models or [])
        self._resolved_models = dict(resolved_models or {})
        self._endpoints = dict(endpoints or {})

    def list_models(self) -> list[ModelSelection]:
        return list(self._models)

    def build_model(self, selection: ModelSelection) -> Model:
        key = (selection.provider, selection.endpoint_id, selection.model_id)
        try:
            return self._resolved_models[key]
        except KeyError as error:
            raise KeyError(key) from error

    def get_endpoint(self, provider: str, endpoint: str) -> Endpoint | None:
        return self._endpoints.get((provider, endpoint))


class FakeSession:
    def __init__(
        self,
        *,
        session_id: str,
        cwd: str,
        session_name: str | None = None,
        event_message: AssistantMessage | None = None,
        messages: list[object] | None = None,
    ) -> None:
        self.session_id = session_id
        self.session_name = session_name
        self.session_file = Path(cwd) / f"{session_id}.jsonl"
        self.agent = FakeAgent()
        self.session_manager = FakeSessionManager(cwd, self)
        self.model_registry = FakeModelRegistry()
        self.resource_bundle = ResourceBundle(cwd=Path(cwd))
        self.listeners = []
        self.prompt_calls: list[tuple[str, object]] = []
        self.prompt_kwargs: list[dict[str, object]] = []
        self.wait_calls = 0
        self.steer_calls: list[tuple[str, object]] = []
        self.follow_up_calls: list[tuple[str, object]] = []
        self.abort_calls = 0
        self.set_model_calls: list[ModelSelection] = []
        self.set_active_tools_calls: list[list[str]] = []
        self.set_thinking_level_calls: list[str] = []
        self.set_steering_mode_calls: list[str] = []
        self.set_follow_up_mode_calls: list[str] = []
        self.set_session_name_calls: list[str | None] = []
        self.set_auto_retry_calls: list[bool] = []
        self.set_auto_compaction_calls: list[bool] = []
        self.command_entries: list[dict[str, object]] = []
        self.diagnostics: list[DiagnosticRecord] = []
        self.packages: list[dict[str, object]] = []
        self.error_report: ErrorReport | None = None
        self.abort_retry_calls = 0
        self.compact_calls: list[str | None] = []
        self.bash_calls: list[dict[str, object]] = []
        self.abort_bash_calls = 0
        self.export_to_html_calls: list[str | None] = []
        self.user_messages_for_forking: list[dict[str, str]] = []
        self._bash_started: asyncio.Event | None = None
        self._bash_release: asyncio.Event | None = None
        self._bash_result: dict[str, object] = {
            "output": "ok\n",
            "exit_code": 0,
            "cancelled": False,
            "truncated": False,
            "full_output_path": None,
        }
        self._event_message = event_message
        self._messages = list(messages or [])
        self._prompt_started: asyncio.Event | None = None
        self._prompt_release: asyncio.Event | None = None
        self._state = AgentSessionState(
            run=RunState(status="idle"),
            steering=[],
            follow_up=[],
            active_tool_names=[],
            is_compacting=False,
            is_retrying=False,
            thinking_level="off",
            model_selection=None,
        )

    @property
    def session_control(self) -> "FakeSession":
        return self

    def subscribe(self, listener):
        self.listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self.listeners:
                self.listeners.remove(listener)

        return unsubscribe

    def get_state(self) -> AgentSessionState:
        return self._state

    def get_model_selection(self) -> ModelSelection | None:
        return self._state.model_selection

    def get_session_context(self):
        return SimpleNamespace(messages=tuple(self._messages))

    async def prompt(self, user_input: str, images=None, **kwargs) -> None:
        self.prompt_calls.append((user_input, images))
        self.prompt_kwargs.append(dict(kwargs))
        preflight_result = kwargs.get("preflight_result")
        if callable(preflight_result):
            preflight_result(True)
        streaming_behavior = kwargs.get("streaming_behavior")
        if self._state.run.status == "running" and streaming_behavior in {
            "steer",
            "followUp",
            "follow_up",
        }:
            if streaming_behavior == "steer":
                self.steer(user_input, images=images)
            else:
                self.follow_up(user_input, images=images)
            return
        self._state = replace(self._state, run=RunState(status="running"))
        if self._prompt_started is not None:
            self._prompt_started.set()
        if self._prompt_release is not None:
            await self._prompt_release.wait()
        if self._event_message is not None:
            self._messages.append(self._event_message)
            for listener in list(self.listeners):
                listener({"type": "message_end", "message": self._event_message})
        self._state = replace(self._state, run=RunState(status="idle"))

    async def wait_for_idle(self) -> None:
        self.wait_calls += 1

    def steer(self, user_input: str, images=None) -> None:
        self.steer_calls.append((user_input, images))
        self._state = replace(self._state, steering=[*self._state.steering, user_input])

    def follow_up(self, user_input: str, images=None) -> None:
        self.follow_up_calls.append((user_input, images))
        self._state = replace(
            self._state, follow_up=[*self._state.follow_up, user_input]
        )

    def abort(self) -> None:
        self.abort_calls += 1

    async def set_model(self, selection: ModelSelection) -> None:
        self.set_model_calls.append(selection)
        self._state = replace(self._state, model_selection=selection)

    async def cycle_model(self) -> ModelSelection | None:
        models = self.get_available_models()
        if not isinstance(models, list):
            raise TypeError("Model registry returned an invalid response.")
        if not models:
            return None
        current = self.get_model_selection()
        try:
            index = models.index(current) if current is not None else -1
        except ValueError:
            index = -1
        selection = models[(index + 1) % len(models)]
        await self.set_model(selection)
        return selection

    async def set_active_tools(self, tool_names: list[str]) -> None:
        self.set_active_tools_calls.append(list(tool_names))
        self._state = replace(self._state, active_tool_names=list(tool_names))

    def set_thinking_level(self, level: str) -> None:
        self.set_thinking_level_calls.append(level)
        self._state = replace(self._state, thinking_level=level)

    def cycle_thinking_level(self) -> str:
        order = ("off", "minimal", "low", "medium", "high", "xhigh")
        try:
            index = order.index(self._state.thinking_level)
        except ValueError:
            index = 0
        next_level = order[(index + 1) % len(order)]
        self.set_thinking_level(next_level)
        return next_level

    def set_steering_mode(self, mode: str) -> None:
        self.set_steering_mode_calls.append(mode)
        self.agent.steering_mode = mode

    def set_follow_up_mode(self, mode: str) -> None:
        self.set_follow_up_mode_calls.append(mode)
        self.agent.follow_up_mode = mode

    async def set_session_name(self, name: str | None) -> None:
        self.set_session_name_calls.append(name)
        await self.session_manager.append_session_info(name)

    def get_available_models(self) -> list[ModelSelection]:
        return self.model_registry.list_models()

    def list_commands(self) -> list[object]:
        if self.command_entries:
            return [
                command
                if isinstance(command, SessionCommandDescriptor)
                else _command_descriptor(command)
                for command in self.command_entries
            ]
        commands: list[SessionCommandDescriptor] = []
        for prompt in self.resource_bundle.prompts:
            commands.append(
                _command_descriptor(
                    {
                        "name": f"/{prompt.name}",
                        "source": "prompt",
                        "path": str(prompt.source_path),
                    }
                )
            )
        for skill in self.resource_bundle.skills:
            commands.append(
                _command_descriptor(
                    {
                        "name": f"/skill:{skill.name}",
                        "source": "skill",
                        "path": str(skill.source_path),
                    }
                )
            )
        return commands

    def get_last_diagnostics(self, limit: int = 50) -> list[DiagnosticRecord]:
        return self.diagnostics[-limit:]

    def get_last_error_report(self) -> ErrorReport | None:
        return self.error_report

    def set_auto_retry_enabled(self, enabled: bool) -> None:
        self.set_auto_retry_calls.append(enabled)

    @property
    def auto_compaction_enabled(self) -> bool:
        return (
            True
            if not self.set_auto_compaction_calls
            else self.set_auto_compaction_calls[-1]
        )

    def set_auto_compaction_enabled(self, enabled: bool) -> None:
        self.set_auto_compaction_calls.append(enabled)

    def abort_retry(self) -> None:
        self.abort_retry_calls += 1

    async def execute_bash(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env=None,
        timeout_seconds: float | None = None,
        stdin: str | None = None,
    ) -> dict[str, object]:
        self.bash_calls.append(
            {
                "command": command,
                "cwd": cwd,
                "env": env,
                "timeout_seconds": timeout_seconds,
                "stdin": stdin,
            }
        )
        if self._bash_started is not None:
            self._bash_started.set()
        if self._bash_release is not None:
            await self._bash_release.wait()
        return dict(self._bash_result)

    def abort_bash(self) -> None:
        self.abort_bash_calls += 1
        if self._bash_release is not None:
            self._bash_result = {
                "output": "partial\n",
                "exit_code": None,
                "cancelled": True,
                "truncated": False,
                "full_output_path": None,
            }
            self._bash_release.set()

    async def compact(self, custom_instructions: str | None = None) -> CompactionResult:
        self.compact_calls.append(custom_instructions)
        return CompactionResult(
            summary="compacted",
            first_kept_entry_id="entry-1",
            tokens_before=42,
            details={"preserved": 3},
        )

    def get_session_stats(self):
        model_selection = self._state.model_selection
        return {
            "sessionId": self.session_id,
            "sessionName": self.session_name,
            "entryCount": 7,
            "messageCount": 5,
            "customMessageCount": 1,
            "activeToolCount": len(self._state.active_tool_names),
            "isRetrying": self._state.is_retrying,
            "isCompacting": self._state.is_compacting,
            "hasDiagnostics": False,
            "branchCount": 2,
            "lastModelSelection": (
                None
                if model_selection is None
                else {
                    "provider": model_selection.provider,
                    "modelId": model_selection.model_id,
                }
            ),
            "contextUsage": {
                "messageCount": 5,
                "assistantMessageCount": 2,
                "userMessageCount": 2,
                "toolCallCount": 1,
                "toolResultCount": 1,
                "customMessageCount": 1,
                "estimatedContextTokens": 123,
                "hasCompaction": False,
                "branchDepth": 2,
                "leafEntryId": "leaf-1",
            },
        }

    def export_to_html(self, output_path: str | None = None) -> str:
        self.export_to_html_calls.append(output_path)
        return output_path or f"/tmp/{self.session_id}.html"

    def get_last_assistant_text(self) -> str | None:
        for message in reversed(self._messages):
            if getattr(message, "role", None) != "assistant":
                continue
            return "".join(
                block.text
                for block in message.content
                if getattr(block, "type", None) == "text"
            )
        return None

    def get_user_messages_for_forking(self) -> list[dict[str, str]]:
        return [
            {"entry_id": item["entry_id"], "text": item["text"]}
            for item in self.user_messages_for_forking
        ]

    def get_entry_text(self, entry_id: str) -> str | None:
        entry = self.session_manager.get_entry(entry_id)
        if entry is None:
            return None
        content = getattr(getattr(entry, "payload", None), "content", None)
        if isinstance(content, str):
            return content or None
        if isinstance(content, list):
            text = "".join(
                block.text
                for block in content
                if getattr(block, "type", None) == "text"
            )
            return text or None
        return None

    def get_packages(
        self, *, catalog_path: str | None = None
    ) -> list[dict[str, object]]:
        del catalog_path
        return list(self.packages)


class FakeRuntime:
    def __init__(
        self, session: FakeSession, session_summaries: list[object] | None = None
    ) -> None:
        self._current_session = session
        self.new_session_calls: list[dict[str, object]] = []
        self.switch_session_calls: list[object] = []
        self.fork_session_calls: list[str] = []
        self.fork_session_operation_calls: list[tuple[str | None, str]] = []
        self._next_session: FakeSession | None = None
        self.session_summaries = list(session_summaries or [])
        self.list_session_summaries_calls = 0
        self.find_session_summaries_calls: list[SessionQuery | None] = []
        self.find_all_session_summaries_calls: list[SessionQuery | None] = []
        self.refresh_session_index_calls = 0
        self.refresh_all_session_indexes_calls = 0
        self.list_indexed_session_summaries_calls = 0
        self.list_all_indexed_session_summaries_calls = 0
        self.find_indexed_session_summaries_calls: list[SessionQuery | None] = []
        self.find_all_indexed_session_summaries_calls: list[SessionQuery | None] = []
        self.diagnostics: list[DiagnosticRecord] = []
        self.get_diagnostics_calls: list[DiagnosticsQuery | None] = []
        self.get_session_diagnostics_calls: list[DiagnosticsQuery | None] = []
        self.get_diagnostics_summary_calls: list[DiagnosticsQuery | None] = []
        self.get_session_diagnostics_summary_calls: list[DiagnosticsQuery | None] = []
        self.get_packages_calls: list[str | None] = []
        self.materialize_package_calls: list[str] = []
        self.install_package_calls: list[str] = []
        self.update_package_calls: list[str] = []
        self.update_packages_calls = 0
        self.check_package_updates_calls = 0
        self.remove_package_calls: list[str] = []
        self.uninstall_package_calls: list[str] = []

    def get_current_session(self) -> FakeSession:
        return self._current_session

    def queue_next_session(self, session: FakeSession) -> None:
        self._next_session = session

    async def new_session_operation(self, *, cwd=None, parent_session=None):
        self.new_session_calls.append({"cwd": cwd, "parent_session": parent_session})
        assert self._next_session is not None
        previous = self._current_session
        self._current_session = self._next_session
        self._next_session = None
        return SessionOperationResult(
            previous=previous,
            current=self._current_session,
            payload=None,
            cancelled=False,
        )

    async def restore_session_operation(self, session_id):
        self.switch_session_calls.append(session_id)
        assert self._next_session is not None
        previous = self._current_session
        self._current_session = self._next_session
        self._next_session = None
        return SessionOperationResult(
            previous=previous,
            current=self._current_session,
            payload=None,
            cancelled=False,
        )

    async def fork_session_operation(
        self, entry_id: str | None, *, position: str = "at"
    ):
        self.fork_session_operation_calls.append((entry_id, position))
        assert self._next_session is not None
        resolved_entry_id = entry_id
        if resolved_entry_id is None:
            resolved_entry_id = self._current_session.session_manager.get_leaf_id()
            if not isinstance(resolved_entry_id, str) or not resolved_entry_id:
                raise ValueError("Cannot clone session: no current entry selected")
        self.fork_session_calls.append(resolved_entry_id)
        selected_text = (
            self._current_session.get_entry_text(resolved_entry_id)
            if entry_id is not None and position == "before"
            else None
        )
        previous = self._current_session
        self._current_session = self._next_session
        self._next_session = None
        return SessionOperationResult(
            previous=previous,
            current=self._current_session,
            payload=selected_text,
            cancelled=False,
        )

    def list_session_summaries(self) -> list[object]:
        self.list_session_summaries_calls += 1
        return list(self.session_summaries)

    def find_session_summaries(self, query: SessionQuery | None = None) -> list[object]:
        self.find_session_summaries_calls.append(query)
        return self._find_session_summaries(query)

    def find_all_session_summaries(
        self, query: SessionQuery | None = None
    ) -> list[object]:
        self.find_all_session_summaries_calls.append(query)
        return self._find_session_summaries(query)

    def refresh_session_index(self) -> list[object]:
        self.refresh_session_index_calls += 1
        return list(self.session_summaries)

    def refresh_all_session_indexes(self) -> list[object]:
        self.refresh_all_session_indexes_calls += 1
        return list(self.session_summaries)

    def list_indexed_session_summaries(self) -> list[object]:
        self.list_indexed_session_summaries_calls += 1
        return list(self.session_summaries)

    def list_all_indexed_session_summaries(self) -> list[object]:
        self.list_all_indexed_session_summaries_calls += 1
        return list(self.session_summaries)

    def find_indexed_session_summaries(
        self, query: SessionQuery | None = None
    ) -> list[object]:
        self.find_indexed_session_summaries_calls.append(query)
        return self._find_session_summaries(query)

    def find_all_indexed_session_summaries(
        self, query: SessionQuery | None = None
    ) -> list[object]:
        self.find_all_indexed_session_summaries_calls.append(query)
        return self._find_session_summaries(query)

    def _find_session_summaries(
        self, query: SessionQuery | None = None
    ) -> list[object]:
        if query is None:
            return list(self.session_summaries)

        def matches(summary: object) -> bool:
            if query.cwd is not None and getattr(summary, "cwd", None) != query.cwd:
                return False
            if (
                query.name is not None
                and query.name.lower() not in str(getattr(summary, "name", "")).lower()
            ):
                return False
            if (
                query.parent_session is not None
                and getattr(summary, "parent_session", None) != query.parent_session
            ):
                return False
            if query.text is not None:
                haystack = " ".join(
                    str(value)
                    for value in (
                        getattr(summary, "session_id", ""),
                        getattr(summary, "cwd", ""),
                        getattr(summary, "name", ""),
                        getattr(summary, "last_message_preview", ""),
                    )
                ).lower()
                if query.text.lower() not in haystack:
                    return False
            return True

        filtered = [summary for summary in self.session_summaries if matches(summary)]
        return filtered[: query.limit] if query.limit is not None else filtered

    def get_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]:
        self.get_diagnostics_calls.append(query)
        return self._filter_diagnostics(
            query, records=list(self.diagnostics or self._current_session.diagnostics)
        )

    def get_session_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]:
        self.get_session_diagnostics_calls.append(query)
        records = list(self.diagnostics or self._current_session.diagnostics)
        records = [
            record
            for record in records
            if record.session_id == self._current_session.session_id
        ]
        return self._filter_diagnostics(query, records=records)

    def get_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary:
        self.get_diagnostics_summary_calls.append(query)
        return _diagnostics_summary(
            self._filter_diagnostics(
                query,
                records=list(self.diagnostics or self._current_session.diagnostics),
            )
        )

    def get_session_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary:
        self.get_session_diagnostics_summary_calls.append(query)
        records = list(self.diagnostics or self._current_session.diagnostics)
        records = [
            record
            for record in records
            if record.session_id == self._current_session.session_id
        ]
        return _diagnostics_summary(self._filter_diagnostics(query, records=records))

    def get_packages(
        self, *, catalog_path: str | None = None
    ) -> list[dict[str, object]]:
        self.get_packages_calls.append(catalog_path)
        return self._current_session.get_packages(catalog_path=catalog_path)

    async def materialize_package(self, source: str) -> dict[str, object]:
        self.materialize_package_calls.append(source)
        return {
            "source": source,
            "name": "review-pack",
            "lifecycle": "materialization_pending",
            "targetPath": "/tmp/packages/review-pack",
            "errorMessage": None,
        }

    async def install_package(self, source: str) -> dict[str, object]:
        self.install_package_calls.append(source)
        return {
            "source": source,
            "name": "review-pack",
            "lifecycle": "installed",
            "targetPath": "/tmp/packages/review-pack",
            "errorMessage": None,
        }

    async def update_package(self, source: str) -> dict[str, object]:
        self.update_package_calls.append(source)
        return {
            "source": source,
            "name": "review-pack",
            "lifecycle": "installed",
            "targetPath": "/tmp/packages/review-pack",
            "errorMessage": None,
        }

    async def update_packages(self) -> list[dict[str, object]]:
        self.update_packages_calls += 1
        return [
            {
                "source": "https://packages.example.invalid/review-pack.git",
                "name": "review-pack",
                "lifecycle": "installed",
                "targetPath": "/tmp/packages/review-pack",
                "errorMessage": None,
            }
        ]

    async def check_package_updates(self) -> list[dict[str, object]]:
        self.check_package_updates_calls += 1
        return [
            {
                "source": "https://packages.example.invalid/review-pack.git",
                "name": "review-pack",
                "currentCommit": "a",
                "availableCommit": "b",
                "pinned": False,
            }
        ]

    async def remove_package(self, source: str) -> dict[str, object]:
        self.remove_package_calls.append(source)
        return {
            "source": source,
            "name": "review-pack",
            "lifecycle": "remote_registered",
            "targetPath": "/tmp/packages/review-pack",
            "errorMessage": None,
        }

    async def uninstall_package(self, source: str) -> dict[str, object]:
        self.uninstall_package_calls.append(source)
        return {
            "source": source,
            "name": "review-pack",
            "lifecycle": "remote_registered",
            "targetPath": "/tmp/packages/review-pack",
            "errorMessage": None,
        }

    def _filter_diagnostics(
        self,
        query: DiagnosticsQuery | None,
        *,
        records: list[DiagnosticRecord],
    ) -> list[DiagnosticRecord]:
        if query is None:
            return records
        if query.phase is not None:
            records = [record for record in records if record.phase == query.phase]
        if query.source is not None:
            records = [record for record in records if record.source == query.source]
        if query.level is not None:
            records = [record for record in records if record.type == query.level]
        if query.session_id is not None:
            records = [
                record for record in records if record.session_id == query.session_id
            ]
        if query.entry_id is not None:
            records = [
                record for record in records if record.entry_id == query.entry_id
            ]
        if query.code is not None:
            records = [record for record in records if record.code == query.code]
        return records[-query.limit :] if query.limit is not None else records


def _diagnostics_summary(records: list[DiagnosticRecord]) -> DiagnosticSummary:
    latest_error = next(
        (record for record in reversed(records) if record.type == "error"), None
    )
    by_code: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_phase: dict[str, int] = {}
    for record in records:
        count = max(record.occurrence_count, 1)
        by_code[record.code] = by_code.get(record.code, 0) + count
        by_source[record.source] = by_source.get(record.source, 0) + count
        by_phase[record.phase] = by_phase.get(record.phase, 0) + count
    return DiagnosticSummary(
        total_count=sum(by_code.values()),
        error_count=sum(
            max(record.occurrence_count, 1)
            for record in records
            if record.type == "error"
        ),
        warning_count=sum(
            max(record.occurrence_count, 1)
            for record in records
            if record.type == "warning"
        ),
        info_count=sum(
            max(record.occurrence_count, 1)
            for record in records
            if record.type == "info"
        ),
        by_code=by_code,
        by_source=by_source,
        by_phase=by_phase,
        latest_error=latest_error,
    )
