from loushang.ai.api import (
    complete,
    complete_structured,
    stream,
)
from loushang.ai.auth import (
    ApiKeyAuth,
    AuthError,
    CredentialExpiredError,
    CredentialStatus,
    FileCredentialStore,
    InvalidCredentialError,
    MissingCredentialError,
    OAuthBearerAuth,
    OAuthCredential,
    OAuthProviderNotConfiguredError,
    RefreshFailedError,
    credential_status,
    login,
    logout,
)
from loushang.ai.errors import (
    AIError,
    AIErrorCode,
    AIErrorInfo,
    AmbiguousModelError,
    ModelNotFoundError,
)
from loushang.ai.event_stream import AssistantMessageEventStream
from loushang.ai.model import Model, ModelSelection
from loushang.ai.model.registry import (
    ModelRegistry as _ModelRegistry,
)
from loushang.ai.model.registry import (
    get_default_model_registry as _get_default_model_registry,
)
from loushang.ai.options import (
    CallOptions,
    PreparedRequestLimits,
    ReasoningOptions,
    RetryOptions,
    ThinkingLevel,
)
from loushang.ai.structured import (
    StructuredOutputError,
    StructuredOutputOptions,
    StructuredOutputResult,
)
from loushang.ai.types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    ImagePart,
    Message,
    StopReason,
    TextPart,
    ThinkingPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)
from loushang.ai.usage import (
    usage_from_message,
    usage_payload,
)


def _model_registry() -> _ModelRegistry:
    return _get_default_model_registry()


def get_model(provider: str, endpoint: str, model_id: str) -> Model:
    try:
        return _model_registry().get_model(provider, endpoint, model_id)
    except KeyError as error:
        ref = f"{provider}:{endpoint}:{model_id}"
        raise ModelNotFoundError(
            f"Model not found: {ref}",
            provider=provider,
            endpoint=endpoint,
            model=model_id,
        ) from error
    except ValueError as error:
        raise AmbiguousModelError(
            f"Ambiguous model: {model_id}",
            provider=provider,
            endpoint=endpoint,
            model=model_id,
        ) from error


def list_models(
    *,
    provider: str | None = None,
    endpoint: str | None = None,
    model_id: str | None = None,
) -> list[Model]:
    return _model_registry().list_models(
        provider=provider,
        endpoint=endpoint,
        model_id=model_id,
    )


__all__ = [
    "AssistantMessage",
    "AssistantMessageEvent",
    "AssistantMessageEventStream",
    "AmbiguousModelError",
    "Context",
    "Message",
    "Model",
    "ModelNotFoundError",
    "ModelSelection",
    "StopReason",
    "AIError",
    "AIErrorCode",
    "AIErrorInfo",
    "ApiKeyAuth",
    "AuthError",
    "CallOptions",
    "PreparedRequestLimits",
    "CredentialExpiredError",
    "CredentialStatus",
    "FileCredentialStore",
    "InvalidCredentialError",
    "MissingCredentialError",
    "OAuthBearerAuth",
    "OAuthCredential",
    "OAuthProviderNotConfiguredError",
    "RefreshFailedError",
    "ReasoningOptions",
    "RetryOptions",
    "ThinkingLevel",
    "StructuredOutputError",
    "StructuredOutputOptions",
    "StructuredOutputResult",
    "ImagePart",
    "TextPart",
    "ThinkingPart",
    "Tool",
    "ToolCall",
    "ToolResultMessage",
    "UserMessage",
    "Usage",
    "UsageCost",
    "complete",
    "complete_structured",
    "credential_status",
    "get_model",
    "list_models",
    "login",
    "logout",
    "stream",
    "usage_from_message",
    "usage_payload",
]
