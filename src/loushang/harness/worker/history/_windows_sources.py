"""Closed history names and borrowed source capture; no Product/GC authority."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages._file_consumption import consume_file
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)


@dataclass(frozen=True, slots=True)
class WindowsHistoryNames:
    exact: frozenset[str]
    patterns: tuple[re.Pattern[str], ...]

    def require_known(self, names: tuple[str, ...]) -> None:
        for name in names:
            if not name.casefold().startswith(("worker-", ".worker-")):
                continue
            if name not in self.exact and not any(
                pattern.fullmatch(name) is not None for pattern in self.patterns
            ):
                raise ValueError("Windows Worker GC state owner is unrecognized")


_SourceT = TypeVar("_SourceT")


@dataclass(frozen=True, slots=True)
class WindowsHistorySourceCapture(Generic[_SourceT]):
    names: WindowsHistoryNames
    source_file_type: Callable[..., _SourceT]
    non_source_names: frozenset[str]
    base_stage_names: frozenset[str]
    max_files: int
    max_file_bytes: int
    max_total_bytes: int

    @contextmanager
    def capture(
        self,
        root: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        allow_preparation_stage: bool,
        allow_checkpoint_stage: bool,
        allow_base_stage: bool,
    ) -> Iterator[tuple[tuple[str, ...], tuple[_SourceT, ...]]]:
        before = tuple(windows_listdir_at(root))
        self.names.require_known(before)
        if (
            (
                "worker-history-preparation-v1.json.stage" in before
                and not allow_preparation_stage
            )
            or (
                "worker-history-checkpoint-v1.json.stage" in before
                and not allow_checkpoint_stage
            )
            or (not allow_base_stage and self.base_stage_names.intersection(before))
        ):
            raise ValueError("Windows Worker history stage remains")
        names = tuple(
            sorted(
                name
                for name in before
                if name.casefold().startswith(("worker-", ".worker-"))
                and name not in self.non_source_names
            )
        )
        if any(name.casefold().endswith(".stage") for name in names):
            raise ValueError("Windows Worker history stage remains")
        if len(names) > self.max_files:
            raise ValueError("Windows Worker history inventory exceeds bound")
        files: list[_SourceT] = []
        total = 0
        for name in names:
            descriptor = open_windows_regular_file_at(
                root, name, create_new=False, write=False, read_control=True
            )
            with os.fdopen(descriptor, "rb") as source:
                acl.validate(source.fileno())
                if windows_regular_file_stream_names(source.fileno()) != ("::$DATA",):
                    raise ValueError("Windows Worker history stream changed")
                opened = os.fstat(source.fileno())
                size, digest = consume_file(
                    source,
                    max_bytes=min(self.max_file_bytes, self.max_total_bytes - total),
                    chunk_size=64 * 1024,
                    size_error=lambda: ValueError(
                        "Windows Worker history bytes exceed bound"
                    ),
                )
                total += size
                closed = os.fstat(source.fileno())
                if (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_size,
                    opened.st_mtime_ns,
                    opened.st_ctime_ns,
                ) != (
                    closed.st_dev,
                    closed.st_ino,
                    closed.st_size,
                    closed.st_mtime_ns,
                    closed.st_ctime_ns,
                ) or size != opened.st_size:
                    raise ValueError("Windows Worker history source changed")
                visible = windows_stat_at(root, name)
                if (
                    not os.path.samestat(closed, visible)
                    or visible.st_size != size
                    or visible.st_mtime_ns != closed.st_mtime_ns
                    or visible.st_ctime_ns != closed.st_ctime_ns
                ):
                    raise ValueError("Windows Worker history source changed")
                files.append(
                    self.source_file_type(
                        name=name,
                        size=size,
                        sha256_digest=digest,
                    )
                )
        yield before, tuple(files)
        if set(windows_listdir_at(root)) != set(before):
            raise ValueError("Windows Worker history inventory changed")
