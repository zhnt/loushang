from __future__ import annotations

import errno
import importlib
import json
import os
import re
import stat
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar, cast

from loushang.foundation.json import (
    JsonValueError,
    require_json_mapping,
    validate_json_value,
)
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
_JSONL_LINE_ENDING = re.compile(r"\r\n|\r|\n")


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


class JournalLockUnavailable(BlockingIOError):
    """A requested non-blocking journal lock is currently held elsewhere."""

    def __init__(self, *, path: Path) -> None:
        super().__init__(f"Journal lock is unavailable: {path.name}")
        self.path = path


@contextmanager
def journal_file_lock(
    path: Path,
    mode: LockMode,
    *,
    lock_suffix: str = ".lock",
    blocking: bool = True,
    create: bool = True,
    is_windows: Callable[[], bool] | None = None,
    load_fcntl: Callable[[], Any] | None = None,
    load_msvcrt: Callable[[], Any] | None = None,
) -> Iterator[None]:
    if type(blocking) is not bool:
        raise TypeError("Journal lock blocking mode must be a built-in bool")
    if type(create) is not bool:
        raise TypeError("Journal lock creation mode must be a built-in bool")
    lock_path = path.with_name(f"{path.name}{lock_suffix}")
    if create:
        lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _open_lock_file(lock_path, create=create) as handle:
        if create:
            _fchmod_private(handle.fileno())
            _prepare_lock_byte(handle)
        else:
            opened = os.fstat(handle.fileno())
            getuid = getattr(os, "getuid", None)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (os.name == "posix" and opened.st_mode & 0o077)
                or (
                    os.name == "posix"
                    and callable(getuid)
                    and opened.st_uid != getuid()
                )
            ):
                raise OSError("Journal lock is not a private regular file")
        windows = (is_windows or _is_windows)()
        if windows:
            msvcrt = (load_msvcrt or _load_msvcrt)()
            operation = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            try:
                msvcrt.locking(handle.fileno(), operation, 1)
            except OSError as exc:
                if not blocking and exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise JournalLockUnavailable(path=lock_path) from exc
                raise
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        fcntl = (load_fcntl or _load_fcntl)()
        operation = fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(handle.fileno(), operation)
        except OSError as exc:
            if not blocking and exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise JournalLockUnavailable(path=lock_path) from exc
            raise
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def journal_file_lock_at(
    directory_fd: int,
    name: str,
    mode: LockMode,
    *,
    blocking: bool = True,
    create: bool = False,
) -> Iterator[None]:
    """Lock one private regular file relative to a pinned directory."""

    if os.name != "posix" or os.open not in os.supports_dir_fd:
        raise OSError("Descriptor-relative journal locks are unavailable")
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError("Descriptor-relative journal lock name must be one component")
    if type(blocking) is not bool:
        raise TypeError("Journal lock blocking mode must be a built-in bool")
    if type(create) is not bool:
        raise TypeError("Journal lock creation mode must be a built-in bool")
    flags = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    if create:
        flags |= os.O_CREAT
    descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    with os.fdopen(descriptor, "r+b") as handle:
        if create:
            _fchmod_private(handle.fileno())
        opened = os.fstat(handle.fileno())
        getuid = getattr(os, "getuid", None)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_mode & 0o077
            or (callable(getuid) and opened.st_uid != getuid())
        ):
            raise OSError("Journal lock is not a private regular file")
        fcntl = _load_fcntl()
        operation = fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(handle.fileno(), operation)
        except OSError as exc:
            if not blocking and exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise JournalLockUnavailable(path=Path(name)) from exc
            raise
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
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        existed = target.exists()
        with target.open("a", encoding=format_profile.encoding) as handle:
            _fchmod_private(handle.fileno())
            handle.write(line)
            handle.write(format_profile.newline)
            _sync_handle(handle, durability)
        if not existed:
            _sync_parent_directory(target, durability)


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
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        existed = target.exists()
        with target.open("a", encoding=format_profile.encoding) as handle:
            _fchmod_private(handle.fileno())
            handle.write(payload)
            _sync_handle(handle, durability)
        if not existed:
            _sync_parent_directory(target, durability)


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


def decode_jsonl(
    raw: str,
    *,
    target: str | Path,
    record_codec: JournalRecordCodec[R],
    header_codec: JournalHeaderCodec[H] | None = None,
    load_policy: JournalLoadPolicy = JournalLoadPolicy(),
) -> JsonlSnapshot[H, R]:
    """Decode an already-authorized JSONL snapshot without reopening a path."""

    if not isinstance(raw, str):
        raise TypeError("JSONL source must be text")
    return _decode_jsonl(
        raw,
        target=Path(target),
        record_codec=record_codec,
        header_codec=header_codec,
        load_policy=load_policy,
    )


def _decode_jsonl(
    raw: str,
    *,
    target: Path,
    record_codec: JournalRecordCodec[R],
    header_codec: JournalHeaderCodec[H] | None,
    load_policy: JournalLoadPolicy,
) -> JsonlSnapshot[H, R]:

    physical_lines = _split_jsonl_physical_lines(raw)
    numbered_lines = [
        (line_number, line)
        for line_number, line in enumerate(physical_lines, start=1)
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
    unterminated_tail_line = (
        len(physical_lines) if raw and not _has_trailing_newline(raw) else None
    )
    for line_number, line in record_lines:
        is_partial_tail = line_number == unterminated_tail_line
        if is_partial_tail and load_policy.partial_tail != "raise":
            diagnostics.append(
                _diagnostic(
                    "partial_journal_tail",
                    "Journal record was skipped because it is incomplete or invalid.",
                    target,
                    line_number,
                )
            )
            continue
        try:
            value = _load_mapping(
                line, path=target, line_number=line_number, kind="record"
            )
            record = record_codec.decode_record(value)
            if is_partial_tail:
                raise JournalFileError(
                    "Journal record is missing its commit newline",
                    path=target,
                    code="partial_journal_tail",
                    line_number=line_number,
                )
            records.append(record)
        except Exception as exc:
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

    if (
        unterminated_tail_line is not None
        and not physical_lines[-1].strip()
        and load_policy.partial_tail != "raise"
    ):
        diagnostics.append(
            _diagnostic(
                "partial_journal_tail",
                "Journal trailing whitespace was skipped because it is incomplete.",
                target,
                unterminated_tail_line,
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
        validate_json_value(value, name=f"journal_{kind}")
    except JsonValueError as exc:
        raise JournalFileError(
            f"Journal {kind} contains a value outside strict JSON",
            path=path,
            code=f"invalid_{kind}_value",
            line_number=line_number,
        ) from exc
    return value


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


def _fchmod_private(descriptor: int) -> None:
    fchmod = getattr(os, "fchmod", None)
    if callable(fchmod):
        fchmod(descriptor, 0o600)


def _has_trailing_newline(raw: str) -> bool:
    return raw.endswith(("\n", "\r"))


def _split_jsonl_physical_lines(raw: str) -> list[str]:
    """Split only on JSONL CR/LF framing, never Unicode string content."""

    if not raw:
        return []
    lines = _JSONL_LINE_ENDING.split(raw) if "\r" in raw else raw.split("\n")
    if _has_trailing_newline(raw):
        lines.pop()
    return lines


def _line_start_offset(raw: str, line_number: int) -> int:
    if line_number < 1:
        raise ValueError("line number must be positive")
    if line_number == 1 and raw:
        return 0
    for ending_number, match in enumerate(
        _JSONL_LINE_ENDING.finditer(raw),
        start=1,
    ):
        if ending_number == line_number - 1 and match.end() < len(raw):
            return match.end()
    raise ValueError(f"line {line_number} does not exist in journal")


def _replace_text_unlocked(
    target: Path,
    data: str,
    *,
    encoding: str,
    durability: JournalDurabilityProfile,
) -> None:
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("w", encoding=encoding) as handle:
            _fchmod_private(handle.fileno())
            handle.write(data)
            _sync_handle(handle, durability)
        temp_path.replace(target)
        _sync_parent_directory(target, durability)
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


@contextmanager
def _open_lock_file(path: Path, *, create: bool) -> Iterator[Any]:
    if os.name == "posix":
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not nofollow:
            raise OSError("No-follow journal lock opens are unavailable")
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | nofollow
        if create:
            flags |= os.O_CREAT
        else:
            flags |= getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "r+b") as handle:
            opened = os.fstat(handle.fileno())
            getuid = getattr(os, "getuid", None)
            if not stat.S_ISREG(opened.st_mode) or (
                callable(getuid) and opened.st_uid != getuid()
            ):
                raise OSError("Journal lock is not a private regular file")
            yield handle
        return

    if os.name == "nt":
        with _open_windows_lock_file(path, create=create) as handle:
            yield handle
        return

    metadata = path.lstat() if not create else None
    if metadata is not None and _is_link_or_reparse(metadata):
        raise OSError("Journal lock cannot be a symlink or reparse point")
    with path.open("a+b" if create else "r+b") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or _is_link_or_reparse(opened):
            raise OSError("Journal lock is not a private regular file")
        if metadata is not None and not os.path.samestat(metadata, opened):
            raise OSError("Journal lock identity changed while opening")
        yield handle


@contextmanager
def _open_windows_lock_file(path: Path, *, create: bool) -> Iterator[Any]:
    """Open a regular Windows lock without following a reparse point.

    The handle intentionally omits ``FILE_SHARE_DELETE``.  While it is open,
    Windows cannot replace the lock file or rename its parent directory; this
    pins the already-validated private root for portable compatibility reads.
    """

    import ctypes
    import msvcrt
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL")
    kernel32 = win_dll("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    generic_read_write = 0x80000000 | 0x40000000
    share_read_write = 0x00000001 | 0x00000002
    open_existing = 3
    open_always = 4
    file_attribute_normal = 0x00000080
    file_flag_open_reparse_point = 0x00200000
    handle = create_file(
        str(path),
        generic_read_write,
        share_read_write,
        None,
        open_always if create else open_existing,
        file_attribute_normal | file_flag_open_reparse_point,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        get_last_error = getattr(ctypes, "get_last_error")
        win_error = getattr(ctypes, "WinError")
        raise win_error(get_last_error())
    try:
        open_osfhandle = getattr(msvcrt, "open_osfhandle")
        descriptor = open_osfhandle(
            handle,
            os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
        )
    except BaseException:
        close_handle(handle)
        raise
    try:
        opened_file = os.fdopen(descriptor, "r+b")
    except BaseException:
        os.close(descriptor)
        raise
    with opened_file as opened_handle:
        path_metadata = path.lstat()
        opened = os.fstat(opened_handle.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_link_or_reparse(path_metadata)
            or _is_link_or_reparse(opened)
            or not os.path.samestat(path_metadata, opened)
        ):
            raise OSError("Journal lock is not a direct regular file")
        yield opened_handle


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(
        stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_reparse_tag", 0)
        or (
            reparse_attribute
            and getattr(metadata, "st_file_attributes", 0) & reparse_attribute
        )
    )


def _sync_parent_directory(
    target: Path,
    durability: JournalDurabilityProfile,
) -> None:
    """Durably establish a newly created or atomically replaced entry."""

    if not durability.fsync or os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(target.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
    "decode_jsonl",
    "journal_file_lock",
    "journal_file_lock_at",
    "load_jsonl",
    "parse_legacy_jsonl_line",
    "write_jsonl",
]
