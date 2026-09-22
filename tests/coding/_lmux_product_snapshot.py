"""Post-detach confirmation; never used to timestamp the visible reply.

The caller must have settled its terminal before calling, and must retain and
close its authenticated connection even if attach or detach fails. This helper
borrows that connection; it is not an anonymous/read-only observation API.
"""

from __future__ import annotations

import asyncio
import math
import re
import time

from loushang.appserver.protocol import (
    MuxAttachV1,
    MuxDetachV1,
    MuxSelectorV1,
    SessionSnapshotRequestV1,
    TranscriptRecordKindV1,
)


async def confirm_reply(client, *, mux_id, member_id, identity, expected, deadline):
    return await _confirm(client, mux_id=mux_id, member_id=member_id, identity=identity,
                          expected=expected, deadline=deadline, pending=False)


async def confirm_history(client, *, mux_id, member_id, identity, deadline):
    """Read the exact seeded tail under the existing temporary attachment."""
    return await _confirm(client, mux_id=mux_id, member_id=member_id, identity=identity,
                          expected=None, deadline=deadline, pending=False, history=True)


async def confirm_pending_reply(client, *, mux_id, member_id, identity, expected, deadline):
    """Confirm the detached delayed-final turn still runs without a commit."""
    return await _confirm(client, mux_id=mux_id, member_id=member_id, identity=identity,
                          expected=expected, deadline=deadline, pending=True)


async def confirm_tool_reply(client, *, mux_id, member_id, identity, expected, deadline):
    if expected != "LMUX_TOOL_COMPLETED":
        raise ValueError("invalid fixed tool reply witness")
    return await _confirm(client, mux_id=mux_id, member_id=member_id, identity=identity,
                          expected=expected, deadline=deadline, pending=False, tool_approval=True)


async def confirm_denied_tool_reply(client, *, mux_id, member_id, identity, expected, deadline):
    """Confirm the fixed policy-error echo, not proof of zero execution.

    The caller must separately witness the same handler's zero effects both
    before denial and after exact service settlement. A model echo alone
    cannot establish that authorization prevented execution.
    """
    if expected != "Tool lmux_evidence requires approval":
        raise ValueError("invalid fixed denied tool reply witness")
    return await _confirm(client, mux_id=mux_id, member_id=member_id, identity=identity,
                          expected=expected, deadline=deadline, pending=False, tool_approval=True)


async def confirm_interrupted_reply(client, *, mux_id, member_id, identity, expected,
                                    interrupted_nonce, deadline):
    """Verify B after interrupted A; the empty record itself proves no cause."""
    if re.fullmatch(r"[0-9a-f]{32}", interrupted_nonce) is None:
        raise ValueError("invalid interrupted request witness")
    if expected == "LMUX_REPLY_" + interrupted_nonce:
        raise ValueError("next request must use a different nonce")
    return await _confirm(client, mux_id=mux_id, member_id=member_id, identity=identity,
                          expected=expected, deadline=deadline, pending=False,
                          interrupted_nonce=interrupted_nonce)


async def confirm_natural_reply(client, *, mux_id, member_id, identity, expected,
                                natural_nonce, pending, deadline):
    if re.fullmatch(r"[0-9a-f]{32}", natural_nonce) is None:
        raise ValueError("invalid natural completion nonce")
    return await _confirm(client, mux_id=mux_id, member_id=member_id, identity=identity,
                          expected=expected, deadline=deadline, pending=pending,
                          natural_nonce=natural_nonce)


async def _confirm(client, *, mux_id, member_id, identity, expected, deadline, pending,
                   interrupted_nonce=None, tool_approval=False, natural_nonce=None, history=False):
    if not history and not tool_approval and re.fullmatch(r"LMUX_REPLY_[0-9a-f]{32}", expected) is None:
        raise ValueError("invalid reply witness")
    if not math.isfinite(deadline):
        raise ValueError("invalid observation deadline")

    async def bounded(operation):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("observation deadline expired before dispatch")
        async with asyncio.timeout(remaining):
            result = await operation()
        if time.monotonic() >= deadline:
            raise TimeoutError("observation response arrived after deadline")
        return result

    attachment = await bounded(lambda: client.attach_mux(MuxAttachV1(MuxSelectorV1(mux_space_id=mux_id))))
    primary = None
    try:
        assert attachment.mux_space.mux_space_id == mux_id
        members = attachment.mux_space.members
        assert len(members) == 1
        assert members[0].member_id == member_id and members[0].session == identity
        assert members[0].title == "FirstUse"
        snapshot = await bounded(lambda: client.snapshot_session(SessionSnapshotRequestV1(
            attachment.attachment_id, attachment.controller_generation, member_id,
        )))
        # Mux display title and Product-owned snapshot title are independent.
        # The fresh Coding Product can still project its default "Coding".
        assert snapshot.identity == identity
        assert snapshot.running is pending
        assistants = tuple(record.text for record in snapshot.records
                           if record.kind is TranscriptRecordKindV1.ASSISTANT)
        if history:
            from ._lmux_history_recipe import ROUNDS, validate_history_window
            validate_history_window([[record.kind.value, record.text] for record in snapshot.records], ROUNDS - 1)
            if time.monotonic() >= deadline:
                raise TimeoutError("history snapshot validation exceeded deadline")
        elif pending:
            assert assistants == (), "delayed final must not commit an assistant reply"
            users = tuple(record.text for record in snapshot.records
                          if record.kind is TranscriptRecordKindV1.USER)
            if natural_nonce is not None:
                assert expected == "LMUX_REPLY_" + natural_nonce
            assert users == (("gated " if natural_nonce is not None else "delayed ")
                             + expected.removeprefix("LMUX_REPLY_"),)
        elif natural_nonce is not None:
            expected_records = (
                (TranscriptRecordKindV1.USER, "gated " + natural_nonce),
                (TranscriptRecordKindV1.ASSISTANT, "LMUX_REPLY_" + natural_nonce),
            )
            if expected != "LMUX_REPLY_" + natural_nonce:
                expected_records += (
                    (TranscriptRecordKindV1.USER, "reply " + expected.removeprefix("LMUX_REPLY_")),
                    (TranscriptRecordKindV1.ASSISTANT, expected),
                )
            assert tuple((record.kind, record.text) for record in snapshot.records) == expected_records
        elif tool_approval:
            assert tuple((record.kind, record.text) for record in snapshot.records) == (
                (TranscriptRecordKindV1.USER, "approval"),
                (TranscriptRecordKindV1.ASSISTANT, ""),
                (TranscriptRecordKindV1.ASSISTANT, expected),
            ), "fresh tool turn must have one final reply after its tool-call message"
        elif interrupted_nonce is not None:
            # The fixed Agent abort path retains one empty assistant record.
            # Do not ignore arbitrary empty/error records or infer an abort
            # reason from a projection that carries no stop_reason field.
            records = tuple((record.kind, record.text) for record in snapshot.records)
            assert records == (
                (TranscriptRecordKindV1.USER, "delayed " + interrupted_nonce),
                (TranscriptRecordKindV1.ASSISTANT, ""),
                (TranscriptRecordKindV1.USER, "reply " + expected.removeprefix("LMUX_REPLY_")),
                (TranscriptRecordKindV1.ASSISTANT, expected),
            ), "same Session must retain A then exactly one successful B reply"
        else:
            assert tuple((record.kind, record.text) for record in snapshot.records) == (
                (TranscriptRecordKindV1.USER, "reply " + expected.removeprefix("LMUX_REPLY_")),
                (TranscriptRecordKindV1.ASSISTANT, expected),
            ), "fresh Session must contain exactly the requested user turn and committed reply"
        assert not any(record.kind is TranscriptRecordKindV1.ERROR for record in snapshot.records)
        return snapshot
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            await bounded(lambda: client.detach_mux(MuxDetachV1(
                attachment.attachment_id, attachment.controller_generation,
            )))
        except BaseException as cleanup:
            if primary is None:
                raise
            primary.add_note("post-detach snapshot observer detach failed: " + type(cleanup).__name__)
