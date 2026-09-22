"""Public request/snapshot seed, borrowing an already owned attachment.

The caller owns authentication, attachment, connection close and service stop.
Returning here never authorizes starting a PTY before those resources settle.
"""

import asyncio
import math
import sys
import time

from loushang.appserver.protocol import (
    AckV1,
    AttachmentEventV1,
    MuxAttachV1,
    MuxDetachV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionSnapshotRequestV1,
    TurnTextV1,
)

from ._lmux_history_recipe import ROUNDS, history_turn, validate_history_window

SEED_SECONDS = 600.0
ROUND_SECONDS = 40.0
MAX_POLLS = 80
MAX_EVENT_READS = 64
POLL_SECONDS = 0.1


async def seed_attached_history(client, *, mux_id, member_id, identity, deadline):
    """Own a temporary attachment, borrowing the caller's original connection.

    Lost attach/detach responses remain failures. Only the original connection
    owner can settle an attachment whose response was lost.
    """
    if (type(deadline) not in (int, float) or not 0 <= deadline <= sys.float_info.max
            or not math.isfinite(deadline)):
        raise ValueError("invalid attachment deadline")

    async def bounded(operation, limit):
        remaining = limit - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("history attachment deadline expired")
        async with asyncio.timeout(remaining):
            result = await operation()
        if time.monotonic() >= limit:
            raise TimeoutError("history attachment result arrived too late")
        return result

    attach_started = time.monotonic()
    attach_deadline = min(deadline, attach_started + 30)
    attachment = await bounded(lambda: client.attach_mux(MuxAttachV1(MuxSelectorV1(mux_space_id=mux_id))),
                               attach_deadline)
    attached = time.monotonic()
    primary = None
    try:
        mux = attachment.mux_space
        if (mux.mux_space_id != mux_id or len(mux.members) != 1
                or mux.members[0].member_id != member_id or mux.members[0].session != identity):
            raise ValueError("history attachment differs from authenticated target")
        evidence = await seed_history(client, attachment_id=attachment.attachment_id,
            generation=attachment.controller_generation, member_id=member_id, identity=identity,
            deadline=deadline - 30)  # Reserve bounded detach time, never borrow from the seed.
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            detach_started = time.monotonic()
            detach_deadline = min(deadline, detach_started + 30)
            ack = await bounded(lambda: client.detach_mux(MuxDetachV1(
                attachment.attachment_id, attachment.controller_generation)),
                detach_deadline)
            if type(ack) is not AckV1:
                raise ValueError("history detach requires successful Ack")
        except BaseException as cleanup:
            if primary is None:
                raise
            primary.add_note("history detach failed: " + type(cleanup).__name__)
    detached = time.monotonic()
    if detached >= deadline:
        raise TimeoutError("history attachment completion exceeded deadline")
    return {**evidence, "detached_at": detached,
            "attachment": {"deadline": deadline, "attach_started_at": attach_started,
                           "attach_deadline": attach_deadline, "attached_at": attached,
                           "detach_started_at": detach_started, "detach_deadline": detach_deadline}}


async def seed_history(client, *, attachment_id, generation, member_id, identity, deadline):
    if (type(deadline) not in (int, float) or not 0 <= deadline <= sys.float_info.max
            or not math.isfinite(deadline)):
        raise ValueError("invalid seed deadline")
    started = time.monotonic()
    deadline = min(deadline, started + SEED_SECONDS)
    request = SessionSnapshotRequestV1(attachment_id, generation, member_id)

    async def bounded(operation, limit):
        remaining = limit - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("history seed deadline expired before dispatch")
        async with asyncio.timeout(remaining):
            result = await operation()
        if time.monotonic() >= limit:
            raise TimeoutError("history seed result arrived after deadline")
        return result

    def records(snapshot):
        if snapshot.identity != identity:
            raise ValueError("history seed Session identity changed")
        rows = [[record.kind.value, record.text] for record in snapshot.records]
        if any(kind == "error" for kind, _ in rows):
            raise ValueError("history seed received error record")
        return rows

    initial = await bounded(lambda: client.snapshot_session(request), min(deadline, started + ROUND_SECONDS))
    if records(initial) or initial.running is not False:
        raise ValueError("history seed requires a fresh idle Session")
    evidence = []
    previous = []
    for index in range(ROUNDS):
        began = time.monotonic()
        limit = min(deadline, began + ROUND_SECONDS)
        text, _ = history_turn(index)
        ack = await bounded(lambda text=text: client.start_turn(TurnTextV1(
            attachment_id, generation, member_id, text,
        )), limit)
        if type(ack) is not AckV1:
            raise ValueError("history seed requires a successful Ack")
        acknowledged = time.monotonic()
        for poll in range(MAX_POLLS):
            # Snapshot reads do not consume the bounded attachment mailbox.
            # Borrow the same client's normal event path; never reattach or
            # replay a turn to recover from lag. The wire may return one event
            # per frame: only an empty batch proves this drain completed.
            for _ in range(MAX_EVENT_READS):
                events = await bounded(lambda: client.read_events(attachment_id=attachment_id,
                    controller_generation=generation, limit=64), limit)
                if type(events) is not tuple or len(events) > 64:
                    raise ValueError("invalid history event batch")
                if not events:
                    break
                for event in events:
                    if (type(event) is not AttachmentEventV1 or event.attachment_id != attachment_id
                            or event.member_id != member_id or event.event.session_id != identity.session_id
                            or event.event.kind is SessionEventKindV1.ERROR):
                        raise ValueError("history event differs from current Session")
            else:
                raise TimeoutError("history event read budget exhausted")
            snapshot = await bounded(lambda: client.snapshot_session(request), limit)
            rows = records(snapshot)
            if snapshot.running is False and rows != previous:
                validate_history_window(rows, index)
                settled = time.monotonic()
                if settled >= limit:
                    raise TimeoutError("history seed validation exceeded round deadline")
                evidence.append({"round": index, "started_at": began, "acknowledged_at": acknowledged,
                                 "settled_at": settled, "snapshot_reads": poll + 1})
                previous = rows
                break
            # Old idle is not this turn's success; never send the request twice.
            if poll + 1 == MAX_POLLS:
                raise TimeoutError("history seed snapshot read budget exhausted")
            await bounded(lambda: asyncio.sleep(POLL_SECONDS), limit)
    finished = time.monotonic()
    if finished >= deadline:
        raise TimeoutError("history seed completion exceeded total deadline")
    return {"started_at": started, "finished_at": finished, "rounds": evidence}
