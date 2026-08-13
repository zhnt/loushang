from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loushang.agent import AgentTool
from loushang.ai import ApiKeyAuth, CallOptions, get_model
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import (
    Capabilities,
    Model,
    load_model_registry_from_directory,
    load_model_registry_from_file,
    resolve_model_endpoint,
)
from loushang.ai.model.registry import ModelRegistry
from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage, UserMessage
from loushang.coding import (
    AgentSession,
    AgentSessionRuntime,
    create_agent_session_runtime,
    create_services,
)
from loushang.harness.tools.core import ToolDefinition

ENV_EXAMPLES_MODEL_CATALOG = "LOUSHANG_EXAMPLES_MODEL_CATALOG"
ENV_EXAMPLES_SESSION_DIR = "LOUSHANG_EXAMPLES_SESSION_DIR"

_OVERRIDE_REGISTRY: ModelRegistry | None = None


def _resolve_session_dir(default_session_dir: Path) -> Path:
    raw = os.environ.get(ENV_EXAMPLES_SESSION_DIR, "").strip()
    if not raw:
        return default_session_dir
    return Path(raw).expanduser().resolve()


def _resolve_model_catalog() -> Path | None:
    raw = os.environ.get(ENV_EXAMPLES_MODEL_CATALOG, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _resolve_model(provider: str, endpoint: str, model_id: str) -> Model:
    registry = _resolve_model_registry()
    if registry is not None:
        catalog = _resolve_model_catalog()
        try:
            return registry.get_model(provider, endpoint, model_id)
        except Exception as exc:
            raise RuntimeError(
                f"resolve model from custom catalog failed: {catalog}"
            ) from exc
    return get_model(provider, endpoint, model_id)


def _resolve_model_registry() -> ModelRegistry | None:
    catalog = _resolve_model_catalog()
    if catalog is None:
        return None
    global _OVERRIDE_REGISTRY
    if _OVERRIDE_REGISTRY is None:
        try:
            loader = (
                load_model_registry_from_directory
                if catalog.is_dir()
                else load_model_registry_from_file
            )
            _OVERRIDE_REGISTRY = loader(catalog)
        except FileNotFoundError as exc:
            raise RuntimeError(f"model catalog not found: {catalog}") from exc
        except Exception as exc:
            raise RuntimeError(f"failed to load model catalog: {catalog}") from exc
    return _OVERRIDE_REGISTRY


MODEL_ID = "kimi-for-coding"
KIMI_PROVIDER_ID = "kimi-code"
DEFAULT_SYSTEM_PROMPT = (
    "You are Kimi, an AI assistant provided by Moonshot AI. "
    "You are better at Chinese and English conversations and provide helpful, accurate answers."
)


def offline_model() -> Model:
    return Model(
        id="offline-extension-demo",
        name="Offline Extension Demo",
        provider="offline",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def resolve_kimi_model_id(
    *, default: str = MODEL_ID, endpoint_id: str = "kimi-code-anthropic"
) -> str:
    if endpoint_id in {"kimi-code-anthropic", "kimi-code-openai"}:
        return default
    return os.getenv("KIMI_MODEL_NAME", "").strip() or default


def build_kimi_model(
    *, endpoint_id: str = "kimi-code-anthropic", model_id: str | None = None
) -> Model:
    resolved_model_id = (
        model_id
        if model_id is not None
        else resolve_kimi_model_id(endpoint_id=endpoint_id)
    )
    try:
        return _resolve_model(KIMI_PROVIDER_ID, endpoint_id, resolved_model_id)
    except Exception:
        if resolved_model_id != MODEL_ID:
            return _resolve_model(KIMI_PROVIDER_ID, endpoint_id, MODEL_ID)
        raise


def describe_model(model: Model) -> dict[str, str | None]:
    endpoint = resolve_model_endpoint(model)
    return {
        "provider": model.provider_id,
        "model": model.id,
        "endpoint": model.endpoint_id,
        "api": endpoint.api if endpoint is not None else None,
        "base_url": endpoint.base_url if endpoint is not None else None,
    }


def resolve_api_key() -> str:
    api_key = os.environ.get("KIMI_CODE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Please export KIMI_CODE_API_KEY before running online extension examples."
        )
    return api_key


def usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost=None,
    )


def assistant_text_message(text: str) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="offline",
        endpoint="offline",
        model="offline-extension-demo",
        response_id=None,
        usage=usage(),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def assistant_tool_call_message(
    tool_name: str, arguments: dict[str, object]
) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="tc_1",
                name=tool_name,
                arguments=arguments,
            )
        ],
        api="anthropic-messages",
        provider="offline",
        endpoint="offline",
        model="offline-extension-demo",
        response_id=None,
        usage=usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


def stream_with_final_message(message: AssistantMessage) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def _feed() -> None:
        stream.push({"type": "start", "partial": message})
        if message.content and isinstance(message.content[0], TextPart):
            stream.push({"type": "text_start", "content_index": 0, "partial": message})
            stream.push(
                {
                    "type": "text_delta",
                    "content_index": 0,
                    "delta": message.content[0].text,
                    "partial": message,
                }
            )
            stream.push(
                {
                    "type": "text_end",
                    "content_index": 0,
                    "content": message.content[0].text,
                    "partial": message,
                }
            )
        elif message.content and isinstance(message.content[0], ToolCall):
            stream.push(
                {"type": "toolcall_start", "content_index": 0, "partial": message}
            )
            stream.push(
                {
                    "type": "toolcall_delta",
                    "content_index": 0,
                    "delta": str(message.content[0].arguments),
                    "partial": message,
                }
            )
            stream.push(
                {
                    "type": "toolcall_end",
                    "content_index": 0,
                    "tool_call": message.content[0],
                    "partial": message,
                }
            )
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})  # type: ignore[typeddict-item]

    asyncio.create_task(_feed())
    return stream


def build_runtime(
    *,
    session_dir: Path,
    stream_fn,
    system_prompt: str,
    tools: list[ToolDefinition] | None = None,
    persist: bool = False,
):
    services = _build_bootstrap_services()
    return create_agent_session_runtime(
        session_dir=session_dir,
        model=offline_model(),
        stream_fn=stream_fn,
        system_prompt=system_prompt,
        tools=tools or [],
        persist=persist,
        services=services,
    )


def create_kimi_runtime(
    *,
    cwd: str | Path,
    model: Model | None = None,
    system_prompt: str,
    tools: list[AgentTool[Any]] | None = None,
    persist: bool = False,
) -> AgentSessionRuntime:
    working_dir = Path(cwd).resolve()
    session_dir = _resolve_session_dir(working_dir / ".loushang-sessions")
    services = _build_bootstrap_services()
    return create_agent_session_runtime(
        session_dir=session_dir,
        model=model or build_kimi_model(),
        system_prompt=system_prompt,
        tools=list(tools or []),
        persist=persist,
        services=services,
    )


def _build_bootstrap_services():
    ai_model_registry = _resolve_model_registry()
    if ai_model_registry is None:
        return None
    return create_services(ai_model_registry=ai_model_registry)


async def create_kimi_runtime_session(
    *,
    cwd: str | Path,
    model: Model | None = None,
    system_prompt: str,
    tools: list[AgentTool[Any]] | None = None,
    persist: bool = False,
) -> tuple[AgentSessionRuntime, AgentSession]:
    working_dir = Path(cwd).resolve()
    runtime = create_kimi_runtime(
        cwd=working_dir,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        persist=persist,
    )
    session = await runtime.create_session(cwd=str(working_dir))
    session.agent.call_options = CallOptions(auth=ApiKeyAuth(resolve_api_key()))
    return runtime, session


def print_messages(session) -> None:
    for index, message in enumerate(session.get_session_context().messages, start=1):
        role = getattr(message, "role", "unknown")
        content = getattr(message, "content", [])
        text = " ".join(
            part.text for part in content if getattr(part, "type", None) == "text"
        )
        print(f"{index}. {role}: {text}")


def attach_stream_printer(
    session: AgentSession, *, show_thinking: bool = False
) -> None:
    thinking_open = False

    def on_event(event: dict) -> None:
        nonlocal thinking_open
        event_type = event.get("type")
        if event_type == "message_update":
            assistant_event = event.get("assistant_message_event", {})
            assistant_event_type = assistant_event.get("type")
            if assistant_event_type == "thinking_delta" and show_thinking:
                if not thinking_open:
                    print("\n[thinking] ", end="", flush=True)
                    thinking_open = True
                print(assistant_event.get("delta", ""), end="", flush=True)
            elif (
                assistant_event_type == "thinking_end"
                and show_thinking
                and thinking_open
            ):
                print()
                thinking_open = False
            elif assistant_event_type == "text_delta":
                if thinking_open:
                    print("\n[answer] ", end="", flush=True)
                    thinking_open = False
                print(assistant_event.get("delta", ""), end="", flush=True)
        elif event_type == "message_end":
            if thinking_open:
                print()
                thinking_open = False
            print()
        elif event_type == "tool_execution_start":
            print(f"\n[tool start: {event.get('tool_name')}({event.get('args')})]")
        elif event_type == "tool_execution_end":
            result = event.get("result")
            if result and hasattr(result, "content"):
                content_text = "".join(
                    part.text
                    for part in result.content
                    if getattr(part, "type", None) == "text"
                )
                print(f"[tool end: {content_text}]")

    session.subscribe(on_event)


def latest_tool_results(session) -> list[Any]:
    return [
        message
        for message in session.get_session_context().messages
        if getattr(message, "role", None) == "toolResult"
    ]


def latest_user_text(context_messages: list[object]) -> str:
    last_message = context_messages[-1] if context_messages else None
    if isinstance(last_message, UserMessage):
        if isinstance(last_message.content, str):
            return last_message.content
        return " ".join(
            part.text
            for part in last_message.content
            if getattr(part, "type", None) == "text"
        )
    return ""
