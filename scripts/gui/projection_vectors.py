"""Model-checked snapshot/event evidence, including states; not runtime fixtures."""

import copy
import json
from pathlib import Path

from loushang.appserver.execution import model as em
from loushang.appserver.execution.codec import decode_response, encode_response
from loushang.appserver.protocol import InvalidAppMessageError
from loushang.appserver.protocol import model as pm


def emit_projection_vectors() -> None:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "tests/appserver/fixtures/execution_v1.json"
    )
    identity = decode_response(
        json.dumps(json.loads(fixture.read_text(encoding="utf-8"))["accepted"]).encode()
    ).result.identity
    observation = em.ExecutionObservationV1()
    snapshot = em.ExecutionSessionSnapshotV1(
        "instance",
        em.ExecutionSourceSnapshotV1(
            pm.SessionSnapshotV1(
                identity,
                "空闲会话",
                0,
                0,
                False,
                (pm.TranscriptRecordV1(pm.TranscriptRecordKindV1.USER, "你好"),),
            ),
            observation,
        ),
        em.ExecutionSessionViewV1(identity, 0, observation),
    )
    base = json.loads(encode_response(em.ExecutionResponseV1("snapshot", snapshot)))
    cases = []

    def add(name, kind, value, valid=True):
        cases.append((name, kind, json.dumps(value, ensure_ascii=False), valid))

    add("idle", "snapshot", base)
    for count in [2**53 + 1, 2**100 + 1]:
        value = copy.deepcopy(base)
        value["result"]["source"]["source"].update(cursor=count, revision=count)
        add(f"snapshot-large-{count}", "snapshot", value)
    for count in [0, 2**53 - 1, 2**53, True, -1, 1.5]:
        value = copy.deepcopy(base)
        value["result"]["executions"]["revision"] = count
        add(
            f"metadata-revision-{count}",
            "snapshot",
            value,
            type(count) is int and 0 <= count <= 2**53 - 1,
        )
    for field, bad in [
        ("cursor", True),
        ("cursor", -1),
        ("revision", "1"),
        ("running", 1),
    ]:
        value = copy.deepcopy(base)
        value["result"]["source"]["source"][field] = bad
        add(f"source-{field}-{bad}", "snapshot", value, False)
    for size in [256, 257]:
        value = copy.deepcopy(base)
        value["result"]["source"]["source"]["records"] *= size
        add(f"snapshot-records-{size}", "snapshot", value, size <= 256)
    for size in [65_536, 65_537]:
        value = copy.deepcopy(base)
        value["result"]["source"]["source"]["records"][0]["text"] = "x" * size
        add(f"snapshot-text-{size}", "snapshot", value, size <= 65_536)
    for name in ["identity-mismatch", "draft-idle", "missing", "extra"]:
        value = copy.deepcopy(base)
        if name == "identity-mismatch":
            value["result"]["executions"]["identity"]["sessionId"] = "another"
        elif name == "draft-idle":
            value["result"]["source"]["draft"] = "unowned draft"
        elif name == "missing":
            del value["result"]["executions"]["active"]
        else:
            value["result"]["source"]["observation"]["unexpected"] = True
        add(name, "snapshot", value, False)

    def event_batch(kind=pm.SessionEventKindV1.ASSISTANT_DELTA, cursor=1):
        interaction = (
            "interaction"
            if kind
            in {
                pm.SessionEventKindV1.INTERACTION_REQUESTED,
                pm.SessionEventKindV1.INTERACTION_DISMISSED,
            }
            else None
        )
        event = em.ExecutionContentEventV1(
            pm.SessionEventV1("session", cursor, kind, "你好🙂", interaction),
            "execution",
        )
        return json.loads(
            encode_response(
                em.ExecutionResponseV1("events", em.ExecutionEventsV1((event,)))
            )
        )

    for kind in pm.SessionEventKindV1:
        add(f"content-{kind.value}", "events", event_batch(kind))
    nullable = event_batch()
    nullable["result"]["events"][0]["executionId"] = None
    nullable["result"]["events"][0]["source"]["text"] = None
    add("nullable-content", "events", nullable)
    for count in [2**53 + 1, 2**100 + 1]:
        add(f"event-large-{count}", "events", event_batch(cursor=count))
    for count in [0, True, -1, "1", 1.0]:
        value = event_batch()
        value["result"]["events"][0]["source"]["cursor"] = count
        add(f"event-invalid-cursor-{count}", "events", value, False)
    for size in [0, 256, 257]:
        value = event_batch()
        value["result"]["events"] *= size
        add(f"event-batch-{size}", "events", value, size <= 256)
    for name in [
        "interaction-missing",
        "interaction-unexpected",
        "unknown-kind",
        "missing-nullable",
        "extra",
    ]:
        value = event_batch(
            pm.SessionEventKindV1.INTERACTION_REQUESTED
            if name == "interaction-missing"
            else pm.SessionEventKindV1.STATUS
        )
        source = value["result"]["events"][0]["source"]
        if name == "interaction-missing":
            source["interactionId"] = None
        elif name == "interaction-unexpected":
            source["interactionId"] = "unexpected"
        elif name == "unknown-kind":
            source["kind"] = "unknown"
        elif name == "missing-nullable":
            del source["text"]
        else:
            source["unexpected"] = True
        add(name, "events", value, False)
    from state_vectors import append_state_vectors

    append_state_vectors(cases, base, event_batch())
    for name, kind, wire, valid in cases:
        try:
            expected = json.loads(encode_response(decode_response(wire.encode())))
            if kind == "snapshot":
                source = expected["result"]["source"]["source"]
                for field in ["cursor", "revision"]:
                    source[field] = str(source[field])
            else:
                for event in expected["result"]["events"]:
                    if "source" in event:
                        event["source"]["cursor"] = str(event["source"]["cursor"])
            accepted = True
        except InvalidAppMessageError:
            expected, accepted = None, False
        assert accepted == valid, f"Python projection contract changed: {name}"
        print(
            json.dumps(
                dict(name=name, kind=kind, wire=wire, valid=valid, expected=expected),
                ensure_ascii=False,
            )
        )
