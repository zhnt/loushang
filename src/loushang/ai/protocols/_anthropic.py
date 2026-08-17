from __future__ import annotations

from typing import Any, Literal, cast

from loushang.ai.model.domain import AnthropicMessagesConfig
from loushang.ai.options import CacheRetention
from loushang.ai.protocols._helpers import (
    get_header_case_insensitive,
    set_header_case_insensitive,
)
from loushang.ai.utils import sanitize_surrogates


class AnthropicMessagesProtocol:
    """
    Anthropic provider shared helpers to align semantics with pi-ai across SDK/HTTPX impls.
    """

    @staticmethod
    def supports_adaptive_thinking(
        adapter_config: AnthropicMessagesConfig | None,
    ) -> bool:
        return (
            adapter_config is not None
            and adapter_config.thinking_mode == "adaptive"
        )

    @staticmethod
    def map_thinking_level_to_effort(
        level: str | None,
        adapter_config: AnthropicMessagesConfig | None,
    ) -> Literal["low", "medium", "high", "xhigh", "max"] | None:
        if level is None or adapter_config is None:
            return None
        effort = adapter_config.reasoning_effort_map.get(level)
        if effort in ("low", "medium", "high", "xhigh", "max"):
            return cast(Literal["low", "medium", "high", "xhigh", "max"], effort)
        return None

    @staticmethod
    def resolve_cache_retention(
        cache_retention: CacheRetention | None,
    ) -> CacheRetention:
        if cache_retention in ("none", "short", "long"):
            return cache_retention  # type: ignore[return-value]
        return "short"  # default

    @classmethod
    def get_cache_control(
        cls,
        base_url: str | None,
        cache_retention: CacheRetention | None,
        *,
        supports_long_cache_retention: bool | None = None,
    ):
        retention = cls.resolve_cache_retention(cache_retention)
        if retention == "none":
            return {"retention": retention, "cacheControl": None}
        supports_long = bool(supports_long_cache_retention)
        ttl = "1h" if retention == "long" and supports_long else None
        cache_control = {"type": "ephemeral", **({"ttl": ttl} if ttl else {})}
        return {"retention": retention, "cacheControl": cache_control}

    @staticmethod
    def merge_headers(*sources: dict[str, str] | None) -> dict[str, str]:
        out: dict[str, str] = {}
        for s in sources:
            if s:
                out.update(s)
        return out

    @classmethod
    def apply_beta_headers(
        cls,
        *,
        existing_headers: dict[str, str] | None,
        need_interleaved_beta: bool,
        force_fine_grained_tools: bool = True,
    ) -> dict[str, str]:
        features: list[str] = []
        if force_fine_grained_tools:
            features.append("fine-grained-tool-streaming-2025-05-14")
        if need_interleaved_beta:
            features.append("interleaved-thinking-2025-05-14")
        if not features:
            return dict(existing_headers or {})
        out = dict(existing_headers or {})
        current = get_header_case_insensitive(out, "anthropic-beta")
        if current:
            cur = {p.strip() for p in current.split(",") if p.strip()}
            for f in features:
                cur.add(f)
            set_header_case_insensitive(
                out,
                "anthropic-beta",
                ",".join(sorted(cur)),
            )
        else:
            set_header_case_insensitive(out, "anthropic-beta", ",".join(features))
        return out

    @classmethod
    def should_inject_fine_grained_tools(
        cls,
        *,
        adapter_config: AnthropicMessagesConfig | None,
        headers: dict[str, str] | None,
    ) -> bool:
        if adapter_config is not None and adapter_config.fine_grained_tools is False:
            return False
        if headers:
            h = {k.lower(): v for k, v in headers.items()}
            if "anthropic-beta" in h:
                return True
        if adapter_config is not None and adapter_config.fine_grained_tools is True:
            return True
        return False

    @classmethod
    def should_inject_interleaved_thinking(
        cls,
        *,
        reasoning_enabled: bool | None,
        adapter_config: AnthropicMessagesConfig | None,
    ) -> bool:
        if adapter_config is not None and adapter_config.interleaved_thinking is False:
            return False
        if reasoning_enabled is not True:
            return False
        if cls.supports_adaptive_thinking(adapter_config):
            return False
        return True

    @staticmethod
    def assistant_block_to_anthropic_payload(block: object) -> dict[str, Any] | None:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", "")
            if isinstance(text, str) and text.strip():
                return {"type": "text", "text": sanitize_surrogates(text)}
            return None

        if block_type == "toolCall":
            tool_id = getattr(block, "id", None)
            tool_name = getattr(block, "name", None)
            tool_args = getattr(block, "arguments", {}) or {}
            if isinstance(tool_id, str) and tool_id:
                return {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name or "",
                    "input": tool_args or {},
                }
            return None

        if block_type == "thinking":
            thinking = getattr(block, "thinking", "")
            if not isinstance(thinking, str) or not thinking.strip():
                return None

            signature = getattr(block, "thinking_signature", None)
            redacted = getattr(block, "redacted", False)

            if redacted:
                if isinstance(signature, str) and signature.strip():
                    return {"type": "redacted_thinking", "data": signature}
                return {"type": "text", "text": sanitize_surrogates(thinking)}

            if isinstance(signature, str) and signature.strip():
                return {
                    "type": "thinking",
                    "thinking": sanitize_surrogates(thinking),
                    "signature": signature,
                }
            return {"type": "text", "text": sanitize_surrogates(thinking)}

        return None

    @staticmethod
    def tool_result_content_to_anthropic_payload(
        content: object,
    ) -> str | list[dict[str, Any]]:
        if not isinstance(content, list):
            return "(empty)"

        if all(getattr(part, "type", None) == "text" for part in content):
            text_parts = [getattr(part, "text", "") for part in content]
            text = "\n".join(
                part for part in text_parts if isinstance(part, str) and part.strip()
            )
            return sanitize_surrogates(text) or "(empty)"

        blocks: list[dict[str, Any]] = []
        for part in content:
            part_type = getattr(part, "type", None)
            if part_type == "text":
                text = getattr(part, "text", "")
                if isinstance(text, str) and text.strip():
                    blocks.append({"type": "text", "text": sanitize_surrogates(text)})
            elif part_type == "image":
                data = getattr(part, "data", "")
                mime = getattr(part, "mime_type", "")
                if isinstance(data, str) and data and isinstance(mime, str) and mime:
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime,
                                "data": data,
                            },
                        }
                    )

        if not blocks:
            return "(empty)"
        if len(blocks) == 1 and blocks[0]["type"] == "text":
            return blocks[0]["text"]
        return blocks
