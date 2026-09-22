"""Fixed diagnostic observer of the original interaction RPC, never a retry."""

from contextlib import contextmanager


@contextmanager
def observe_interaction_receipts(client_type, trace):
    original = client_type.respond_interaction

    async def observed(self, request):
        from loushang.appserver.protocol import AckV1

        fields = dict(attachment_id=request.attachment_id,
                      controller_generation=request.controller_generation,
                      member_id=request.member_id, interaction_id=request.interaction_id,
                      outcome=request.outcome.value)
        trace.emit("interaction_sent", **fields)
        result = await original(self, request)
        if type(result) is not AckV1:
            raise TypeError("unexpected original interaction receipt")
        trace.emit("interaction_accepted", **fields)
        return result

    client_type.respond_interaction = observed
    try:
        yield
    finally:
        client_type.respond_interaction = original
