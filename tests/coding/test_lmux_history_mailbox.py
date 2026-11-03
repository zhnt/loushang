"""Long public seed must consume the real bounded attachment mailbox."""

import asyncio
import time
from types import SimpleNamespace as NS

from loushang.appserver.protocol import AckV1, SessionEventKindV1, SessionEventV1
from loushang.appservice.runtime import _Attachment

from ._lmux_history_recipe import OMITTED, history_records
from ._lmux_history_seed import seed_history


def test_seed_consumes_events_without_replacing_or_enlarging_attachment():
    identity = NS(session_id="session")
    mailbox = _Attachment(attachment_id="attachment", mux_space_id="mux",
                          controller_generation=1, mailbox_capacity=256)
    mailbox.bind_member(identity, "member")
    sent, consumed = [], []
    full = history_records()

    class Client:
        async def start_turn(self, request):
            sent.append(request.text)
            for offset, kind in enumerate((SessionEventKindV1.TURN_STARTED, SessionEventKindV1.USER_MESSAGE,
                         SessionEventKindV1.ASSISTANT_DELTA, SessionEventKindV1.ASSISTANT_MESSAGE,
                         SessionEventKindV1.TURN_COMPLETED), start=1):
                mailbox.push(SessionEventV1("session", (len(sent) - 1) * 5 + offset, kind))
            return AckV1()

        async def snapshot_session(self, request):
            assert mailbox.active, f"mailbox lagged after {len(sent)} turns"
            count = len(sent)
            rows = full[max(0, count * 2 - 14):count * 2]
            if count > 7:
                rows = [["status", OMITTED], *rows]
            return NS(identity=identity, running=False,
                      records=[NS(kind=NS(value=kind), text=text) for kind, text in rows])

        async def read_events(self, **kwargs):
            assert kwargs == {"attachment_id": "attachment", "controller_generation": 1, "limit": 64}
            # The real wire dispatcher caps each response at one event even
            # when the client requests 64 (bounded maximum frame size).
            events = mailbox.read(limit=1)
            consumed.extend(events)
            return events

    async def run():
        return await seed_history(Client(), attachment_id="attachment", generation=1,
            member_id="member", identity=identity, deadline=time.monotonic() + 600)

    result = asyncio.run(run())
    assert len(result["rounds"]) == 128 and len(consumed) == 640
    assert sent == [f"history {index:04d}" for index in range(128)]
    assert mailbox.active and mailbox.queue.empty() and mailbox.queue.maxsize == 256
