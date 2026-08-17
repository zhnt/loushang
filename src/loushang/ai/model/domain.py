from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import InitVar, dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Literal, TypeAlias, cast

Modality = Literal["text", "image"]
ALLOWED_MODALITIES: tuple[Modality, ...] = ("text", "image")
_REASONING_FORMATS = frozenset({"openai", "deepseek", "moonshot", "zai-thinking"})


class _FrozenSequence(tuple[object, ...]):
    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple)):
            return tuple(self) == tuple(other)
        return False

    def __ne__(self, other: object) -> bool:
        return not self == other

    __hash__ = tuple.__hash__


def _normalize_optional_bool_attrs(instance: object, *attrs: str) -> None:
    for attr in attrs:
        value = getattr(instance, attr)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"adapter config field must be a boolean: {attr}")


def _normalize_optional_str_attrs(instance: object, *attrs: str) -> None:
    for attr in attrs:
        value = getattr(instance, attr)
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError(f"adapter config field must be a non-empty string: {attr}")


def _optional_bool_from_raw(raw: Mapping[str, object], key: str) -> bool | None:
    if key not in raw:
        return None
    value = raw[key]
    if isinstance(value, bool):
        return value
    raise ValueError(f"adapter config field must be a boolean: {key}")


def _bool_from_raw(raw: Mapping[str, object], key: str, default: bool) -> bool:
    value = _optional_bool_from_raw(raw, key)
    return default if value is None else value


def _optional_str_from_raw(raw: Mapping[str, object], key: str) -> str | None:
    if key not in raw:
        return None
    value = raw[key]
    if isinstance(value, str) and value:
        return value
    raise ValueError(f"adapter config field must be a non-empty string: {key}")


def _copy_raw_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _copy_raw_value(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_raw_value(entry) for entry in value]
    return value


def _copy_raw_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {key: _copy_raw_value(entry) for key, entry in value.items()}


def _freeze_raw_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_raw_value(entry) for key, entry in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return _FrozenSequence(_freeze_raw_value(entry) for entry in value)
    return value


def _freeze_raw_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(
        {key: _freeze_raw_value(entry) for key, entry in value.items()}
    )


OPENAI_COMPLETIONS_ADAPTER_KEYS = frozenset(
    {
        "store",
        "developerRole",
        "streamingUsage",
        "maxOutputTokensField",
        "reasoningEffort",
        "reasoningEffortMap",
        "strictSchema",
        "assistantReasoningContent",
        "reasoningFormat",
    }
)
OPENAI_RESPONSES_ADAPTER_KEYS = frozenset(
    {
        "developerRole",
        "maxOutputTokens",
        "promptCacheKey",
        "longCacheRetention",
    }
)
ANTHROPIC_MESSAGES_ADAPTER_KEYS = frozenset(
    {
        "fineGrainedTools",
        "interleavedThinking",
        "longCacheRetention",
        "reasoningEffortMap",
        "thinkingMode",
    }
)

_ANTHROPIC_THINKING_MODES = frozenset({"adaptive", "budgeted"})
_ANTHROPIC_REASONING_LEVELS = frozenset(
    {"minimal", "low", "medium", "high", "xhigh"}
)
_ANTHROPIC_REASONING_EFFORTS = frozenset(
    {"low", "medium", "high", "xhigh", "max"}
)


def _string_or_none_dict_from_raw(
    raw: Mapping[str, object],
    key: str,
) -> dict[str, str | None]:
    if key not in raw:
        return {}
    value = raw[key]
    if not isinstance(value, Mapping):
        raise ValueError(f"adapter config field must be a string-or-null map: {key}")
    result: dict[str, str | None] = {}
    for entry_key, entry_value in value.items():
        if not isinstance(entry_key, str) or not (
            entry_value is None or isinstance(entry_value, str)
        ):
            raise ValueError(
                f"adapter config field must be a string-or-null map: {key}"
            )
        result[entry_key] = entry_value
    return result


def _anthropic_reasoning_effort_map_from_raw(
    raw: Mapping[str, object],
) -> dict[str, str | None]:
    return _validate_anthropic_reasoning_effort_map(
        _string_or_none_dict_from_raw(raw, "reasoningEffortMap")
    )


def _validate_anthropic_reasoning_effort_map(
    value: Mapping[str, str | None],
) -> dict[str, str | None]:
    result = dict(value)
    invalid_keys = sorted(set(result).difference(_ANTHROPIC_REASONING_LEVELS))
    invalid_values = sorted(
        {
            value
            for value in result.values()
            if value is not None and value not in _ANTHROPIC_REASONING_EFFORTS
        }
    )
    if invalid_keys or invalid_values:
        raise ValueError(
            "adapter config reasoningEffortMap contains unsupported "
            f"keys={invalid_keys} values={invalid_values}"
        )
    return result


def _with_raw_value(raw: dict[str, object], key: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, dict) and not value:
        return
    raw[key] = value


def _validate_adapter_keys(
    raw: Mapping[str, object],
    allowed_keys: frozenset[str],
) -> None:
    unknown = sorted(set(raw) - allowed_keys)
    if unknown:
        raise ValueError(f"adapter config has unknown keys: {unknown}")


def _set_explicit_adapter_keys(
    instance: object,
    *,
    attr_to_key: Mapping[str, str],
    defaults: Mapping[str, object],
    allowed_keys: frozenset[str],
) -> None:
    explicit_keys = getattr(instance, "_explicit_keys", None)
    if explicit_keys is None:
        explicit_keys = frozenset(
            key
            for attr, key in attr_to_key.items()
            if getattr(instance, attr) != defaults[key]
        )
    else:
        explicit_keys = frozenset(explicit_keys)
        unknown = sorted(set(explicit_keys) - allowed_keys)
        if unknown:
            raise ValueError(f"adapter config has unknown explicit keys: {unknown}")
    object.__setattr__(instance, "_explicit_keys", explicit_keys)


def _adapter_override_raw(config: AdapterConfig) -> dict[str, object]:
    explicit_keys = getattr(config, "_explicit_keys", None)
    if not explicit_keys:
        return {}
    raw = config.to_raw()
    return {key: raw[key] for key in explicit_keys if key in raw}


_OPENAI_COMPLETIONS_ATTR_TO_KEY = {
    "store": "store",
    "developer_role": "developerRole",
    "streaming_usage": "streamingUsage",
    "max_output_tokens_field": "maxOutputTokensField",
    "reasoning_effort": "reasoningEffort",
    "reasoning_effort_map": "reasoningEffortMap",
    "strict_schema": "strictSchema",
    "assistant_reasoning_content": "assistantReasoningContent",
    "reasoning_format": "reasoningFormat",
}
_OPENAI_COMPLETIONS_DEFAULTS = {
    "store": True,
    "developerRole": True,
    "streamingUsage": True,
    "maxOutputTokensField": "max_completion_tokens",
    "reasoningEffort": True,
    "reasoningEffortMap": {},
    "strictSchema": True,
    "assistantReasoningContent": False,
    "reasoningFormat": "openai",
}


_OPENAI_RESPONSES_ATTR_TO_KEY = {
    "developer_role": "developerRole",
    "max_output_tokens": "maxOutputTokens",
    "prompt_cache_key": "promptCacheKey",
    "long_cache_retention": "longCacheRetention",
}
_OPENAI_RESPONSES_DEFAULTS = {
    "developerRole": True,
    "maxOutputTokens": True,
    "promptCacheKey": True,
    "longCacheRetention": True,
}


_ANTHROPIC_MESSAGES_ATTR_TO_KEY = {
    "fine_grained_tools": "fineGrainedTools",
    "interleaved_thinking": "interleavedThinking",
    "long_cache_retention": "longCacheRetention",
    "reasoning_effort_map": "reasoningEffortMap",
    "thinking_mode": "thinkingMode",
}
_ANTHROPIC_MESSAGES_DEFAULTS: dict[str, object] = {
    "fineGrainedTools": None,
    "interleavedThinking": None,
    "longCacheRetention": True,
    "reasoningEffortMap": {},
    "thinkingMode": "budgeted",
}


@dataclass(frozen=True)
class OpenAICompletionsConfig:
    store: bool = True
    developer_role: bool = True
    streaming_usage: bool = True
    max_output_tokens_field: str = "max_completion_tokens"
    reasoning_effort: bool = True
    reasoning_effort_map: Mapping[str, str | None] = field(default_factory=dict)
    strict_schema: bool = True
    assistant_reasoning_content: bool = False
    reasoning_format: str | None = "openai"
    _explicit_keys: frozenset[str] | None = field(
        default=None,
        compare=False,
        repr=False,
        kw_only=True,
    )

    def __post_init__(self) -> None:
        _normalize_optional_bool_attrs(
            self,
            "store",
            "developer_role",
            "streaming_usage",
            "reasoning_effort",
            "strict_schema",
            "assistant_reasoning_content",
        )
        _normalize_optional_str_attrs(
            self,
            "max_output_tokens_field",
            "reasoning_format",
        )
        if self.reasoning_format not in _REASONING_FORMATS:
            raise ValueError(
                f"unsupported reasoningFormat: {self.reasoning_format!r}"
            )
        object.__setattr__(
            self,
            "reasoning_effort_map",
            MappingProxyType(dict(self.reasoning_effort_map)),
        )
        _set_explicit_adapter_keys(
            self,
            attr_to_key=_OPENAI_COMPLETIONS_ATTR_TO_KEY,
            defaults=_OPENAI_COMPLETIONS_DEFAULTS,
            allowed_keys=OPENAI_COMPLETIONS_ADAPTER_KEYS,
        )

    @classmethod
    def from_raw(
        cls,
        raw: Mapping[str, object] | None,
    ) -> "OpenAICompletionsConfig":
        raw = raw or {}
        _validate_adapter_keys(raw, OPENAI_COMPLETIONS_ADAPTER_KEYS)
        return cls(
            store=_bool_from_raw(raw, "store", cls.store),
            developer_role=_bool_from_raw(raw, "developerRole", cls.developer_role),
            streaming_usage=_bool_from_raw(raw, "streamingUsage", cls.streaming_usage),
            max_output_tokens_field=_optional_str_from_raw(
                raw,
                "maxOutputTokensField",
            )
            or cls.max_output_tokens_field,
            reasoning_effort=_bool_from_raw(
                raw,
                "reasoningEffort",
                cls.reasoning_effort,
            ),
            reasoning_effort_map=_string_or_none_dict_from_raw(
                raw,
                "reasoningEffortMap",
            ),
            strict_schema=_bool_from_raw(raw, "strictSchema", cls.strict_schema),
            assistant_reasoning_content=_bool_from_raw(
                raw,
                "assistantReasoningContent",
                cls.assistant_reasoning_content,
            ),
            reasoning_format=_optional_str_from_raw(raw, "reasoningFormat")
            if "reasoningFormat" in raw
            else cls.reasoning_format,
            _explicit_keys=frozenset(raw),
        )

    def to_raw(self) -> dict[str, object]:
        raw: dict[str, object] = {
            "store": self.store,
            "developerRole": self.developer_role,
            "streamingUsage": self.streaming_usage,
            "maxOutputTokensField": self.max_output_tokens_field,
            "reasoningEffort": self.reasoning_effort,
            "strictSchema": self.strict_schema,
            "assistantReasoningContent": self.assistant_reasoning_content,
        }
        _with_raw_value(raw, "reasoningEffortMap", dict(self.reasoning_effort_map))
        _with_raw_value(raw, "reasoningFormat", self.reasoning_format)
        return raw


@dataclass(frozen=True)
class OpenAIResponsesConfig:
    developer_role: bool = True
    max_output_tokens: bool = True
    prompt_cache_key: bool = True
    long_cache_retention: bool = True
    _explicit_keys: frozenset[str] | None = field(
        default=None,
        compare=False,
        repr=False,
        kw_only=True,
    )

    def __post_init__(self) -> None:
        _normalize_optional_bool_attrs(
            self,
            "developer_role",
            "max_output_tokens",
            "prompt_cache_key",
            "long_cache_retention",
        )
        _set_explicit_adapter_keys(
            self,
            attr_to_key=_OPENAI_RESPONSES_ATTR_TO_KEY,
            defaults=_OPENAI_RESPONSES_DEFAULTS,
            allowed_keys=OPENAI_RESPONSES_ADAPTER_KEYS,
        )

    @classmethod
    def from_raw(cls, raw: Mapping[str, object] | None) -> "OpenAIResponsesConfig":
        raw = raw or {}
        _validate_adapter_keys(raw, OPENAI_RESPONSES_ADAPTER_KEYS)
        return cls(
            developer_role=_bool_from_raw(raw, "developerRole", cls.developer_role),
            max_output_tokens=_bool_from_raw(
                raw,
                "maxOutputTokens",
                cls.max_output_tokens,
            ),
            prompt_cache_key=_bool_from_raw(
                raw,
                "promptCacheKey",
                cls.prompt_cache_key,
            ),
            long_cache_retention=_bool_from_raw(
                raw,
                "longCacheRetention",
                cls.long_cache_retention,
            ),
            _explicit_keys=frozenset(raw),
        )

    def to_raw(self) -> dict[str, object]:
        return {
            "developerRole": self.developer_role,
            "maxOutputTokens": self.max_output_tokens,
            "promptCacheKey": self.prompt_cache_key,
            "longCacheRetention": self.long_cache_retention,
        }


@dataclass(frozen=True)
class AnthropicMessagesConfig:
    fine_grained_tools: bool | None = None
    interleaved_thinking: bool | None = None
    long_cache_retention: bool = True
    reasoning_effort_map: Mapping[str, str | None] = field(default_factory=dict)
    thinking_mode: Literal["adaptive", "budgeted"] = "budgeted"
    _explicit_keys: frozenset[str] | None = field(
        default=None,
        compare=False,
        repr=False,
        kw_only=True,
    )

    def __post_init__(self) -> None:
        _normalize_optional_bool_attrs(
            self,
            "fine_grained_tools",
            "interleaved_thinking",
            "long_cache_retention",
        )
        if self.thinking_mode not in _ANTHROPIC_THINKING_MODES:
            raise ValueError(
                f"unsupported Anthropic thinkingMode: {self.thinking_mode!r}"
            )
        reasoning_effort_map = _validate_anthropic_reasoning_effort_map(
            self.reasoning_effort_map
        )
        object.__setattr__(
            self,
            "reasoning_effort_map",
            MappingProxyType(reasoning_effort_map),
        )
        _set_explicit_adapter_keys(
            self,
            attr_to_key=_ANTHROPIC_MESSAGES_ATTR_TO_KEY,
            defaults=_ANTHROPIC_MESSAGES_DEFAULTS,
            allowed_keys=ANTHROPIC_MESSAGES_ADAPTER_KEYS,
        )

    @classmethod
    def from_raw(cls, raw: Mapping[str, object] | None) -> "AnthropicMessagesConfig":
        raw = raw or {}
        _validate_adapter_keys(raw, ANTHROPIC_MESSAGES_ADAPTER_KEYS)
        return cls(
            fine_grained_tools=_optional_bool_from_raw(raw, "fineGrainedTools")
            if "fineGrainedTools" in raw
            else cls.fine_grained_tools,
            interleaved_thinking=_optional_bool_from_raw(raw, "interleavedThinking")
            if "interleavedThinking" in raw
            else cls.interleaved_thinking,
            long_cache_retention=_bool_from_raw(
                raw,
                "longCacheRetention",
                cls.long_cache_retention,
            ),
            reasoning_effort_map=_anthropic_reasoning_effort_map_from_raw(raw),
            thinking_mode=cast(
                Literal["adaptive", "budgeted"],
                (
                    _optional_str_from_raw(raw, "thinkingMode")
                    if "thinkingMode" in raw
                    else cls.thinking_mode
                ),
            ),
            _explicit_keys=frozenset(raw),
        )

    def to_raw(self) -> dict[str, object]:
        raw: dict[str, object] = {
            "longCacheRetention": self.long_cache_retention,
        }
        _with_raw_value(raw, "fineGrainedTools", self.fine_grained_tools)
        _with_raw_value(raw, "interleavedThinking", self.interleaved_thinking)
        _with_raw_value(raw, "reasoningEffortMap", dict(self.reasoning_effort_map))
        if self._explicit_keys and "thinkingMode" in self._explicit_keys:
            raw["thinkingMode"] = self.thinking_mode
        return raw


AdapterConfig: TypeAlias = (
    OpenAICompletionsConfig | OpenAIResponsesConfig | AnthropicMessagesConfig
)


def default_adapter_config(api: str) -> AdapterConfig | None:
    if api == "openai-completions":
        return OpenAICompletionsConfig()
    if api == "openai-responses":
        return OpenAIResponsesConfig()
    if api == "anthropic-messages":
        return AnthropicMessagesConfig()
    return None


def adapter_config_from_raw(
    api: str,
    raw: Mapping[str, object] | None,
) -> AdapterConfig | None:
    if api == "openai-completions":
        return OpenAICompletionsConfig.from_raw(raw)
    if api == "openai-responses":
        return OpenAIResponsesConfig.from_raw(raw)
    if api == "anthropic-messages":
        return AnthropicMessagesConfig.from_raw(raw)
    return None


def adapter_config_allowed_keys(api: str) -> frozenset[str]:
    if api == "openai-completions":
        return OPENAI_COMPLETIONS_ADAPTER_KEYS
    if api == "openai-responses":
        return OPENAI_RESPONSES_ADAPTER_KEYS
    if api == "anthropic-messages":
        return ANTHROPIC_MESSAGES_ADAPTER_KEYS
    return frozenset()


def merge_adapter_config(
    base: AdapterConfig | None,
    override: AdapterConfig | None,
) -> AdapterConfig | None:
    if override is None:
        return base
    if base is None:
        return override
    if type(base) is not type(override):
        raise ValueError("model adapter config must match endpoint adapter type")
    override_raw = _adapter_override_raw(override)
    if not override_raw:
        return base
    return type(base).from_raw({**base.to_raw(), **override_raw})


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    scopes: tuple[str, ...] = ()
    redirect_uri: str | None = None
    revocation_endpoint: str | None = None
    token_endpoint_auth_method: str = "none"

    def __post_init__(self) -> None:
        for name in ("client_id", "authorization_endpoint", "token_endpoint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"oauth {name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        for name in ("redirect_uri", "revocation_endpoint"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"oauth {name} must be a non-empty string or None")
            object.__setattr__(self, name, value.strip())
        if (
            not isinstance(self.token_endpoint_auth_method, str)
            or not self.token_endpoint_auth_method.strip()
        ):
            raise ValueError(
                "oauth token_endpoint_auth_method must be a non-empty string"
            )
        object.__setattr__(
            self,
            "token_endpoint_auth_method",
            self.token_endpoint_auth_method.strip(),
        )
        if not isinstance(self.scopes, tuple) or any(
            not isinstance(scope, str) or not scope.strip() for scope in self.scopes
        ):
            raise ValueError("oauth scopes must contain non-empty strings")
        normalized_scopes = tuple(scope.strip() for scope in self.scopes)
        if len(set(normalized_scopes)) != len(normalized_scopes):
            raise ValueError("oauth scopes must not contain duplicates")
        object.__setattr__(self, "scopes", normalized_scopes)

    @classmethod
    def from_raw(cls, raw: Mapping[str, object]) -> "OAuthConfig":
        if not isinstance(raw, Mapping):
            raise ValueError("oauth config must be an object")
        return cls(
            client_id=raw.get("client_id"),  # type: ignore[arg-type]
            authorization_endpoint=raw.get("authorization_endpoint"),  # type: ignore[arg-type]
            token_endpoint=raw.get("token_endpoint"),  # type: ignore[arg-type]
            scopes=_as_str_tuple(raw.get("scopes")),
            redirect_uri=_as_optional_str(raw.get("redirect_uri")),
            revocation_endpoint=_as_optional_str(raw.get("revocation_endpoint")),
            token_endpoint_auth_method=raw.get(  # type: ignore[arg-type]
                "token_endpoint_auth_method",
                "none",
            ),
        )

    def to_raw(self) -> dict[str, object]:
        raw: dict[str, object] = {
            "client_id": self.client_id,
            "authorization_endpoint": self.authorization_endpoint,
            "token_endpoint": self.token_endpoint,
        }
        if self.scopes:
            raw["scopes"] = list(self.scopes)
        if self.redirect_uri is not None:
            raw["redirect_uri"] = self.redirect_uri
        if self.revocation_endpoint is not None:
            raw["revocation_endpoint"] = self.revocation_endpoint
        if self.token_endpoint_auth_method != "none":
            raw["token_endpoint_auth_method"] = self.token_endpoint_auth_method
        return raw


@dataclass(frozen=True)
class Auth:
    kind: str = "apiKey"
    provider: str | None = None
    oauth: OAuthConfig | None = None
    api_key_env: str | None = None
    api_key_envs: tuple[str, ...] = ()
    header: str = "Authorization"
    prefix: str = "Bearer "

    def __post_init__(self) -> None:
        if self.kind not in {"apiKey", "oauth", "none"}:
            raise ValueError(f"unsupported auth kind: {self.kind!r}")
        if self.provider is not None and (
            not isinstance(self.provider, str) or not self.provider
        ):
            raise ValueError("auth provider must be a non-empty string or None")
        if self.oauth is not None and not isinstance(self.oauth, OAuthConfig):
            raise TypeError("auth oauth must be OAuthConfig or None")
        if self.oauth is not None and self.kind != "oauth":
            raise ValueError("auth oauth config requires kind='oauth'")
        if self.api_key_env is not None and (
            not isinstance(self.api_key_env, str) or not self.api_key_env
        ):
            raise ValueError("auth api_key_env must be a non-empty string or None")
        if not isinstance(self.api_key_envs, tuple) or any(
            not isinstance(value, str) or not value for value in self.api_key_envs
        ):
            raise ValueError("auth api_key_envs must contain non-empty strings")
        if len(set(self.api_key_envs)) != len(self.api_key_envs):
            raise ValueError("auth api_key_envs must not contain duplicates")
        if not isinstance(self.header, str) or not self.header:
            raise ValueError("auth header must be a non-empty string")
        if not isinstance(self.prefix, str):
            raise ValueError("auth prefix must be a string")

    @classmethod
    def from_raw(cls, raw: Mapping[str, object] | None) -> "Auth | None":
        if not raw:
            return None
        return cls(
            kind=raw.get("kind", "apiKey"),  # type: ignore[arg-type]
            provider=_as_optional_str(raw.get("provider")),
            oauth=(
                OAuthConfig.from_raw(cast(Mapping[str, object], raw["oauth"]))
                if isinstance(raw.get("oauth"), Mapping)
                else None
            ),
            api_key_env=_as_optional_str(raw.get("apiKeyEnv")),
            api_key_envs=_as_str_tuple(raw.get("apiKeyEnvs")),
            header=raw.get("header", "Authorization"),  # type: ignore[arg-type]
            prefix=raw.get("prefix", "Bearer "),  # type: ignore[arg-type]
        )

    def to_raw(self) -> dict[str, object]:
        raw: dict[str, object] = {"kind": self.kind}
        if self.provider is not None:
            raw["provider"] = self.provider
        if self.oauth is not None:
            raw["oauth"] = self.oauth.to_raw()
        if self.api_key_env is not None:
            raw["apiKeyEnv"] = self.api_key_env
        if self.api_key_envs:
            raw["apiKeyEnvs"] = list(self.api_key_envs)
        if self.header != "Authorization":
            raw["header"] = self.header
        if self.prefix != "Bearer ":
            raw["prefix"] = self.prefix
        return raw


@dataclass(frozen=True)
class Pricing:
    currency: str | None = None
    input: float | int | None = None
    output: float | int | None = None
    cache_read: float | int | None = None
    cache_write: float | int | None = None

    def __post_init__(self) -> None:
        for attr in ("input", "output", "cache_read", "cache_write"):
            value = getattr(self, attr)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError(f"pricing field must be a non-negative number: {attr}")

    @classmethod
    def from_raw(cls, raw: Mapping[str, object] | None) -> "Pricing | None":
        if raw is None:
            return None
        return cls(
            currency=_as_optional_str(raw.get("currency")),
            input=_as_optional_number(raw.get("input")),
            output=_as_optional_number(raw.get("output")),
            cache_read=_as_optional_number(raw.get("cacheRead")),
            cache_write=_as_optional_number(raw.get("cacheWrite")),
        )

    def to_raw(self) -> dict[str, object]:
        raw = {
            "currency": self.currency,
            "input": self.input,
            "output": self.output,
            "cacheRead": self.cache_read,
            "cacheWrite": self.cache_write,
        }
        return {key: value for key, value in raw.items() if value is not None}


@dataclass(frozen=True)
class Capabilities:
    input: tuple[Modality, ...] = ("text",)
    output: tuple[Modality, ...] = ("text",)
    context_window: int | None = None
    max_tokens: int | None = None
    reasoning: bool = False
    stream: bool = False
    tool_use: bool = False
    structured_output: bool = False
    attachment: bool = False
    temperature: bool = False

    def __post_init__(self) -> None:
        for attr in (
            "reasoning",
            "stream",
            "tool_use",
            "structured_output",
            "attachment",
            "temperature",
        ):
            if not isinstance(getattr(self, attr), bool):
                raise ValueError(f"capability field must be a boolean: {attr}")
        for attr in ("context_window", "max_tokens"):
            value = getattr(self, attr)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"capability field must be a positive integer: {attr}")
        for attr in ("input", "output"):
            value = getattr(self, attr)
            if not isinstance(value, (list, tuple)) or not value:
                raise ValueError(
                    f"capability field must be a non-empty modality sequence: {attr}"
                )
            if any(
                not isinstance(modality, str) or modality not in ALLOWED_MODALITIES
                for modality in value
            ) or len(set(value)) != len(value):
                raise ValueError(f"capability field has invalid modalities: {attr}")
            object.__setattr__(self, attr, tuple(value))

    @property
    def supports_thinking(self) -> bool:
        return self.reasoning

    @property
    def supports_image_input(self) -> bool:
        return "image" in self.input

    @property
    def supports_image_output(self) -> bool:
        return "image" in self.output

    @classmethod
    def from_raw(cls, raw: Mapping[str, object] | None) -> "Capabilities":
        raw = raw or {}
        capabilities_raw = raw.get("capabilities")
        if isinstance(capabilities_raw, Mapping):
            raw = capabilities_raw
        return cls(
            input=_parse_modalities(raw["input"]) if "input" in raw else ("text",),
            output=(_parse_modalities(raw["output"]) if "output" in raw else ("text",)),
            context_window=_positive_int_from_raw(raw, "contextWindow"),
            max_tokens=_positive_int_from_raw(raw, "maxTokens"),
            reasoning=_capability_bool_from_raw(raw, "reasoning"),
            stream=_capability_bool_from_raw(raw, "stream"),
            tool_use=_capability_bool_from_raw(raw, "toolUse"),
            structured_output=_capability_bool_from_raw(raw, "structuredOutput"),
            attachment=_capability_bool_from_raw(raw, "attachment"),
            temperature=_capability_bool_from_raw(raw, "temperature"),
        )

    def to_raw(self) -> dict[str, object]:
        return {
            "capabilities": {
                "contextWindow": self.context_window,
                "maxTokens": self.max_tokens,
                "input": list(self.input),
                "output": list(self.output),
                "reasoning": self.reasoning,
                "stream": self.stream,
                "toolUse": self.tool_use,
                "structuredOutput": self.structured_output,
                "attachment": self.attachment,
                "temperature": self.temperature,
            }
        }


@dataclass(frozen=True)
class Defaults(Mapping[str, object]):
    items_by_key: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key in ("contextWindow", "maxTokens", "maxOutputTokens"):
            if key not in self.items_by_key:
                continue
            value = self.items_by_key[key]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"model default must be a positive integer: {key}")
        if "temperature" in self.items_by_key:
            temperature = self.items_by_key["temperature"]
            if (
                isinstance(temperature, bool)
                or not isinstance(temperature, int | float)
                or not isfinite(temperature)
            ):
                raise ValueError("model default must be a finite number: temperature")
        if "reasoningEffort" in self.items_by_key:
            reasoning_effort = self.items_by_key["reasoningEffort"]
            if not isinstance(reasoning_effort, str) or not reasoning_effort.strip():
                raise ValueError(
                    "model default must be a non-empty string: reasoningEffort"
                )
        object.__setattr__(
            self,
            "items_by_key",
            _freeze_raw_mapping(self.items_by_key),
        )

    def __getitem__(self, key: str) -> object:
        return self.items_by_key[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.items_by_key)

    def __len__(self) -> int:
        return len(self.items_by_key)

    def get(self, key: str, default: object | None = None) -> object | None:
        return self.items_by_key.get(key, default)

    def merged(self, other: Mapping[str, object] | None = None) -> "Defaults":
        merged = dict(self.items_by_key)
        if other is not None:
            merged.update(dict(other))
        return Defaults(items_by_key=merged)

    @classmethod
    def from_raw(cls, raw: Mapping[str, object] | None) -> "Defaults":
        return cls(items_by_key=dict(raw or {}))

    def to_raw(self) -> dict[str, object]:
        return _copy_raw_mapping(self.items_by_key)


@dataclass(frozen=True)
class Model:
    id: str
    _endpoint_key: str = ""
    provider: InitVar[str | None] = None
    endpoint: InitVar[str | None] = None
    api: str | None = None
    base_url: str | None = None
    base_url_env: str | None = None
    region: str | None = None
    lane: str | None = None
    preferred_endpoint: bool = False
    auth: Auth | None = None
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    name: str | None = None
    family: str | None = None
    alias: str | None = None
    knowledge: str | None = None
    release_date: str | None = None
    last_updated: str | None = None
    capabilities: Capabilities = field(default_factory=Capabilities)
    pricing: Pricing | None = None
    adapter: AdapterConfig | None = None
    defaults: Defaults = field(default_factory=Defaults)
    upstream_id: str | None = None

    def __post_init__(self, provider: str | None, endpoint: str | None) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        if self.upstream_id is not None and (
            not isinstance(self.upstream_id, str) or not self.upstream_id.strip()
        ):
            raise ValueError("model upstream_id must be a non-empty string")
        if not self._endpoint_key and provider is not None and endpoint is not None:
            object.__setattr__(
                self,
                "_endpoint_key",
                build_endpoint_key(provider, endpoint),
            )

    @property
    def provider_id(self) -> str:
        return parse_endpoint_key(self._endpoint_key)[0]

    @property
    def endpoint_id(self) -> str:
        return parse_endpoint_key(self._endpoint_key)[1]

    @property
    def input(self) -> tuple[Modality, ...]:
        return self.capabilities.input

    @property
    def output(self) -> tuple[Modality, ...]:
        return self.capabilities.output

    @property
    def context_window(self) -> int | None:
        return self.capabilities.context_window

    @property
    def max_tokens(self) -> int | None:
        return self.capabilities.max_tokens

    @property
    def reasoning(self) -> bool:
        return self.capabilities.reasoning

    @property
    def supports_tool_use(self) -> bool:
        return self.capabilities.tool_use

    @property
    def supports_structured_output(self) -> bool:
        return self.capabilities.structured_output

    @property
    def supports_attachment(self) -> bool:
        return self.capabilities.attachment

    @property
    def supports_temperature(self) -> bool:
        return self.capabilities.temperature

    @property
    def supports_stream(self) -> bool:
        return self.capabilities.stream

    @property
    def supports_thinking(self) -> bool:
        return self.capabilities.supports_thinking

    @property
    def supports_image_input(self) -> bool:
        return self.capabilities.supports_image_input

    @property
    def supports_image_output(self) -> bool:
        return self.capabilities.supports_image_output

    def to_raw(self) -> dict[str, object]:
        raw: dict[str, object] = {
            "displayName": self.name,
            "family": self.family,
            "alias": self.alias,
            "knowledge": self.knowledge,
            "releaseDate": self.release_date,
            "lastUpdated": self.last_updated,
            "defaults": self.defaults.to_raw(),
        }
        raw.update(self.capabilities.to_raw())
        if self.adapter is not None:
            raw["adapter"] = self.adapter.to_raw()
        if self.pricing is not None:
            raw["pricing"] = self.pricing.to_raw()
        if self.auth is not None:
            raw["auth"] = self.auth.to_raw()
        if self.upstream_id is not None:
            raw["upstreamId"] = self.upstream_id
        return {key: value for key, value in raw.items() if value is not None}


@dataclass(frozen=True)
class Endpoint:
    id: str
    api: str
    _provider_key: str = ""
    provider: InitVar[str | None] = None
    name: str | None = None
    base_url: str | None = None
    base_url_env: str | None = None
    region: str | None = None
    lane: str | None = None
    preferred: bool = False
    docs: str | None = None
    auth: Auth | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    defaults: Defaults = field(default_factory=Defaults)
    models: Mapping[str, Model] = field(default_factory=dict)
    adapter: AdapterConfig | None = None

    def __post_init__(self, provider: str | None) -> None:
        object.__setattr__(self, "models", MappingProxyType(dict(self.models)))
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        if self._provider_key:
            return
        if provider is None:
            return
        object.__setattr__(self, "_provider_key", provider)

    @property
    def provider_id(self) -> str:
        return self._provider_key

    @property
    def endpoint_key(self) -> str:
        return build_endpoint_key(self.provider_id, self.id)

    def get_model(self, model_id: str) -> Model | None:
        return self.models.get(model_id)

    def list_models(self) -> list[Model]:
        return sorted(self.models.values(), key=lambda item: item.id)

    def to_raw(self) -> dict[str, object]:
        return _endpoint_to_raw(self)


@dataclass(frozen=True)
class Provider:
    id: str
    name: str | None = None
    website: str | None = None
    auth: Auth | None = None
    endpoints: Mapping[str, Endpoint] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoints", MappingProxyType(dict(self.endpoints)))

    def get_endpoint(self, endpoint_id: str) -> Endpoint | None:
        return self.endpoints.get(endpoint_id)

    def list_endpoints(self) -> list[Endpoint]:
        return sorted(self.endpoints.values(), key=lambda item: item.id)

    def get_model(self, endpoint_id: str, model_id: str) -> Model | None:
        endpoint = self.get_endpoint(endpoint_id)
        if endpoint is None:
            return None
        return endpoint.get_model(model_id)

    def list_models(self) -> list[Model]:
        models: list[Model] = []
        for endpoint in self.list_endpoints():
            models.extend(endpoint.list_models())
        return models

    def to_raw(self) -> dict[str, object]:
        raw: dict[str, object] = {
            "endpoints": {
                endpoint_id: _endpoint_to_raw(endpoint)
                for endpoint_id, endpoint in self.endpoints.items()
            }
        }
        if self.name is not None:
            raw["displayName"] = self.name
        if self.website is not None:
            raw["website"] = self.website
        if self.auth is not None:
            raw["auth"] = self.auth.to_raw()
        return raw


def _endpoint_to_raw(
    endpoint: Endpoint,
) -> dict[str, object]:
    raw: dict[str, object] = {
        "api": endpoint.api,
        "defaults": endpoint.defaults.to_raw(),
        "models": {
            model_id: model.to_raw() for model_id, model in endpoint.models.items()
        },
    }
    if endpoint.name is not None:
        raw["displayName"] = endpoint.name
    if endpoint.base_url is not None:
        raw["baseUrl"] = endpoint.base_url
    if endpoint.base_url_env is not None:
        raw["baseUrlEnv"] = endpoint.base_url_env
    if endpoint.region is not None:
        raw["region"] = endpoint.region
    if endpoint.lane is not None:
        raw["lane"] = endpoint.lane
    if endpoint.preferred:
        raw["preferred"] = endpoint.preferred
    if endpoint.docs is not None:
        raw["docs"] = endpoint.docs
    if endpoint.auth is not None:
        raw["auth"] = endpoint.auth.to_raw()
    if endpoint.headers:
        raw["headers"] = dict(endpoint.headers)
    if endpoint.adapter is not None:
        raw["adapter"] = endpoint.adapter.to_raw()
    return raw


def _parse_modalities(raw: object) -> tuple[Modality, ...]:
    if (
        not isinstance(raw, list)
        or not raw
        or any(
            not isinstance(value, str) or value not in ALLOWED_MODALITIES
            for value in raw
        )
        or len(set(raw)) != len(raw)
    ):
        raise ValueError("capability field has invalid modalities")
    return cast(tuple[Modality, ...], tuple(raw))


def _capability_bool_from_raw(raw: Mapping[str, object], key: str) -> bool:
    if key not in raw:
        return False
    value = raw[key]
    if not isinstance(value, bool):
        raise ValueError(f"capability field must be a boolean: {key}")
    return value


def _positive_int_from_raw(raw: Mapping[str, object], key: str) -> int | None:
    if key not in raw:
        return None
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"capability field must be a positive integer: {key}")
    return value


def _as_optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_optional_number(value: object) -> float | int | None:
    return (
        value
        if not isinstance(value, bool)
        and isinstance(value, int | float)
        and isfinite(value)
        else None
    )


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def build_endpoint_key(provider_id: str, endpoint_id: str) -> str:
    return f"{provider_id}:{endpoint_id}"


def parse_endpoint_key(endpoint_key: str) -> tuple[str, str]:
    if ":" not in endpoint_key:
        return "", endpoint_key
    provider_id, endpoint_id = endpoint_key.split(":", 1)
    return provider_id, endpoint_id
