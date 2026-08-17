from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
from contextlib import suppress
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_module(alias: str, filename: str):
    if alias in sys.modules:
        return sys.modules[alias]
    path = BASE_DIR / filename
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


_types = _load_module("spike_types", "types.py")
_abort_signal = _load_module("spike_abort_signal", "abort_signal.py")
_event_stream = _load_module("spike_event_stream", "event_stream.py")
_assembler = _load_module("spike_assembler", "assembler.py")

AssistantMessageAssembler = _assembler.AssistantMessageAssembler
RawFinish = _assembler.RawFinish
RawTextPart = _assembler.RawTextPart
ManualAbortSignal = _abort_signal.ManualAbortSignal
create_assistant_message_event_stream = _event_stream.create_assistant_message_event_stream


async def _produce_normal(assembler: AssistantMessageAssembler) -> None:
    assembler.start()
    await asyncio.sleep(0)
    assembler.feed(RawTextPart("hello "))
    await asyncio.sleep(0)
    assembler.feed(RawTextPart("world"))
    await asyncio.sleep(0)
    assembler.finish(RawFinish("stop"))


async def _produce_aborted(assembler: AssistantMessageAssembler, signal: ManualAbortSignal) -> None:
    assembler.start()
    await asyncio.sleep(0)
    assembler.feed(RawTextPart("hello "))
    await asyncio.sleep(0)
    signal.cancel()
    await asyncio.sleep(0)
    with suppress(RuntimeError):
        assembler.feed(RawTextPart("world"))


async def scenario_normal_completion() -> tuple[int, str, str | None]:
    stream, writer = create_assistant_message_event_stream()
    assembler = AssistantMessageAssembler(writer)
    producer = asyncio.create_task(_produce_normal(assembler))

    count = 0
    last_type = None
    async for event in stream:
        count += 1
        last_type = event.type
    await producer
    result = await stream.result()
    return count, last_type or "", result.stop_reason


async def scenario_aborted_mid_stream() -> tuple[int, str, str | None]:
    stream, writer = create_assistant_message_event_stream()
    signal = ManualAbortSignal()
    assembler = AssistantMessageAssembler(writer, signal=signal)
    producer = asyncio.create_task(_produce_aborted(assembler, signal))

    count = 0
    last_type = None
    async for event in stream:
        count += 1
        last_type = event.type
    await producer
    result = await stream.result()
    return count, last_type or "", result.stop_reason


async def scenario_mixed_consumption() -> tuple[int, str, str | None]:
    stream, writer = create_assistant_message_event_stream()
    assembler = AssistantMessageAssembler(writer)
    assembler.start()
    assembler.feed(RawTextPart("alpha "))
    assembler.feed(RawTextPart("beta"))
    assembler.finish(RawFinish("stop"))

    first = await stream.__anext__()
    rest = 1
    async for _ in stream:
        rest += 1
    result = await stream.result()
    return rest, first.type, result.stop_reason


async def scenario_throughput_smoke() -> tuple[int, float, str | None]:
    stream, writer = create_assistant_message_event_stream()
    assembler = AssistantMessageAssembler(writer)
    assembler.start()

    start = time.perf_counter()
    for _ in range(10_000):
        assembler.feed(RawTextPart("x"))
    assembler.finish(RawFinish("stop"))

    count = 0
    async for _ in stream:
        count += 1
    result = await stream.result()
    elapsed = time.perf_counter() - start
    return count, elapsed, result.stop_reason


async def main() -> None:
    normal = await scenario_normal_completion()
    print(f"scenario_normal_completion: events={normal[0]} last={normal[1]} stop_reason={normal[2]}")

    aborted = await scenario_aborted_mid_stream()
    print(f"scenario_aborted_mid_stream: events={aborted[0]} last={aborted[1]} stop_reason={aborted[2]}")

    mixed = await scenario_mixed_consumption()
    print(f"scenario_mixed_consumption: events={mixed[0]} first={mixed[1]} stop_reason={mixed[2]}")

    throughput = await scenario_throughput_smoke()
    print(
        "scenario_throughput_smoke: "
        f"events={throughput[0]} elapsed={throughput[1]:.4f}s stop_reason={throughput[2]}"
    )


if __name__ == "__main__":
    asyncio.run(main())
