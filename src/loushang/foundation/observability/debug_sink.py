from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from ..json import JSONValue
from ._time import utc_now_iso
from .context import LogContext
from .records import DebugEventRecord, ProblemRecord


class DebugLogSink:
    def __init__(
        self,
        path: str | Path,
        *,
        latest_path: str | Path | None = None,
        max_bytes: int = 20 * 1024 * 1024,
        backup_count: int = 5,
    ) -> None:
        self.path = Path(path)
        self.latest_path = Path(latest_path) if latest_path is not None else None
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = RLock()

    def write_log(
        self,
        *,
        level: str,
        module: str,
        component: str | None,
        message: str,
        context: LogContext,
        details: dict[str, JSONValue],
    ) -> None:
        parts = [
            level.upper(),
            module,
            _format_optional("component", component),
            _format_optional("session", context.session_id),
            _format_optional("run", context.run_id),
            _format_inline(message),
            _format_details(details),
        ]
        self._write_line(f"{utc_now_iso()} " + " ".join(part for part in parts if part))

    def write_problem(self, record: ProblemRecord) -> None:
        parts = [
            "PROBLEM",
            record.severity,
            record.code,
            _format_optional("source", record.source),
            _format_optional("module", record.module),
            _format_optional("component", record.component),
            _format_optional("session", record.session_id),
            _format_optional("run", record.run_id),
            _format_optional("recoverable", record.recoverable),
            _format_inline(record.message),
            _format_details(record.details),
        ]
        self._write_line(f"{record.time} " + " ".join(part for part in parts if part))

    def write_debug_event(self, record: DebugEventRecord) -> None:
        parts = [
            "DEBUG_EVENT",
            record.scope,
            record.name,
            _format_optional("module", record.module),
            _format_optional("component", record.component),
            _format_optional("session", record.session_id),
            _format_optional("run", record.run_id),
            _format_details(record.data),
        ]
        self._write_line(f"{record.time} " + " ".join(part for part in parts if part))

    def _write_line(self, line: str) -> None:
        data = f"{line}\n".encode("utf-8")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(len(data))
            with self.path.open("ab") as handle:
                handle.write(data)
            self._update_latest()

    def _rotate_if_needed(self, next_bytes: int) -> None:
        if self.max_bytes <= 0 or self.backup_count <= 0 or not self.path.exists():
            return
        if self.path.stat().st_size + next_bytes <= self.max_bytes:
            return

        for index in range(self.backup_count - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            target = self.path.with_name(f"{self.path.name}.{index + 1}")
            if source.exists():
                source.replace(target)
        self.path.replace(self.path.with_name(f"{self.path.name}.1"))

    def _update_latest(self) -> None:
        if self.latest_path is None:
            return
        if _same_path(self.latest_path, self.path):
            return
        self.latest_path.parent.mkdir(parents=True, exist_ok=True)
        if self.latest_path.exists() or self.latest_path.is_symlink():
            self.latest_path.unlink()
        try:
            self.latest_path.symlink_to(self.path.resolve())
        except OSError:
            self.latest_path.write_text(str(self.path), encoding="utf-8")


def _format_optional(name: str, value: object | None) -> str:
    if value is None:
        return ""
    return f"{name}={_format_inline(str(value))}"


def _format_details(details: dict[str, JSONValue]) -> str:
    return " ".join(f"{key}={_format_detail_value(value)}" for key, value in sorted(details.items()))


def _format_detail_value(value: JSONValue) -> str:
    if isinstance(value, str):
        return _format_inline(value)
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _format_inline(value: str) -> str:
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)
