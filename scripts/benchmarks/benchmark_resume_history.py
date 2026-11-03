#!/usr/bin/env python3
"""Measure bounded recent-history delivery through actual Coding Roots.

Fixture creation warms the OS file cache. This measures data API first/repeated
reads; terminal paint, background planning and writable activation are excluded.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import platform
import tempfile
import tracemalloc
from pathlib import Path
from statistics import median
from time import perf_counter

from loushang.ai.types import UserMessage
from loushang.coding.composition_provenance import CODING_COMPOSITION_HEADER_KEY
from loushang.coding.product_plan import (
    CODING_CAPABILITY_PROFILE,
    CODING_CAPABILITY_PROFILE_METADATA_KEY,
)
from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime
from loushang.harness.conversation import ConversationHeader, ConversationRecord
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    write_agent_transcript_export,
)
from loushang.harness.transcript.types import AgentTranscriptRecord


def _fixture(root: Path, count: int, payload_bytes: int) -> Path:
    path = root / f"history-{count}.jsonl"
    profile = CODING_CAPABILITY_PROFILE.snapshot().to_json()
    profile["capabilities"] = []
    header = ConversationHeader(
        conversation_id=f"history-{count}", version=1,
        created_at="2026-10-12T00:00:00Z",
        metadata={
            "cwd": str(root),
            CODING_CAPABILITY_PROFILE_METADATA_KEY: profile,
            CODING_COMPOSITION_HEADER_KEY: {
                "version": 1, "setId": "retired-benchmark", "planFingerprint": "a" * 64,
            },
        },
    )
    records: list[AgentTranscriptRecord] = [ConversationRecord(
        record_id=f"record-{index}", parent_id=None if index == 0 else f"record-{index - 1}",
        kind=AGENT_MESSAGE_KIND, payload_version=1,
        created_at="2026-10-12T00:00:01Z",
        payload=UserMessage(role="user", content="x" * payload_bytes, timestamp=1.0),
    ) for index in range(count)]
    write_agent_transcript_export(path, header, records)
    return path


def _forbidden_factory(*_args, **_kwargs):
    raise AssertionError("history benchmark must not create a Product Session")


async def _measure(path: Path, count: int, parallelism: int, samples: int) -> dict[str, object]:
    roots = [AgentSessionRuntime(
        session_dir=path.parent, session_factory=_forbidden_factory,
    ) for _ in range(parallelism)]
    initial = path.stat()
    durations = []
    bytes_read = []
    delivered_records = []
    try:
        for _ in range(samples):
            started = perf_counter()
            pages = await asyncio.gather(*(root.preview_resume_recent_page(path) for root in roots))
            durations.append((perf_counter() - started) * 1000)
            for root, page in zip(roots, pages, strict=True):
                assert root.current_session is None
                assert page.status == "unverified_tail_preview"
                assert page.header_preview.header.conversation_id == f"history-{count}"
                assert page.records[-1].record_id == f"record-{count - 1}"
                assert page.bytes_read <= 2 * 64 * 1024
                bytes_read.append(page.bytes_read)
                delivered_records.append(len(page.records))
    finally:
        await asyncio.gather(*(root.dispose_session_runtime() for root in roots))
    final = path.stat()
    assert (initial.st_dev, initial.st_ino, initial.st_size, initial.st_mtime_ns) == (
        final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns,
    )
    return {
        "records_in_fixture": count,
        "fixture_bytes": initial.st_size,
        "parallel_viewers": parallelism,
        "first_batch_ms": durations[0],
        "repeated_batch_ms": durations[1:],
        "repeated_batch_median_ms": median(durations[1:]) if len(durations) > 1 else None,
        "max_bytes_read_per_viewer": max(bytes_read),
        "max_records_delivered_per_viewer": max(delivered_records),
        "source_identity_size_mtime_unchanged": True,
        "status": "unverified_tail_preview",
    }


async def _measure_python_peak(path: Path, count: int, parallelism: int) -> int:
    """Trace a separate fresh-root batch without perturbing latency samples."""

    if tracemalloc.is_tracing():
        raise RuntimeError("memory benchmark requires its own tracing session")
    gc.collect()
    tracemalloc.start(1)
    try:
        await _measure(path, count, parallelism, samples=1)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    results = []
    scratch_root = args.scratch_root
    if scratch_root is not None:
        scratch_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="loushang-resume-history-benchmark-", dir=scratch_root,
    ) as temporary:
        root = Path(temporary)
        for count in args.sizes:
            path = _fixture(root, count, args.payload_bytes)
            gc.collect()
            for parallelism in args.parallelism:
                result = await _measure(path, count, parallelism, args.samples)
                result["python_traced_peak_bytes"] = (
                    await _measure_python_peak(path, count, parallelism)
                    if args.measure_memory else None
                )
                results.append(result)
    return {
        "schema_version": 1,
        "measurement": "coding_root_bounded_recent_history_data_delivery",
        "python": platform.python_version(),
        "platform": platform.system(),
        "payload_bytes_per_record": args.payload_bytes,
        "samples_per_case": args.samples,
        "viewer_scope": "one original Root per viewer; not one Root with eight waiters",
        "os_cache": "fixture creation warms OS cache; no OS-cold claim",
        "first_read": "first data read on each newly created Root; imports and fixture setup excluded",
        "bytes_measurement": "bounded head/tail bytes; discovery and metadata IO excluded",
        "python_memory_scope": (
            "separate fresh-root single batch plus disposal; imports/fixtures/untracked native allocations/RSS excluded"
            if args.measure_memory else "not measured"
        ),
        "excluded": ["terminal_paint", "planning", "activation", "model_transport", "process_memory_peak"],
        "acceptance": "baseline only; not full R2.1 performance acceptance",
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[10000, 100000])
    parser.add_argument("--parallelism", nargs="+", type=int, default=[1, 2, 8])
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--measure-memory", action="store_true", help="Trace Python allocation peak in separate batches, excluding RSS.")
    parser.add_argument("--payload-bytes", type=int, default=1024)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scratch-root", type=Path, help="Private fixture scratch on a filesystem with sufficient capacity.")
    args = parser.parse_args()
    if any(not 1 <= value <= 100000 for value in args.sizes):
        parser.error("sizes must be between 1 and 100000")
    if any(value not in {1, 2, 8} for value in args.parallelism):
        parser.error("parallelism must be 1, 2 or 8")
    if not 1 <= args.samples <= 20 or not 1 <= args.payload_bytes <= 65536:
        parser.error("samples must be 1..20 and payload bytes must be 1..65536")
    if max(args.sizes) * (args.payload_bytes + 1024) > 256 * 1024 * 1024:
        parser.error("fixture size estimate exceeds the 256 MiB benchmark budget")
    report = asyncio.run(_run(args))
    document = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(document, end="")
    else:
        args.output.write_text(document, encoding="utf-8")
        print(f"Wrote {len(args.sizes) * len(args.parallelism)} baseline cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
