#!/usr/bin/env python3
"""Exercise bounded cold listing and a real large-session resume lifecycle.

The catalog fixture uses sparse sentinel files so 1000 logical 40 MiB sessions
do not consume 40 GiB of disk. Their head and tail are valid transcript records,
while the sparse middle is deliberately not valid JSONL: a successful list proves
that the cold path did not replay complete transcript authority.

The resume fixture is different: it is a fully valid transcript grown through the
Coding CLI application with a deterministic in-process model. The parent process
then starts a fresh worker and resumes that transcript through ``--resume``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from time import monotonic

from loushang.agent import prepared_request_conformant
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage, UserMessage
from loushang.coding.bootstrap import create_agent_session_runtime
from loushang.coding.cli.__main__ import run_cli
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationJsonlHeaderCodec,
    ConversationJsonlRecordCodec,
    ConversationRecord,
)
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.transcript.kinds import AGENT_MESSAGE_KIND
from loushang.harness.transcript.profile import AgentTranscriptProfile

MIB = 1024 * 1024
DEFAULT_SESSION_COUNT = 1000
DEFAULT_LOGICAL_SIZE_MIB = 40
EXPECTED_BOUNDED_ENRICHMENT = 50


@dataclass(frozen=True)
class VerificationResult:
    catalog_elapsed_seconds: float
    catalog_rebuild_seconds: float
    catalog_steady_query_seconds: float
    catalog_steady_seconds: float
    catalog_items: int
    catalog_index_items: int
    catalog_logical_bytes: int
    catalog_allocated_bytes: int
    transcript_bytes: int
    initial_turn_seconds: float
    resume_turn_seconds: float
    session_id: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify bounded cold Resume Catalog and 40 MiB resume.",
    )
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSION_COUNT)
    parser.add_argument(
        "--logical-size-mib",
        type=int,
        default=DEFAULT_LOGICAL_SIZE_MIB,
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep generated fixtures and print their root.",
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--json", action="store_true")

    # Private subprocess mode. Keeping the model deterministic makes the test
    # independent from provider credentials and network availability.
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_session-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_project", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_resume", help=argparse.SUPPRESS)
    parser.add_argument("--_prompt", action="append", help=argparse.SUPPRESS)
    parser.add_argument("--_padding-bytes", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--_result", type=Path, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args._worker:
        return asyncio.run(_run_worker(args))
    if args.sessions < 1:
        raise SystemExit("--sessions must be positive")
    if args.logical_size_mib < 1:
        raise SystemExit("--logical-size-mib must be positive")

    if args.root is not None:
        root = args.root.expanduser().resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        result = _verify(root, args.sessions, args.logical_size_mib)
        _print_result(result, root=root, as_json=args.json)
        return 0

    if args.keep:
        root = Path(tempfile.mkdtemp(prefix="loushang-resume-scale-"))
        result = _verify(root, args.sessions, args.logical_size_mib)
        _print_result(result, root=root, as_json=args.json)
        return 0

    with tempfile.TemporaryDirectory(prefix="loushang-resume-scale-") as raw_root:
        root = Path(raw_root)
        result = _verify(root, args.sessions, args.logical_size_mib)
        _print_result(result, root=None, as_json=args.json)
    return 0


def _verify(
    root: Path,
    session_count: int,
    logical_size_mib: int,
) -> VerificationResult:
    project = root / "project"
    catalog_dir = root / "catalog-sessions"
    resume_dir = root / "resume-sessions"
    project.mkdir(parents=True, exist_ok=True)
    catalog_dir.mkdir(parents=True, exist_ok=True)
    resume_dir.mkdir(parents=True, exist_ok=True)

    logical_size = logical_size_mib * MIB
    _create_sparse_catalog(
        catalog_dir,
        project=project,
        count=session_count,
        logical_size=logical_size,
    )
    catalog_logical, catalog_allocated = _directory_sizes(catalog_dir)

    started = monotonic()
    listed = _run_loushang_list(project=project, session_dir=catalog_dir)
    catalog_elapsed = monotonic() - started
    expected_items = min(session_count, EXPECTED_BOUNDED_ENRICHMENT)
    if len(listed) != expected_items:
        raise RuntimeError(
            f"bounded catalog returned {len(listed)} items; expected {expected_items}"
        )
    if (catalog_dir / ".session-index.json").exists():
        raise RuntimeError("cold bounded listing unexpectedly wrote a session index")
    if tuple(catalog_dir.glob("*.model-input-v2-index.json")):
        raise RuntimeError("cold bounded listing unexpectedly built ModelInput indexes")

    directory_runtime = AgentTranscriptDirectoryRuntime(
        session_dir=catalog_dir,
        session_index_flush_delay=0.0,
    )

    async def finish_lightweight_index() -> None:
        directory_runtime.request_bounded_session_index_refresh()
        await directory_runtime.drain_session_index_flush()

    started = monotonic()
    asyncio.run(finish_lightweight_index())
    catalog_rebuild_elapsed = monotonic() - started
    indexed = directory_runtime.session_catalog.load_index()
    if len(indexed) != session_count or not all(item.bounded for item in indexed):
        raise RuntimeError("background bounded rebuild did not index every candidate")
    if tuple(catalog_dir.glob("*.model-input-v2-index.json")):
        raise RuntimeError(
            "bounded index rebuild unexpectedly built ModelInput indexes"
        )
    started = monotonic()
    steady_page = directory_runtime.try_query_session_index_page(
        limit=EXPECTED_BOUNDED_ENRICHMENT
    )
    catalog_steady_query_elapsed = monotonic() - started
    if len(steady_page.items) != expected_items or steady_page.bounded_fallback:
        raise RuntimeError("in-process steady index query did not return a fresh page")
    started = monotonic()
    steady_listed = _run_loushang_list(project=project, session_dir=catalog_dir)
    catalog_steady_elapsed = monotonic() - started
    if len(steady_listed) != expected_items:
        raise RuntimeError("steady lightweight index did not preserve the first page")

    padding_bytes = max(logical_size, 40 * MIB)
    initial_result = root / "initial-worker.json"
    started = monotonic()
    _run_turn_worker(
        project=project,
        session_dir=resume_dir,
        prompts=("MANUAL-A", "MANUAL-B", "MANUAL-C", "MANUAL-D"),
        padding_bytes=padding_bytes,
        result_path=initial_result,
    )
    initial_elapsed = monotonic() - started
    initial = json.loads(initial_result.read_text(encoding="utf-8"))
    session_id = _required_string(initial, "session_id")
    session_file = Path(_required_string(initial, "session_file"))
    transcript_bytes = session_file.stat().st_size
    if transcript_bytes < padding_bytes:
        raise RuntimeError(
            f"valid transcript is only {transcript_bytes} bytes; expected {padding_bytes}"
        )
    if initial.get("observed_user_prompts") != [
        ["MANUAL-A"],
        ["MANUAL-A", "MANUAL-B"],
        ["MANUAL-A", "MANUAL-B", "MANUAL-C"],
        ["MANUAL-A", "MANUAL-B", "MANUAL-C", "MANUAL-D"],
    ]:
        raise RuntimeError("continuous-turn context did not preserve A-D ordering")

    # The listing subprocess is the installed loushang console entry and must not
    # replay the valid 40 MiB transcript just to display its Resume Catalog row.
    large_list = _run_loushang_list(project=project, session_dir=resume_dir)
    if [item.get("session_id") for item in large_list] != [session_id]:
        raise RuntimeError("large valid transcript was not listed by session id")

    resumed_result = root / "resumed-worker.json"
    started = monotonic()
    _run_turn_worker(
        project=project,
        session_dir=resume_dir,
        prompts=("MANUAL-RESUMED",),
        padding_bytes=0,
        result_path=resumed_result,
        resume=session_id,
    )
    resume_elapsed = monotonic() - started
    resumed = json.loads(resumed_result.read_text(encoding="utf-8"))
    if resumed.get("observed_user_prompts") != [
        [
            "MANUAL-A",
            "MANUAL-B",
            "MANUAL-C",
            "MANUAL-D",
            "MANUAL-RESUMED",
        ]
    ]:
        raise RuntimeError("resumed model input did not contain the complete history")
    if _required_string(resumed, "session_id") != session_id:
        raise RuntimeError("resume created a different session identity")

    return VerificationResult(
        catalog_elapsed_seconds=catalog_elapsed,
        catalog_rebuild_seconds=catalog_rebuild_elapsed,
        catalog_steady_query_seconds=catalog_steady_query_elapsed,
        catalog_steady_seconds=catalog_steady_elapsed,
        catalog_items=len(listed),
        catalog_index_items=len(indexed),
        catalog_logical_bytes=catalog_logical,
        catalog_allocated_bytes=catalog_allocated,
        transcript_bytes=transcript_bytes,
        initial_turn_seconds=initial_elapsed,
        resume_turn_seconds=resume_elapsed,
        session_id=session_id,
    )


def _create_sparse_catalog(
    session_dir: Path,
    *,
    project: Path,
    count: int,
    logical_size: int,
) -> None:
    header_codec = ConversationJsonlHeaderCodec()
    record_codec = ConversationJsonlRecordCodec(
        AgentTranscriptProfile.default().payload_codecs
    )
    base_mtime_ns = 1_700_000_000_000_000_000
    for index in range(count):
        session_id = f"scale-{index:04d}"
        header = ConversationHeader(
            conversation_id=session_id,
            version=1,
            created_at="2026-08-20T00:00:00Z",
            metadata={"cwd": str(project)},
        )
        first = _user_record(
            f"{session_id}-first",
            f"catalog first {index}",
            parent_id=None,
            timestamp=float(index + 1),
        )
        last = _user_record(
            f"{session_id}-last",
            f"catalog tail {index}",
            parent_id=first.record_id,
            timestamp=float(index + 2),
        )
        head = _json_line(header_codec.encode_header(header)) + _json_line(
            record_codec.encode_record(first)
        )
        tail = _json_line(record_codec.encode_record(last))
        if logical_size <= len(head) + len(tail):
            raise RuntimeError("logical fixture size is too small for transcript edges")
        path = session_dir / f"{session_id}.jsonl"
        with path.open("wb") as handle:
            handle.write(head)
            handle.seek(logical_size - len(tail))
            handle.write(tail)
        os.utime(path, ns=(base_mtime_ns + index, base_mtime_ns + index))


def _user_record(
    record_id: str,
    text: str,
    *,
    parent_id: str | None,
    timestamp: float,
) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-08-20T00:00:01Z",
        payload=UserMessage(role="user", content=text, timestamp=timestamp),
    )


def _json_line(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _directory_sizes(root: Path) -> tuple[int, int]:
    logical = 0
    allocated = 0
    for path in root.glob("*.jsonl"):
        status = path.stat()
        logical += status.st_size
        allocated += status.st_blocks * 512
    return logical, allocated


def _run_loushang_list(*, project: Path, session_dir: Path) -> list[dict[str, object]]:
    executable = Path(sys.executable).with_name("loushang")
    completed = subprocess.run(
        [
            str(executable),
            "--session-dir",
            str(session_dir),
            "--list-sessions",
            "--session-index",
            "--session-limit",
            str(EXPECTED_BOUNDED_ENRICHMENT),
            "--list-sessions-format",
            "json",
            "--no-extensions",
            "--no-skills",
        ],
        cwd=project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "loushang session listing failed:\n" + completed.stderr.strip()
        )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise RuntimeError("loushang session listing returned an invalid JSON payload")
    return payload


def _run_turn_worker(
    *,
    project: Path,
    session_dir: Path,
    prompts: tuple[str, ...],
    padding_bytes: int,
    result_path: Path,
    resume: str | None = None,
) -> None:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_worker",
        "--_session-dir",
        str(session_dir),
        "--_project",
        str(project),
        "--_padding-bytes",
        str(padding_bytes),
        "--_result",
        str(result_path),
    ]
    if resume is not None:
        command.extend(("--_resume", resume))
    for prompt in prompts:
        command.extend(("--_prompt", prompt))
    completed = subprocess.run(
        command,
        cwd=project,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("large-session worker failed:\n" + completed.stderr.strip())


async def _run_worker(args: argparse.Namespace) -> int:
    session_dir = _required_path(args._session_dir, "--_session-dir")
    project = _required_path(args._project, "--_project")
    result_path = _required_path(args._result, "--_result")
    prompts = tuple(args._prompt or ())
    if not prompts:
        raise SystemExit("worker requires at least one --_prompt")

    observed_user_prompts: list[list[str]] = []
    call_count = 0

    @prepared_request_conformant
    async def stream_fn(model, context, options=None):
        del model, options
        nonlocal call_count
        call_count += 1
        user_prompts = [
            text
            for message in context.messages
            if isinstance(message, UserMessage)
            if (text := _message_text(message))
        ]
        observed_user_prompts.append(user_prompts)
        prompt = user_prompts[-1]
        padding = "x" * args._padding_bytes if call_count == 1 else ""
        return _stream_with_final_message(
            _assistant_message(f"assistant:{prompt}\n{padding}")
        )

    def runtime_builder(**kwargs):
        return create_agent_session_runtime(
            session_dir=Path(kwargs["session_dir"]),
            model=_model(),
            stream_fn=stream_fn,
            persist=True,
            no_tools=True,
            services=kwargs["services"],
        )

    argv = [
        "--session-dir",
        str(session_dir),
        "--mode",
        "print",
        "--no-tools",
        "--no-extensions",
        "--no-skills",
        "--offline",
    ]
    if args._resume:
        argv.extend(("--resume", args._resume))
    for prompt in prompts:
        argv.extend(("--message", prompt))

    stderr = StringIO()
    with open(os.devnull, "w", encoding="utf-8") as stdout:
        exit_code = await run_cli(
            argv,
            stdin=StringIO(""),
            stdout=stdout,
            stderr=stderr,
            cwd=project,
            runtime_builder=runtime_builder,
        )
    if exit_code != 0:
        raise RuntimeError(f"Coding CLI worker exited {exit_code}: {stderr.getvalue()}")
    transcripts = sorted(session_dir.glob("*.jsonl"))
    if len(transcripts) != 1:
        raise RuntimeError(f"expected one transcript, found {len(transcripts)}")
    header = ConversationJsonlHeaderCodec().decode_header(
        json.loads(transcripts[0].read_bytes().splitlines()[0])
    )
    result_path.write_text(
        json.dumps(
            {
                "exit_code": exit_code,
                "session_id": header.conversation_id,
                "session_file": str(transcripts[0]),
                "observed_user_prompts": observed_user_prompts,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def _model() -> Model:
    return Model(
        id="resume-scale-model",
        name="Resume Scale Model",
        provider="resume-scale",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=100_000_000,
            max_tokens=4096,
        ),
    )


def _assistant_message(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="anthropic-messages",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="resume-scale",
        model="resume-scale-model",
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


def _message_text(message: UserMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(part.text for part in message.content if isinstance(part, TextPart))


def _stream_with_final_message(
    message: AssistantMessage,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()
    stream.push({"type": "start", "partial": message})
    stream.push({"type": "text_start", "content_index": 0, "partial": message})
    stream.push(
        {
            "type": "text_delta",
            "content_index": 0,
            "delta": message.content[0].text,
            "partial": message,
        }
    )
    stream.push(
        {
            "type": "text_end",
            "content_index": 0,
            "content": message.content[0].text,
            "partial": message,
        }
    )
    stream.push({"type": "done", "reason": "stop", "message": message})
    return stream


def _required_path(value: Path | None, flag: str) -> Path:
    if value is None:
        raise SystemExit(f"worker requires {flag}")
    return value.expanduser().resolve(strict=False)


def _required_string(value: object, key: str) -> str:
    selected = value.get(key) if isinstance(value, dict) else None
    if not isinstance(selected, str) or not selected:
        raise RuntimeError(f"worker result has no {key}")
    return selected


def _print_result(
    result: VerificationResult,
    *,
    root: Path | None,
    as_json: bool,
) -> None:
    payload = {
        "catalog": {
            "items": result.catalog_items,
            "indexed_items": result.catalog_index_items,
            "elapsed_seconds": round(result.catalog_elapsed_seconds, 3),
            "bounded_rebuild_seconds": round(result.catalog_rebuild_seconds, 3),
            "steady_query_seconds": round(result.catalog_steady_query_seconds, 3),
            "steady_seconds": round(result.catalog_steady_seconds, 3),
            "logical_gib": round(result.catalog_logical_bytes / (1024**3), 3),
            "allocated_mib": round(result.catalog_allocated_bytes / MIB, 3),
        },
        "large_session": {
            "session_id": result.session_id,
            "transcript_mib": round(result.transcript_bytes / MIB, 3),
            "initial_a_to_d_seconds": round(result.initial_turn_seconds, 3),
            "restart_resume_seconds": round(result.resume_turn_seconds, 3),
        },
        "fixture_root": str(root) if root is not None else None,
        "status": "passed",
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print("Resume scale verification: passed")
    print(
        "Cold catalog: "
        f"{result.catalog_items} rows in {result.catalog_elapsed_seconds:.3f}s; "
        f"logical {result.catalog_logical_bytes / (1024**3):.2f} GiB, "
        f"allocated {result.catalog_allocated_bytes / MIB:.2f} MiB"
    )
    print(
        "Bounded index rebuild: "
        f"{result.catalog_index_items} rows in "
        f"{result.catalog_rebuild_seconds:.3f}s"
    )
    print(
        "Steady indexed query: "
        f"{result.catalog_steady_query_seconds:.3f}s; "
        f"full CLI {result.catalog_steady_seconds:.3f}s"
    )
    print(
        "Valid large session: "
        f"{result.transcript_bytes / MIB:.2f} MiB; "
        f"A-D {result.initial_turn_seconds:.3f}s; "
        f"restart+resume {result.resume_turn_seconds:.3f}s"
    )
    if root is not None:
        print(f"Fixtures kept at: {root}")


if __name__ == "__main__":
    raise SystemExit(main())
