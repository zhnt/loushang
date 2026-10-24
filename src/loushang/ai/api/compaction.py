"""Provider-native context compaction for explicitly capable model routes."""

from __future__ import annotations

from typing import cast

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.bootstrap import register_builtin_api_adapters
from loushang.ai.context import normalize_context
from loushang.ai.errors import UnsupportedCapabilityError
from loushang.ai.model import Model
from loushang.ai.options import CallOptions
from loushang.ai.provider.resolution import prepare_request_for_model
from loushang.ai.types import Context, ProviderCompactionWindow


async def compact_provider_window(
    model: Model,
    context: Context,
    options: CallOptions | None = None,
) -> ProviderCompactionWindow:
    """Return the provider's canonical next input window without interpreting it."""

    if model.provider_compaction != "openai-responses":
        raise UnsupportedCapabilityError(
            f"Model {model.id!r} does not support provider compaction",
            provider=model.provider_id,
            endpoint=model.endpoint_id,
            model=model.id,
            details={"capability": "provider_compaction"},
        )
    normalized = normalize_context(context, model=model)
    request = await prepare_request_for_model(
        model, context=normalized, options=options
    )
    registry = get_default_api_registry()
    if not registry.list_api_adapters():
        register_builtin_api_adapters(registry)
    adapter = registry.get_api_adapter(model.api or "")
    compact_window = getattr(adapter, "compact_window", None)
    if not callable(compact_window):
        raise UnsupportedCapabilityError(
            f"API adapter {model.api!r} does not implement provider compaction",
            provider=model.provider_id,
            endpoint=model.endpoint_id,
            model=model.id,
            details={"capability": "provider_compaction"},
        )
    return cast(ProviderCompactionWindow, await compact_window(request))
