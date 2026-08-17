from __future__ import annotations

import importlib
import json
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar, cast

from loushang.foundation.json import JsonValueError, require_json_mapping
from loushang.harness.journal.codec import (
    JournalCodecError,
    JournalHeaderCodec,
    JournalRecordCodec,
)
from loushang.harness.journal.types import (
    DEFAULT_JSONL_FORMAT,
    DURABLE_LOCKED_JOURNAL,
    JournalDiagnostic,
    JournalDurabilityProfile,
    JournalFormatProfile,
    JournalLoadPolicy,
    JsonlSnapshot,
)

H = TypeVar("H")
R = TypeVar("R")
LockMode = Literal["exclusive", "shared"]
LockFactory = Callable[[Path, LockMode], AbstractContextManager[None]]


@dataclass(frozen=True)
class LegacyJsonConstant:
    """A non-standard number token found by the opt-in legacy line parser."""

    token: str


@dataclass(frozen=True)
class LegacyJsonlParsedLine:
    """Syntax-only result for a permissively parsed legacy JSONL line."""

    value: object
    ending: str


class JournalFileError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        path: Path,
        code: str,
        line_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.code = code
        self.line_number = line_number


@contextmanager
def journal_file_lock(
    path: Path,
    mode: LockMode,
    *,
    lock_suffix: str = ".lock",
    is_windows: Callable[[], bool] | None = None,
    load_fcntl: Callable[[], Any] | None = None,
    load_msvcrt: Callable[[], Any] | None = None,
) -> Iterator[None]:
    lock_path = path.with_name(f"{path.name}{lock_suffix}")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        _prepare_lock_byte(handle)
        windows = (is_windows or _is_windows)()
        if windows:
            msvcrt = (load_msvcrt or _load_msvcrt)()
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        fcntl = (load_fcntl or _load_fcntl)()
        operation = fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH
        fcntl.flock(handle.fileno(), operation)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_jsonl_record(
    path: str | Path,
    record: R,
    *,
    record_codec: JournalRecordCodec[R],
    format_profile: JournalFormatProfile = DEFAULT_JSONL_FORMAT,
    durability: JournalDurabilityProfile = DURABLE_LOCKED_JOURNAL,
    lock_factory: LockFactory | None = None,
) -> None:
    target = Path(path)
    line = _dump_mapping(record_codec.encode_record(record), format_profile)
    with _lock_context(
        target,
        "exclusive",
        durability=durability,
        lock_factory=lock_factory,
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding=format_profile.encoding) as handle:
            handle.write(line)
            handle.write(format_profile.newline)
            _sync_handle(handle, durability)


def append_jsonl_records(
    path: str | Path,
    records: Sequence[R],
    *,
    record_codec: JournalRecordCodec[R],
    format_profile: JournalFormatProfile = DEFAULT_JSONL_FORMAT,
    durability: JournalDurabilityProfile = DURABLE_LOCKED_JOURNAL,
    lock_factory: LockFactory | None = None,
) -> None:
    """Append an ordered record batch with one lock, open, write, and sync."""

    durable_records = tuple(records)
    if not durable_records:
        return
    lines = tuple(
        _dump_mapping(record_codec.encode_record(record), format_profile)
        for record in durable_records
    )
    payload = format_profile.newline.join(lines) + format_profile.newline
    target = Path(path)
    with _lock_context(
        target,
        "exclusive",
        durability=durability,
        lock_factory=lock_factory,
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding=format_profile.encoding) as handle:
            handle.write(payload)
            _sync_handle(handle, durability)


def write_jsonl(
    path: str | Path,
    records: Sequence[R],
    *,
    record_codec: JournalRecordCodec[R],
    header: H | None = None,
    header_codec: JournalHeaderCodec[H] | None = None,
    format_profile: JournalFormatProfile = DEFAULT_JSONL_FORMAT,
    durability: JournalDurabilityProfile = DURABLE_LOCKED_JOURNAL,
    lock_factory: LockFactory | None = None,
) -> None:
    target = Path(path)
    encoded: list[str] = []
    if header is not None:
        if header_codec is None:
            raise ValueError("header_codec is required when writing a header")
        encoded.append(
            _dump_mapping(header_codec.encode_header(header), format_profile)
        )
    encoded.extend(
        _dump_mapping(record_codec.encode_record(record), format_profile)
        for record in records
    )
    data = format_profile.newline.join(encoded)
    if encoded:
        data += format_profile.newline

    with _lock_context(
        target,
        "exclusive",
        durability=durability,
        lock_factory=lock_factory,
    ):
        _replace_text_unlocked(
            target,
            data,
            encoding=format_profile.encoding,
            durability=durability,
        )


def load_jsonl(
    path: str | Path,
    *,
    record_codec: JournalRecordCodec[R],
    header_codec: JournalHeaderCodec[H] | None = None,
    format_profile: JournalFormatProfile = DEFAULT_JSONL_FORMAT,
    durability: JournalDurabilityProfile = DURABLE_LOCKED_JOURNAL,
    load_policy: JournalLoadPolicy = JournalLoadPolicy(),
    lock_factory: LockFactory | None = None,
) -> JsonlSnapshot[H, R]:
    target = Path(path)
    lock_mode: LockMode = (
        "exclusive" if load_policy.partial_tail == "repair" else "shared"
    )
    with _lock_context(
        target,
        lock_mode,
        durability=durability,
        lock_factory=lock_factory,
    ):
        raw = target.read_text(encoding=format_profile.encoding)
        snapshot = _decode_jsonl(
            raw,
            target=target,
            record_codec=record_codec,
            header_codec=header_codec,
            load_policy=load_policy,
        )
        partial_tail = next(
            (
                diagnostic
                for diagnostic in snapshot.diagnostics
                if diagnostic.code == "partial_journal_tail"
            ),
            None,
        )
        if load_policy.partial_tail == "repair" and partial_tail is not None:
            if partial_tail.line_number is None:
                raise RuntimeError("partial-tail diagnostic requires a line number")
            repaired = raw[: _line_start_offset(raw, partial_tail.line_number)]
            _replace_text_unlocked(
                target,
                repaired,
                encoding=format_profile.encoding,
                durability=durability,
            )
        return snapshot


def _decode_jsonl(
    raw: str,
    *,
    target: Path,
    record_codec: JournalRecordCodec[R],
    header_codec: JournalHeaderCodec[H] | None,
    load_policy: JournalLoadPolicy,
) -> JsonlSnapshot[H, R]:

    numbered_lines = [
        (line_number, line)
        for line_number, line in enumerate(raw.splitlines(), start=1)
        if line.strip()
    ]
    if load_policy.header == "required" and not numbered_lines:
        raise JournalFileError(
            "Journal file is empty",
            path=target,
            code="empty_journal",
        )
    if load_policy.header == "required" and header_codec is None:
        raise ValueError("header_codec is required by the load policy")

    diagnostics: list[JournalDiagnostic] = []
    header: H | None = None
    record_lines = numbered_lines
    if load_policy.header == "required":
        line_number, line = numbered_lines[0]
        try:
            value = _load_mapping(
                line, path=target, line_number=line_number, kind="header"
            )
            header = cast(JournalHeaderCodec[H], header_codec).decode_header(value)
        except JournalFileError:
            if load_policy.invalid_header == "raise":
                raise
            diagnostics.append(
                _diagnostic(
                    "invalid_journal_header",
                    "Journal header was skipped because it is invalid.",
                    target,
                    line_number,
                )
            )
        except Exception as exc:
            code = exc.code if isinstance(exc, JournalCodecError) else "invalid_header"
            if load_policy.invalid_header == "raise":
                raise JournalFileError(
                    "Journal header is invalid",
                    path=target,
                    code=code,
                    line_number=line_number,
                ) from exc
            diagnostics.append(
                _diagnostic(
                    code,
                    "Journal header was skipped because its value is invalid.",
                    target,
                    line_number,
                )
            )
        record_lines = numbered_lines[1:]

    records: list[R] = []
    last_nonblank_line = numbered_lines[-1][0] if numbered_lines else None
    for line_number, line in record_lines:
        try:
            value = _load_mapping(
                line, path=target, line_number=line_number, kind="record"
            )
            records.append(record_codec.decode_record(value))
        except Exception as exc:
            is_partial_tail = (
                line_number == last_nonblank_line and not _has_trailing_newline(raw)
            )
            behavior = (
                load_policy.partial_tail
                if is_partial_tail
                else load_policy.invalid_record
            )
            if behavior == "raise":
                if isinstance(exc, JournalFileError):
                    raise
                code = (
                    exc.code if isinstance(exc, JournalCodecError) else "invalid_record"
                )
                raise JournalFileError(
                    "Journal record is invalid",
                    path=target,
                    code=code,
                    line_number=line_number,
                ) from exc
            diagnostics.append(
                _diagnostic(
                    "partial_journal_tail"
                    if is_partial_tail
                    else "invalid_journal_record",
                    "Journal record was skipped because it is incomplete or invalid.",
                    target,
                    line_number,
                )
            )

    return JsonlSnapshot(
        header=header,
        records=tuple(records),
        diagnostics=tuple(diagnostics),
    )


def parse_legacy_jsonl_line(line: str) -> LegacyJsonlParsedLine | None:
    """Parse one legacy line without weakening the strict journal reader.

    Product compatibility readers may opt into this syntax-only helper, migrate
    the returned value to their own strict schema, and then use a strict dumper.
    Malformed JSON returns ``None`` and non-standard numeric constants remain
    explicit ``LegacyJsonConstant`` values.
    """

    body, ending = _split_line_ending(line)
    try:
        value = json.loads(body, parse_constant=LegacyJsonConstant)
    except (ValueError, RecursionError):
        return None
    return LegacyJsonlParsedLine(value=value, ending=ending)


class JsonlJournal(Generic[H, R]):
    def __init__(
        self,
        path: str | Path,
        *,
        record_codec: JournalRecordCodec[R],
        header_codec: JournalHeaderCodec[H] | None = None,
        format_profile: JournalFormatProfile = DEFAULT_JSONL_FORMAT,
        durability: JournalDurabilityProfile = DURABLE_LOCKED_JOURNAL,
        load_policy: JournalLoadPolicy = JournalLoadPolicy(),
        lock_factory: LockFactory | None = None,
    ) -> None:
        self.path = Path(path)
        self.record_codec = record_codec
        self.header_codec = header_codec
        self.format_profile = format_profile
        self.durability = durability
        self.load_policy = load_policy
        self.lock_factory = lock_factory

    def append(self, record: R) -> None:
        append_jsonl_record(
            self.path,
            record,
            record_codec=self.record_codec,
            format_profile=self.format_profile,
            durability=self.durability,
            lock_factory=self.lock_factory,
        )

    def append_batch(self, records: Sequence[R]) -> None:
        append_jsonl_records(
            self.path,
            records,
            record_codec=self.record_codec,
            format_profile=self.format_profile,
            durability=self.durability,
            lock_factory=self.lock_factory,
        )

    def rewrite(self, records: Sequence[R], *, header: H | None = None) -> None:
        write_jsonl(
            self.path,
            records,
            record_codec=self.record_codec,
            header=header,
            header_codec=self.header_codec,
            format_profile=self.format_profile,
            durability=self.durability,
            lock_factory=self.lock_factory,
        )

    def load(self) -> JsonlSnapshot[H, R]:
        return load_jsonl(
            self.path,
            record_codec=self.record_codec,
            header_codec=self.header_codec,
            format_profile=self.format_profile,
            durability=self.durability,
            load_policy=self.load_policy,
            lock_factory=self.lock_factory,
        )


def _lock_context(
    path: Path,
    mode: LockMode,
    *,
    durability: JournalDurabilityProfile,
    lock_factory: LockFactory | None,
) -> AbstractContextManager[None]:
    if not durability.locking:
        return nullcontext()
    if lock_factory is not None:
        return lock_factory(path, mode)
    return journal_file_lock(path, mode, lock_suffix=durability.lock_suffix)


def _dump_mapping(
    value: Mapping[str, object],
    profile: JournalFormatProfile,
) -> str:
    if not isinstance(value, Mapping):
        raise TypeError("journal codecs must encode mappings")
    payload = require_json_mapping(dict(value), name="journal_record")
    return json.dumps(
        payload,
        ensure_ascii=profile.ensure_ascii,
        sort_keys=profile.sort_keys,
        separators=profile.separators,
        allow_nan=False,
    )


def _load_mapping(
    line: str,
    *,
    path: Path,
    line_number: int,
    kind: Literal["header", "record"],
) -> Mapping[str, object]:
    try:
        value = json.loads(line, parse_constant=_reject_json_constant)
    except ValueError as exc:
        raise JournalFileError(
            f"Journal {kind} is not valid JSON",
            path=path,
            code=f"invalid_{kind}_json",
            line_number=line_number,
        ) from exc
    if not isinstance(value, Mapping):
        raise JournalFileError(
            f"Journal {kind} must be a JSON object",
            path=path,
            code=f"invalid_{kind}_shape",
            line_number=line_number,
        )
    try:
        return cast(
            Mapping[str, object],
            require_json_mapping(dict(value), name=f"journal_{kind}"),
        )
    except JsonValueError as exc:
        raise JournalFileError(
            f"Journal {kind} contains a value outside strict JSON",
            path=path,
            code=f"invalid_{kind}_value",
            line_number=line_number,
        ) from exc


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith(("\n", "\r")):
        return line[:-1], line[-1]
    return line, ""


def _sync_handle(handle: Any, durability: JournalDurabilityProfile) -> None:
    if durability.flush or durability.fsync:
        handle.flush()
    if durability.fsync:
        os.fsync(handle.fileno())


def _has_trailing_newline(raw: str) -> bool:
    return raw.endswith(("\n", "\r"))


def _line_start_offset(raw: str, line_number: int) -> int:
    offset = 0
    for current_line, line in enumerate(raw.splitlines(keepends=True), start=1):
        if current_line == line_number:
            return offset
        offset += len(line)
    raise ValueError(f"line {line_number} does not exist in journal")


def _replace_text_unlocked(
    target: Path,
    data: str,
    *,
    encoding: str,
    durability: JournalDurabilityProfile,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("w", encoding=encoding) as handle:
            handle.write(data)
            _sync_handle(handle, durability)
        temp_path.replace(target)
    except BaseException:
        with suppress(FileNotFoundError):
            temp_path.unlink()
        raise


def _diagnostic(
    code: str,
    message: str,
    path: Path,
    line_number: int,
) -> JournalDiagnostic:
    return JournalDiagnostic(
        code=code,
        message=message,
        source_path=path,
        line_number=line_number,
    )


def _prepare_lock_byte(handle: Any) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    handle.seek(0)


def _is_windows() -> bool:
    return os.name == "nt"


def _load_fcntl() -> Any:
    return importlib.import_module("fcntl")


def _load_msvcrt() -> Any:
    return importlib.import_module("msvcrt")


__all__ = [
    "JournalFileError",
    "JsonlJournal",
    "LegacyJsonConstant",
    "LegacyJsonlParsedLine",
    "LockFactory",
    "LockMode",
    "append_jsonl_record",
    "append_jsonl_records",
    "journal_file_lock",
    "load_jsonl",
    "parse_legacy_jsonl_line",
    "write_jsonl",
]
