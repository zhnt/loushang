from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

from loushang.coding.types import ModelSelection


class RecordingTerminalContext:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __enter__(self) -> RecordingTerminalContext:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def consume_control_events(self, events: tuple[object, ...]) -> None:
        self.events.extend(events)


class AppleShiftEnterTerminalContext:
    def __init__(self) -> None:
        self.return_key_count = 0

    def __enter__(self) -> AppleShiftEnterTerminalContext:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def normalize_input_chunk(self, data: str) -> str:
        if data != "\r":
            return data
        self.return_key_count += 1
        if self.return_key_count == 1:
            return "\x1b[13;2u"
        return data


class RecordingTerminalMode:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def __enter__(self) -> RecordingTerminalMode:
        self.calls.append("mode:enter")
        return self

    def __exit__(self, *_args: object) -> bool:
        self.calls.append("mode:exit")
        return False


class ModelPlaybackSession:
    def __init__(self) -> None:
        self.current_model = ModelSelection(provider="moonshot", model_id="kimi-for-coding")
        self.models = [
            ModelSelection(provider="moonshot", model_id="kimi-for-coding"),
            ModelSelection(provider="openai", model_id="gpt-5.4"),
        ]

    def get_model_selection(self) -> ModelSelection:
        return self.current_model

    def get_available_models(self) -> list[ModelSelection]:
        return self.models

    async def set_model(self, selection: object) -> None:
        if isinstance(selection, ModelSelection):
            self.current_model = selection


class SessionCommandPlaybackSession:
    def __init__(self) -> None:
        self.commands: list[tuple[str, str]] = []
        self.prompts: list[str] = []

    def list_commands(self) -> list[object]:
        return [
            SimpleNamespace(
                name="name",
                description="Set session display name",
                source="builtin",
                argument_hint="<name>",
            ),
            SimpleNamespace(
                name="export",
                description="Export session history",
                source="builtin",
                argument_hint="<path>",
            ),
            SimpleNamespace(
                name="review",
                description="Prompt fragment review",
                source="prompt",
                argument_hint="<focus>",
            ),
            SimpleNamespace(
                name="debugging",
                description="Debugging skill",
                source="skill",
                argument_hint="<task>",
            ),
        ]

    async def execute_command_async(self, invocation_name: str, args: str) -> object:
        self.commands.append((invocation_name, args))
        if invocation_name == "export":
            return SimpleNamespace(
                invocation_name=invocation_name,
                result={
                    "source": "builtin",
                    "command": invocation_name,
                    "status": "error",
                    "message": f"Export failed: {args}",
                },
            )
        return SimpleNamespace(
            invocation_name=invocation_name,
            result={
                "source": "builtin",
                "command": invocation_name,
                "status": "ok",
                "message": f"Session name set: {args}",
            },
        )

    async def prompt(self, text: str, **_kwargs: object) -> None:
        self.prompts.append(text)


def recording_drain(calls: list[str]) -> Callable[..., str]:
    def drain(*_args: object, **_kwargs: object) -> str:
        calls.append("drain")
        return ""

    return drain


__all__ = [
    "AppleShiftEnterTerminalContext",
    "ModelPlaybackSession",
    "RecordingTerminalContext",
    "RecordingTerminalMode",
    "SessionCommandPlaybackSession",
    "recording_drain",
]
