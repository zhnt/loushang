import asyncio
from dataclasses import FrozenInstanceError, replace
from io import StringIO

import pytest

from loushang.harnesstui.conversation.input_policy import (
    ConversationCapabilities,
    ConversationCapability,
)


def snapshot():
    return ConversationCapabilities(("attachment", "1", "member", "session"), tuple(
        ConversationCapability(operation, "unavailable", "protocol_unavailable")
        for operation in (
            "transcript", "submit", "steer", "follow_up", "interrupt",
            "approval_details", "approve", "deny", "image_paste", "product_commands",
        )
    ))


def test_capability_snapshot_is_complete_immutable_and_binding_scoped():
    value = snapshot()
    assert value.get("submit", binding_key=value.binding_key).reason == "protocol_unavailable"
    assert value.get("submit", binding_key=("replacement",)).reason == "binding_changed"
    with pytest.raises(FrozenInstanceError):
        value.binding_key = ("replacement",)
    with pytest.raises(ValueError):
        replace(value, entries=value.entries[:-1])
    with pytest.raises(ValueError):
        replace(value, entries=(*value.entries[:-1], value.entries[0]))


@pytest.mark.parametrize("changes", [
    {"operation": "unknown"}, {"availability": "authorized"},
    {"reason": "arbitrary remote text"},
])
def test_capability_values_reject_open_vocabulary(changes):
    with pytest.raises(ValueError):
        replace(snapshot().entries[0], **changes)


@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError], ids=["normal", "error", "cancel"])
@pytest.mark.parametrize("existing", [False, True], ids=["empty", "existing"])
def test_prepared_embedded_projection_refreshes_and_restores_on_exit(failure, existing):
    from loushang.harnesstui.conversation.application_host import (
        run_prepared_screen_conversation,
    )
    from loushang.tui.core import RenderConstraints

    from .test_application_host import _screen_run

    run = _screen_run([])
    prior_value = replace(snapshot(), binding_key=("prior",)) if existing else None
    prior_provider = (lambda: prior_value) if existing else None
    run.app.capability_provider = prior_provider
    run.app.state.capabilities = prior_value
    current = [snapshot()]
    run = replace(run, capability_provider=lambda: current[0])
    original_input = run.app.state.input_capabilities

    async def runner(**kwargs):
        app = kwargs["app"]
        app.render(RenderConstraints(width=100, max_height=30))
        assert app.state.capabilities is current[0]
        current[0] = replace(current[0], binding_key=("new-local-binding",))
        app.render(RenderConstraints(width=100, max_height=30))
        assert app.state.capabilities is current[0]
        assert app.state.input_capabilities == original_input
        if failure is not None:
            raise failure("runner failed")
        return 0

    async def execute():
        return await run_prepared_screen_conversation(
            run, stdin=StringIO(), stdout=StringIO(), screen_runner=runner,
        )

    if failure is not None:
        with pytest.raises(failure, match="runner failed"):
            asyncio.run(execute())
    else:
        assert asyncio.run(execute()) == 0
    assert run.app.capability_provider is prior_provider
    assert run.app.state.capabilities is prior_value
