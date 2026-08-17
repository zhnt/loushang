"""Deterministic Coding model fixture for manual multi-agent CLI checks."""

from __future__ import annotations

from dataclasses import replace

from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import (
    Capabilities,
    Endpoint,
    Model,
    ModelSelection,
    Provider,
)
from loushang.ai.model.registry import ModelRegistry
from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.coding.bootstrap import BootstrapServices
from loushang.harness.model_catalog import ModelCatalog

SCRIPTED_MODEL = ModelSelection(
    provider="scripted",
    endpoint_id="anthropic-messages",
    model_id="multiagent-check",
)


def scripted_multiagent_services(
    base: BootstrapServices,
) -> BootstrapServices:
    """Replace only model resolution; preserve Product-scoped services."""

    model = _scripted_model()
    endpoint = Endpoint(
        id=model.endpoint_id,
        provider=model.provider_id,
        api=model.api or model.endpoint_id,
        models={model.id: model},
    )
    provider = Provider(
        id=model.provider_id,
        endpoints={endpoint.id: endpoint},
    )
    registry = ModelRegistry.from_providers({provider.id: provider})
    return replace(
        base,
        model_registry=ModelCatalog(ai_registry=registry),
    )


async def scripted_multiagent_stream(
    _model: Model,
    context,
    options=None,
) -> AssistantMessageEventStream:
    """Return a deterministic response while exercising the real Agent loop."""

    del options
    prompt = context.messages[-1].content[0].text
    if prompt.startswith("Independently review"):
        text = (
            "Scripted review: the request was inspected independently; "
            "verify lifecycle cleanup and authority boundaries."
        )
    elif prompt.startswith("Synthesize"):
        text = (
            "Scripted synthesis: retain the lifecycle and authority checks, "
            "then proceed only after the focused tests pass."
        )
    elif prompt.startswith("Make the strongest"):
        text = "Scripted proposer: adopt the proposal for its bounded composition."
    elif prompt.startswith("Challenge"):
        text = "Scripted critic: adoption risks hidden lifecycle and rollback gaps."
    elif prompt.startswith("Act as an impartial"):
        text = (
            "Scripted judge: conditionally adopt after lifecycle and rollback "
            "tests pass."
        )
    else:
        text = "Scripted multi-agent response."
    message = AssistantMessage(
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider=SCRIPTED_MODEL.provider,
        endpoint=SCRIPTED_MODEL.endpoint_id,
        model=SCRIPTED_MODEL.model_id,
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost={},
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )
    stream = AssistantMessageEventStream()
    stream.push({"type": "start", "partial": message})
    stream.push({"type": "text_start", "content_index": 0, "partial": message})
    stream.push(
        {
            "type": "text_delta",
            "content_index": 0,
            "delta": text,
            "partial": message,
        }
    )
    stream.push(
        {
            "type": "text_end",
            "content_index": 0,
            "content": text,
            "partial": message,
        }
    )
    stream.push(
        {
            "type": "done",
            "reason": message.stop_reason,
            "message": message,
        }
    )
    return stream


def _scripted_model() -> Model:
    return Model(
        id=SCRIPTED_MODEL.model_id,
        name="Scripted Multi-Agent Check",
        provider=SCRIPTED_MODEL.provider,
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


__all__ = [
    "SCRIPTED_MODEL",
    "scripted_multiagent_services",
    "scripted_multiagent_stream",
]
