"""Private capture of the existing desired/migration compatibility inputs."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Protocol, TypeVar

from loushang.harness.journal import journal_file_lock_at, read_journal_file_at
from loushang.harness.journal.jsonl import _read_private_regular_text_at
from loushang.harness.resources.packages._private_directory import (
    _assert_private_directory_chain_stable,
    _capture_existing_private_directory_chain,
    _open_existing_private_state_root,
    _pin_portable_private_directory_chain,
    _PrivateStateErrorFactory,
    _supports_descriptor_relative_private_state_io,
    _supports_portable_private_state_io,
)


class _EnablementCaptureLayout(Protocol):
    @property
    def root(self) -> Path: ...
    @property
    def private_state_base(self) -> Path: ...
    @property
    def coordination_lock(self) -> Path: ...
    @property
    def desired_state(self) -> Path: ...
    @property
    def enablement_migration(self) -> Path: ...


CaptureT = TypeVar("CaptureT")


def _plugin_enablement_capture_lock_names(
    layout: _EnablementCaptureLayout,
) -> tuple[str, ...]:
    """Return the owner lock order for one cross-journal compatibility read."""

    return (
        f"{layout.coordination_lock.name}.lock",
        f"{layout.enablement_migration.name}.migration.lock",
        f"{layout.desired_state.name}.lock",
        f"{layout.enablement_migration.name}.lock",
    )


def _read_private_state_file(
    directory_fd: int,
    name: str,
    *,
    error_factory: _PrivateStateErrorFactory,
) -> str:
    if Path(name).name != name:
        raise ValueError("Private state filename must be one component")
    return _read_private_regular_text_at(
        directory_fd,
        name,
        encoding="utf-8",
        private_file_error=lambda: error_factory("journal_not_private"),
    )


@contextmanager
def _capture_existing_plugin_enablement_state(
    layout: _EnablementCaptureLayout,
    *,
    error_factory: _PrivateStateErrorFactory,
    capture_factory: Callable[[str, str], CaptureT],
) -> Iterator[CaptureT | None]:
    """Pin one private root and capture compatibility ledgers beneath it."""

    if not _supports_descriptor_relative_private_state_io():
        if _supports_portable_private_state_io():
            with _capture_existing_plugin_enablement_state_portable(
                layout, error_factory=error_factory, capture_factory=capture_factory
            ) as capture:
                yield capture
            return
        if not (
            _capture_existing_private_directory_chain(
                layout.root, layout.private_state_base, error_factory=error_factory
            )
            is not None
        ):
            yield None
            return
        raise error_factory("handles_unavailable")

    descriptor = _open_existing_private_state_root(
        layout.root, layout.private_state_base, error_factory=error_factory
    )
    if descriptor is None:
        yield None
        return
    try:
        with ExitStack() as locks:
            for name in _plugin_enablement_capture_lock_names(layout):
                locks.enter_context(
                    journal_file_lock_at(
                        descriptor,
                        name,
                        "exclusive",
                        create=True,
                    )
                )
            yield capture_factory(
                _read_private_state_file(
                    descriptor,
                    layout.desired_state.name,
                    error_factory=error_factory,
                ),
                _read_private_state_file(
                    descriptor,
                    layout.enablement_migration.name,
                    error_factory=error_factory,
                ),
            )
    finally:
        os.close(descriptor)


@contextmanager
def _capture_existing_plugin_enablement_state_portable(
    layout: _EnablementCaptureLayout,
    *,
    error_factory: _PrivateStateErrorFactory,
    capture_factory: Callable[[str, str], CaptureT],
) -> Iterator[CaptureT | None]:
    """Capture through lock and journal children rooted at one Windows handle."""

    directory_chain = _capture_existing_private_directory_chain(
        layout.root, layout.private_state_base, error_factory=error_factory
    )
    if directory_chain is None:
        yield None
        return
    try:
        with _pin_portable_private_directory_chain(
            directory_chain, error_factory=error_factory
        ) as descriptor:
            if descriptor is None:
                raise OSError("Windows private state root handle is unavailable")
            _assert_private_directory_chain_stable(
                directory_chain, error_factory=error_factory
            )
            with ExitStack() as locks:
                for index, name in enumerate(
                    _plugin_enablement_capture_lock_names(layout)
                ):
                    locks.enter_context(
                        journal_file_lock_at(
                            descriptor,
                            name,
                            "exclusive",
                            create=index > 0,
                        )
                    )
                _assert_private_directory_chain_stable(
                    directory_chain, error_factory=error_factory
                )
                capture = capture_factory(
                    read_journal_file_at(
                        descriptor,
                        layout.desired_state.name,
                    ),
                    read_journal_file_at(
                        descriptor,
                        layout.enablement_migration.name,
                    ),
                )
                _assert_private_directory_chain_stable(
                    directory_chain, error_factory=error_factory
                )
                yield capture
    except OSError:
        raise error_factory("not_private") from None
