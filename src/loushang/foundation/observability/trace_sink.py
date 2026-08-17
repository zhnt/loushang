from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from threading import RLock

from ..json import JSONValue
from .records import DebugEventRecord, ProblemRecord


class TraceJSONLSink:
    def __init__(
        self,
        path: str | Path,
        *,
        latest_path: str | Path | None = None,
        max_bytes: int = 50 * 1024 * 1024,
        backup_count: int = 3,
    ) -> None:
        self.path = Path(path)
        self.latest_path = Path(latest_path) if latest_path is not None else None
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = RLock()

    def write_problem(self, record: ProblemRecord) -> None:
        payload = {"kind": "problem", **record.to_dict()}
        self._write_json(payload)

    def write_debug_event(self, record: DebugEventRecord) -> None:
        payload = {"kind": "debug_event", **record.to_dict()}
        self._write_json(payload)

    def _write_json(self, payload: dict[str, JSONValue]) -> None:
        data = (
            json.dumps(_json_safe_payload(payload), ensure_ascii=False, sort_keys=True, allow_nan=False)
            + "\n"
        ).encode("utf-8")
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


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def _json_safe_payload(value: object) -> JSONValue:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, list | tuple):
        return [_json_safe_payload(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_safe_payload(item) for key, item in value.items()}
    return str(value)
