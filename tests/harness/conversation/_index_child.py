"""Independent index writer used only by the process-lock regression."""

import asyncio
import sys

from loushang.harness.conversation import (
    ConversationKey,
    ConversationLocator,
    FunctionalProjectionCodec,
    IndexedProjection,
    JsonConversationIndex,
)
from loushang.harness.journal.jsonl import JournalLockUnavailable


def main():
    index = JsonConversationIndex(
        sys.argv[1], version=1,
        codec=FunctionalProjectionCodec(
            encoder=lambda value: {"value": value}, decoder=lambda data: data["value"],
        ),
        query_items=lambda _query, items: tuple(items),
    )
    projection = IndexedProjection(
        ConversationLocator("local", ConversationKey("root", "two")), 1, "second",
    )
    try:
        asyncio.run(index.upsert(projection))
    except JournalLockUnavailable:
        print("busy", flush=True)
    else:
        raise AssertionError("child bypassed parent index transaction")
    if sys.stdin.readline() != "continue\n":
        raise AssertionError("missing parent release receipt")
    assert asyncio.run(index.upsert(projection))
    print("published", flush=True)


if __name__ == "__main__":
    main()
