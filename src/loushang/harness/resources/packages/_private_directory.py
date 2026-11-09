"""Prepare an owned private leaf without changing its caller's path policy."""

import os
import stat
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Literal


def prepare_private_directory(root: Path) -> None:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    before = root.lstat()
    if (
        not stat.S_ISDIR(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or bool(getattr(before, "st_reparse_tag", 0))
    ):
        raise OSError("private root is not a direct directory")
    getuid = getattr(os, "getuid", None)
    if os.name == "posix" and callable(getuid) and before.st_uid != getuid():
        raise PermissionError("private root belongs to another user")
    if os.name == "posix":
        root.chmod(0o700)
    if not os.path.samestat(before, root.lstat()):
        raise OSError("private root identity changed")


_PrivateStateErrorReason = Literal[
    "outside_base", "not_private", "journal_not_private", "handles_unavailable"
]
_PrivateStateErrorFactory = Callable[[_PrivateStateErrorReason], Exception]


def _supports_descriptor_relative_private_state_io() -> bool:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    return bool(
        os.name == "posix"
        and os.open in os.supports_dir_fd
        and nofollow
        and getattr(os, "O_DIRECTORY", 0)
    )


def _supports_portable_private_state_io() -> bool:
    """Return whether identity-checked Windows root descriptors are available."""

    return os.name == "nt"


def _uses_windows_directory_pins() -> bool:
    return os.name == "nt"


def _validate_private_directory_descriptor(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    getuid = getattr(os, "getuid", None)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_mode & 0o077
        or (callable(getuid) and metadata.st_uid != getuid())
    ):
        raise OSError("private root is not a private directory")


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


def _open_existing_private_state_root(
    root: Path,
    private_base: Path,
    *,
    error_factory: _PrivateStateErrorFactory,
) -> int | None:
    base = private_base.expanduser().absolute()
    root = root.expanduser().absolute()
    try:
        relative = root.relative_to(base)
    except ValueError:
        raise error_factory("outside_base") from None
    try:
        root.lstat()
    except FileNotFoundError:
        # An absent compatibility root is not private state yet.  Do not
        # require or mutate permissions on an unrelated existing home/base.
        return None
    except OSError:
        raise error_factory("not_private") from None
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDONLY | os.O_DIRECTORY | nofollow | getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(base, flags)
        _validate_private_directory_descriptor(descriptor)
        for part in relative.parts:
            child = os.open(part, flags, dir_fd=descriptor)
            try:
                _validate_private_directory_descriptor(child)
            except BaseException:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except FileNotFoundError:
        if descriptor is not None:
            os.close(descriptor)
        return None
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        raise error_factory("not_private") from None


def _capture_existing_private_directory_chain(
    root: Path,
    private_base: Path,
    *,
    error_factory: _PrivateStateErrorFactory,
) -> tuple[tuple[Path, os.stat_result], ...] | None:
    """Capture the exact private directory identities used by portable I/O."""

    base = private_base.expanduser().absolute()
    root = root.expanduser().absolute()
    try:
        relative = root.relative_to(base)
    except ValueError:
        raise error_factory("outside_base") from None
    try:
        root.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise error_factory("not_private") from None

    captured: list[tuple[Path, os.stat_result]] = []
    current = base
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        captured.append(
            (
                current,
                _validate_existing_private_directory(
                    current, error_factory=error_factory
                ),
            )
        )
    return tuple(captured)


def _validate_existing_private_directory(
    root: Path, *, error_factory: _PrivateStateErrorFactory
) -> os.stat_result:
    try:
        before = root.lstat()
        getuid = getattr(os, "getuid", None)
        if (
            not stat.S_ISDIR(before.st_mode)
            or _is_link_or_reparse(before)
            or (os.name == "posix" and before.st_mode & 0o077)
            or (os.name == "posix" and callable(getuid) and before.st_uid != getuid())
        ):
            raise OSError("private root is not a private direct directory")
        after = root.lstat()
        if not os.path.samestat(before, after):
            raise OSError("private root identity changed")
        return after
    except OSError:
        raise error_factory("not_private") from None


def _assert_private_directory_chain_stable(
    captured: tuple[tuple[Path, os.stat_result], ...],
    *,
    error_factory: _PrivateStateErrorFactory,
) -> None:
    for path, expected in captured:
        current = _validate_existing_private_directory(
            path, error_factory=error_factory
        )
        if not os.path.samestat(expected, current):
            raise OSError("private root identity changed")


@contextmanager
def _pin_portable_private_directory_chain(
    captured: tuple[tuple[Path, os.stat_result], ...],
    *,
    error_factory: _PrivateStateErrorFactory,
) -> Iterator[int | None]:
    """Anchor Windows child I/O to the validated workspace-root handle."""

    from .plugin_lifecycle.windows_quarantine import _open_windows_private_directory_pin

    if not _uses_windows_directory_pins():
        # Tests force the portable reader on POSIX to exercise its common
        # sequencing; production reaches this branch only on Windows.
        yield None
        return
    with ExitStack() as pins:
        root_descriptor: int | None = None
        for path, expected in captured:
            root_descriptor = pins.enter_context(
                _open_windows_private_directory_pin(
                    path, expected, error_factory=error_factory
                )
            )
        if root_descriptor is None:
            raise OSError("private state directory chain is empty")
        yield root_descriptor


def prepare_private_directory_tree(
    path: Path,
    *,
    private_base: Path,
    outside_base_error: Callable[[], Exception],
    private_error: Callable[[], Exception],
) -> None:
    """Original caller-owned tree preparation, retaining its lexical base policy."""
    base = private_base.expanduser().absolute()
    root = path.expanduser().absolute()
    try:
        relative = root.relative_to(base)
    except ValueError:
        raise outside_base_error() from None
    current = base
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        try:
            prepare_private_directory(current)
        except OSError:
            raise private_error() from None
