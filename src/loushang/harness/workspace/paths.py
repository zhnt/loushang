from __future__ import annotations

import re
import stat
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path
from types import TracebackType

PathNormalizer = Callable[[str], str]
PathVariantProvider = Callable[[Path], Iterable[Path]]

_UNICODE_SPACES_RE = re.compile(r"[\u00a0\u2000-\u200a\u202f\u205f\u3000]")
_NARROW_NO_BREAK_SPACE = "\u202f"


def expand_user_path(path: str | Path) -> Path:
    text = _path_text(path)
    if text == "~":
        return Path.home()
    if text.startswith("~/"):
        return Path(str(Path.home()) + text[1:])
    return Path(text)


def resolve_path_from_cwd(
    path: str | Path,
    *,
    cwd: str | Path | None,
) -> Path:
    resolved = expand_user_path(path)
    if resolved.is_absolute():
        return resolved
    base = Path.cwd() if cwd is None else expand_user_path(cwd)
    return base / resolved


def resolve_workspace_path(
    path: str | Path,
    *,
    cwd: str | Path | None,
    normalizers: Iterable[PathNormalizer] = (),
    variant_providers: Iterable[PathVariantProvider] = (),
) -> Path:
    text = _path_text(path)
    for normalizer in normalizers:
        text = _normalized_path_text(normalizer(text))

    selected = resolve_path_from_cwd(text, cwd=cwd)
    if selected.exists():
        return selected.resolve()

    for provider in variant_providers:
        for variant in provider(selected):
            candidate = variant if variant.is_absolute() else selected.parent / variant
            if candidate.exists():
                return candidate.resolve()
    return selected.resolve()


def canonicalize_workspace_path(path: str | Path) -> Path:
    canonical = Path(_path_text(path))
    if not canonical.is_absolute():
        raise ValueError("path must be absolute")
    return canonical.resolve()


def resolve_path_inside_workspace(
    path: str | Path,
    workspace: Path,
    *,
    error_type: type[Exception],
    message: str,
) -> Path:
    """Resolve an input path and require its target inside the canonical workspace."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(workspace):
        raise error_type(message)
    return resolved


def normalize_unicode_spaces(path: str) -> str:
    return _UNICODE_SPACES_RE.sub(" ", path)


def user_input_path_variants(path: Path) -> tuple[Path, ...]:
    path_text = str(path)
    nfd_variant = unicodedata.normalize("NFD", path_text)
    variants = (
        _macos_screenshot_path_variant(path_text),
        nfd_variant,
        _curly_quote_path_variant(path_text),
        _curly_quote_path_variant(nfd_variant),
    )
    return tuple(Path(variant) for variant in dict.fromkeys(variants) if variant != path_text)


def _path_text(path: str | Path) -> str:
    if isinstance(path, Path):
        return str(path)
    if isinstance(path, str) and path:
        return path
    raise TypeError("path must be a non-empty string or Path")


def _normalized_path_text(path: object) -> str:
    if isinstance(path, str) and path:
        return path
    raise TypeError("path normalizers must return a non-empty string")


def _macos_screenshot_path_variant(path: str) -> str:
    return re.sub(r" (AM|PM)\.", rf"{_NARROW_NO_BREAK_SPACE}\1.", path, flags=re.IGNORECASE)


def _curly_quote_path_variant(path: str) -> str:
    return path.replace("'", "\u2019")


def require_workspace_directory(path: str | Path, *, unavailable: str) -> Path:
    """Resolve an existing workspace before an owner checks its scope."""
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(unavailable)
    return root


def capture_workspace_directory_identity(
    workspace: Path, *, unavailable: str
) -> tuple[int, int]:
    """Capture the root itself after the caller's admission checks."""
    identity = read_workspace_directory_identity(workspace)
    if identity is None:
        raise ValueError(unavailable)
    return identity


def read_workspace_directory_identity(workspace: Path) -> tuple[int, int] | None:
    """Observe the directory itself, leaving filesystem errors to the caller."""
    metadata = workspace.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        return None
    return metadata.st_dev, metadata.st_ino


def is_workspace_directory_identity(identity: object) -> bool:
    return (
        type(identity) is tuple
        and len(identity) == 2
        and all(type(item) is int and item >= 0 for item in identity)
    )


def assert_workspace_directory_identity(
    workspace: Path,
    identity: tuple[int, int],
    *,
    changed: Callable[[], Exception],
) -> None:
    """Recheck one previously captured workspace directory, without recapture."""
    try:
        metadata = workspace.lstat()
        current = workspace.resolve(strict=True)
    except OSError as exc:
        raise changed() from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or current != workspace
        or (metadata.st_dev, metadata.st_ino) != identity
    ):
        raise changed()


class WorkspaceOperationGuard:
    """Check the bound workspace before work and before publishing success."""

    def __init__(self, check: Callable[[], None] | None) -> None:
        self._check = check

    def __enter__(self) -> None:
        if self._check is not None:
            self._check()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None and self._check is not None:
            self._check()
