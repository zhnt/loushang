from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
while not (REPO_ROOT / "src").exists() and REPO_ROOT.parent != REPO_ROOT:
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loushang.agent import AgentTool, AgentToolResult, ThinkingLevel
from loushang.ai import ApiKeyAuth, CallOptions, TextPart, get_model
from loushang.ai.model import (
    Model,
    load_model_registry_from_directory,
    load_model_registry_from_file,
    resolve_model_endpoint,
)
from loushang.ai.model.registry import ModelRegistry
from loushang.coding import (
    AgentSession,
    AgentSessionRuntime,
    SessionManager,
    create_agent_session,
    create_agent_session_runtime,
    create_services,
)

ENV_EXAMPLES_MODEL_CATALOG = "LOUSHANG_EXAMPLES_MODEL_CATALOG"
ENV_EXAMPLES_SESSION_DIR = "LOUSHANG_EXAMPLES_SESSION_DIR"
ENV_EXAMPLES_ARTIFACT_ROOT = "LOUSHANG_EXAMPLES_ARTIFACT_ROOT"

_OVERRIDE_REGISTRY: ModelRegistry | None = None


def _resolve_session_dir(default_session_dir: Path) -> Path:
    raw = os.environ.get(ENV_EXAMPLES_SESSION_DIR, "").strip()
    if not raw:
        return default_session_dir
    return Path(raw).expanduser().resolve()


def _resolve_model_catalog() -> Path | None:
    raw = os.environ.get(ENV_EXAMPLES_MODEL_CATALOG, "").strip()
    if not raw:
        artifact_root = os.environ.get(ENV_EXAMPLES_ARTIFACT_ROOT, "").strip()
        if artifact_root:
            candidate_dir = Path(artifact_root).expanduser() / "models"
            if candidate_dir.is_dir() and any(candidate_dir.glob("*.json")):
                return candidate_dir
            candidate_file = Path(artifact_root).expanduser() / "models.json"
            if candidate_file.is_file():
                return candidate_file

        return None
    return Path(raw).expanduser()


def _resolve_model(provider: str, endpoint: str, model_id: str) -> Model:
    catalog = _resolve_model_catalog()
    registry = _resolve_model_registry()
    if registry is not None:
        try:
            return registry.get_model(provider, endpoint, model_id)
        except Exception as exc:
            raise RuntimeError(f"resolve model from custom catalog failed: {catalog}") from exc
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


@dataclass
class CalcTool:
    name: str = "calculate"
    description: str = "Perform basic arithmetic calculations"
    parameters: dict[str, Any] | None = None
    label: str = "Calculator"
    prepare_arguments: None = None

    def __post_init__(self) -> None:
        if self.parameters is None:
            self.parameters = {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate, e.g., '23 * 45' or '1 + 1'",
                    }
                },
                "required": ["expression"],
            }

    async def execute(
        self,
        tool_call_id: str,
        params: dict[str, Any],
        signal: object | None = None,
        on_update: Any = None,
    ) -> AgentToolResult[dict[str, Any]]:
        expression = params.get("expression", "")
        try:
            result = eval(expression, {"__builtins__": {}}, {})
            return AgentToolResult(
                content=[TextPart(type="text", text=str(result))],
                details={"expression": expression, "result": result},
            )
        except Exception as error:
            return AgentToolResult(
                content=[TextPart(type="text", text=f"Error: {error}")],
                details={"error": str(error)},
            )


def resolve_kimi_model_id(default: str = MODEL_ID, *, endpoint_id: str = "kimi-code-anthropic") -> str:
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
        raise RuntimeError("请先导出 KIMI_CODE_API_KEY 环境变量")
    return api_key


def create_kimi_session(
    *,
    cwd: str | Path | None = None,
    model: Model | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel = "off",
    tools: list[AgentTool[Any]] | None = None,
) -> AgentSession:
    working_dir = Path(cwd or Path.cwd()).resolve()
    session_dir = _resolve_session_dir(working_dir / ".loushang-sessions")
    session_manager = SessionManager.new(
        session_dir=session_dir,
        cwd=str(working_dir),
        persist=False,
    )
    session = create_agent_session(
        session_manager=session_manager,
        model=model or build_kimi_model(),
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        thinking_level=thinking_level,
        tools=list(tools or []),
        services=_build_bootstrap_services(),
    )
    session.agent.call_options = CallOptions(auth=ApiKeyAuth(resolve_api_key()))
    return session


def create_kimi_runtime(
    *,
    cwd: str | Path | None = None,
    model: Model | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel = "off",
    tools: list[AgentTool[Any]] | None = None,
    persist: bool = False,
) -> AgentSessionRuntime:
    working_dir = Path(cwd or Path.cwd()).resolve()
    session_dir = _resolve_session_dir(working_dir / ".loushang-sessions")
    return create_agent_session_runtime(
        session_dir=session_dir,
        model=model or build_kimi_model(),
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        thinking_level=thinking_level,
        tools=list(tools or []),
        persist=persist,
        services=_build_bootstrap_services(),
    )


def _build_bootstrap_services():
    ai_model_registry = _resolve_model_registry()
    if ai_model_registry is None:
        return None
    return create_services(ai_model_registry=ai_model_registry)


async def create_kimi_runtime_session(
    *,
    cwd: str | Path | None = None,
    model: Model | None = None,
    system_prompt: str | None = None,
    thinking_level: ThinkingLevel = "off",
    tools: list[AgentTool[Any]] | None = None,
    persist: bool = False,
) -> tuple[AgentSessionRuntime, AgentSession]:
    working_dir = Path(cwd or Path.cwd()).resolve()
    runtime = create_kimi_runtime(
        cwd=working_dir,
        model=model,
        system_prompt=system_prompt,
        thinking_level=thinking_level,
        tools=tools,
        persist=persist,
    )
    session = await runtime.create_session(cwd=str(working_dir))
    session.agent.call_options = CallOptions(auth=ApiKeyAuth(resolve_api_key()))
    return runtime, session


def attach_stream_printer(session: AgentSession, *, show_thinking: bool = False) -> None:
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
            elif assistant_event_type == "thinking_end" and show_thinking and thinking_open:
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
            print(f"\n[使用工具: {event.get('tool_name')}({event.get('args')})]")
        elif event_type == "tool_execution_end":
            result = event.get("result")
            if result and hasattr(result, "content"):
                content_text = "".join(
                    part.text for part in result.content if getattr(part, "type", None) == "text"
                )
                print(f"[工具结果: {content_text}]")

    session.subscribe(on_event)


def print_message_summary(session: AgentSession) -> None:
    messages = session.get_session_context().messages
    print("Messages:")
    for index, message in enumerate(messages, start=1):
        role = getattr(message, "role", "unknown")
        content = getattr(message, "content", [])
        text = " ".join(
            part.text for part in content if getattr(part, "type", None) == "text"
        )
        if text:
            print(f"{index}. {role}: {text}")
            continue
        print(f"{index}. {role}: {text} (content_types={ [getattr(part, 'type', 'unknown') for part in content] }, error={getattr(message, 'error_message', None)}, stop_reason={getattr(message, 'stop_reason', None)})")


def make_appended_prompt(extra_instructions: str) -> str:
    return f"{DEFAULT_SYSTEM_PROMPT}\n\nAdditional Instructions:\n{extra_instructions}"
