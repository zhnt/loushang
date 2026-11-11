from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Iterator, Mapping
from contextlib import (
    AbstractContextManager,
    ExitStack,
    contextmanager,
    nullcontext,
    suppress,
)
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loushang.foundation.json import _unique_json_object_hook

if TYPE_CHECKING:
    from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
        _PinnedWindowsAuthority,
    )


def _read_stable_json_patch(
    path: Path, *, maximum_bytes: Callable[[], int], label: str
) -> tuple[bool, str | None, dict[str, object]]:
    """Read one bounded stable patch before any config lock is created."""
    from loushang.harness.resources.packages._file_consumption import (
        DescriptorReader,
        consume_file,
    )

    adapter: AbstractContextManager[_WindowsSettingsFile | _PosixSettingsFile] = (
        _windows_settings_file(path)
        if os.name == "nt"
        else nullcontext(_PosixSettingsFile(path))
    )
    with ExitStack() as stack:
        try:
            source = stack.enter_context(adapter)
            before = source.stat()
        except FileNotFoundError:
            return False, None, {}
        getuid = getattr(os, "getuid", None)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (callable(getuid) and before.st_uid != getuid())
            or before.st_size > maximum_bytes()
        ):
            raise ValueError(f"{label} file is unsafe")
        descriptor = source.open()
        stack.callback(os.close, descriptor)
        opened = os.fstat(descriptor)
        if _stable_file_identity(opened) != _stable_file_identity(before):
            raise ValueError(f"{label} changed during read")
        buffer = BytesIO()
        consume_file(
            DescriptorReader(descriptor),
            destination=buffer,
            max_bytes=maximum_bytes,
            hash_content=False,
            size_error=lambda: ValueError(f"{label} file exceeds budget"),
        )
        raw = buffer.getvalue()
        after = os.fstat(descriptor)
        visible = source.stat()
        if _stable_file_identity(after) != _stable_file_identity(
            before
        ) or _stable_file_identity(visible) != _stable_file_identity(before):
            raise ValueError(f"{label} changed during read")
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
        )
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"{label} are not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} must be an object")
    return True, sha256(raw).hexdigest(), decoded


class _PosixSettingsFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    def stat(self) -> os.stat_result:
        return self._path.lstat()

    def open(self) -> int:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        return os.open(self._path, flags)


class _WindowsSettingsFile:
    def __init__(self, parent: _PinnedWindowsAuthority, name: str) -> None:
        self._parent = parent
        self._name = name

    def stat(self) -> os.stat_result:
        from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
            windows_stat_at,
        )

        # Use handle-based metadata on both sides of the identity comparison.
        return windows_stat_at(self._parent.descriptor, self._name)

    def open(self) -> int:
        from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
            open_windows_regular_file_at,
        )

        return open_windows_regular_file_at(
            self._parent.descriptor, self._name, create_new=False, write=False
        )


@contextmanager
def _windows_settings_file(path: Path) -> Iterator[_WindowsSettingsFile]:
    from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
        _PinnedWindowsAuthority,
    )

    parent = _PinnedWindowsAuthority.open(path.parent)
    try:
        yield _WindowsSettingsFile(parent, path.name)
    finally:
        try:
            parent.assert_visible()
        finally:
            parent.close()


def _stable_file_identity(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


_reject_duplicate_keys = _unique_json_object_hook(
    lambda: "duplicate settings key",
)


def _reject_non_json_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


class JsonConfigStore:
    def __init__(
        self,
        *,
        encoding: str = "utf-8",
        ensure_ascii: bool = False,
        indent: int = 2,
        sort_keys: bool = True,
    ) -> None:
        self.encoding = encoding
        self.ensure_ascii = ensure_ascii
        self.indent = indent
        self.sort_keys = sort_keys

    def load(self, path: Path) -> Mapping[str, object]:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding=self.encoding))
        if not isinstance(payload, Mapping):
            raise ValueError(f"Config payload must be a JSON object: {path}")
        return cast(Mapping[str, object], payload)

    def save(self, path: Path, patch: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            temp_path.write_text(
                json.dumps(
                    dict(patch),
                    ensure_ascii=self.ensure_ascii,
                    indent=self.indent,
                    sort_keys=self.sort_keys,
                ),
                encoding=self.encoding,
            )
            temp_path.replace(path)
        except BaseException:
            with suppress(FileNotFoundError):
                temp_path.unlink()
            raise


__all__ = ["JsonConfigStore"]
