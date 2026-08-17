from __future__ import annotations

import re
from re import Pattern

from loushang.ai.types import AssistantMessage

# 与 pi-ai 等价的 Provider 溢出检测正则（大小写不敏感）
_OVERFLOW_PATTERNS: tuple[Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in [
        r"prompt is too long",  # Anthropic
        r"input is too long for requested model",  # Amazon Bedrock
        r"exceeds the context window",  # OpenAI (Completions & Responses)
        r"input token count.*exceeds the maximum",  # Google (Gemini)
        r"maximum prompt length is \d+",  # xAI (Grok)
        r"reduce the length of the messages",  # Groq
        r"maximum context length is \d+ tokens",  # OpenRouter
        r"exceeds the limit of \d+",  # GitHub Copilot
        r"exceeds the available context size",  # llama.cpp server
        r"greater than the context length",  # LM Studio
        r"context window exceeds limit",  # MiniMax
        r"exceeded model token limit",  # Kimi For Coding
        r"too large for model with \d+ maximum context length",  # Mistral
        r"model_context_window_exceeded",  # z.ai (非常规)
        r"context[_ ]length[_ ]exceeded",  # 通用
        r"too many tokens",  # 通用
        r"token limit exceeded",  # 通用
    ]
)

_CEREBRAS_PATTERN: Pattern[str] = re.compile(
    r"^4(00|13)\s*(status code)?\s*\(no body\)", re.IGNORECASE
)


def is_context_overflow(
    message: AssistantMessage, context_window: int | None = None
) -> bool:
    error_info = getattr(message, "error_info", None)
    if (
        getattr(message, "stop_reason", None) == "error"
        and isinstance(error_info, dict)
        and error_info.get("code")
        in {
            "context_overflow",
            "request_too_large",
        }
    ):
        return True
    # 情况 1：错误型溢出：根据 error_message 文案匹配
    if getattr(message, "stop_reason", None) == "error":
        error_message = getattr(message, "error_message", None)
        if isinstance(error_message, str) and error_message:
            if any(p.search(error_message) for p in _OVERFLOW_PATTERNS):
                return True
            # Cerebras：400/413 且无 body
            if _CEREBRAS_PATTERN.search(error_message):
                return True

    # 情况 2：静默溢出（成功返回但使用量超过窗口）
    if context_window and getattr(message, "stop_reason", None) == "stop":
        usage = getattr(message, "usage", None)
        if usage is not None:
            # 我们的 Usage: input, cache_read
            input_tokens = int(getattr(usage, "input", 0)) + int(
                getattr(usage, "cache_read", 0)
            )
            if input_tokens > int(context_window):
                return True

            total_tokens = int(getattr(usage, "total_tokens", 0))
            if total_tokens > int(context_window) and _message_has_no_content(message):
                return True

            if (
                total_tokens >= int(context_window * 0.95)
                and int(getattr(usage, "output", 0)) <= 1
                and _message_has_no_content(message)
            ):
                return True

    return False


def _message_has_no_content(message: AssistantMessage) -> bool:
    content = getattr(message, "content", None)
    if not isinstance(content, list) or not content:
        return True
    return not any(_part_has_content(part) for part in content)


def _part_has_content(part: object) -> bool:
    text = getattr(part, "text", None)
    if isinstance(text, str) and text.strip():
        return True
    thinking = getattr(part, "thinking", None)
    if isinstance(thinking, str) and thinking.strip():
        return True
    data = getattr(part, "data", None)
    if isinstance(data, str) and data.strip():
        return True
    return False


def get_overflow_patterns() -> list[Pattern[str]]:
    return list(_OVERFLOW_PATTERNS)
