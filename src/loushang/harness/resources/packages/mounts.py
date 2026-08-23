from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loushang.harness.resources.plugins.revisions import VerifiedRevisionHandle
from loushang.harness.resources.types import RevisionResourceRef

if TYPE_CHECKING:
    from loushang.harness.resources.packages.source import PackageSourceConfig


@dataclass(frozen=True)
class PackageResourceMount:
    """Bind one Package root, optional filter, and optional revision lease."""

    root: Path
    source_filter: PackageSourceConfig | None = None
    enabled: bool = True
    content_digest: str | None = None
    revision_handle: VerifiedRevisionHandle | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        root = self.root.expanduser().resolve()
        object.__setattr__(self, "root", root)
        handle = self.revision_handle
        if handle is None:
            if self.content_digest is not None:
                raise ValueError(
                    "Package mount content digest requires a revision handle."
                )
            return
        if self.content_digest != handle.content_digest:
            raise ValueError(
                "Package mount content digest must match its revision handle."
            )
        try:
            root.relative_to(handle.root)
        except ValueError as exc:
            raise ValueError(
                "Verified Package mount root must belong to its revision handle."
            ) from exc

    @property
    def verified(self) -> bool:
        return self.revision_handle is not None

    def verify(self) -> None:
        handle = self.revision_handle
        if handle is not None:
            handle.verify()

    def close(self) -> None:
        handle = self.revision_handle
        if handle is not None:
            handle.close()

    def read_text(self, path: str | Path, *, encoding: str = "utf-8") -> str:
        candidate = self._contained_path(path)
        handle = self.revision_handle
        if handle is None:
            return candidate.read_text(encoding=encoding)
        relative = candidate.relative_to(handle.root).as_posix()
        with handle.open_file(relative) as stream:
            return stream.read().decode(encoding)

    def reference(
        self,
        path: str | Path,
        *,
        kind: Literal["file", "directory"] | None = None,
    ) -> RevisionResourceRef | None:
        candidate = self._contained_path(path)
        handle = self.revision_handle
        if handle is None:
            return None
        relative_path = candidate.relative_to(handle.root).as_posix()
        actual_kind = handle.entry_kind(relative_path)
        if kind is not None and kind != actual_kind:
            raise ValueError(
                f"Revision resource kind does not match verified entry: {candidate}"
            )
        return RevisionResourceRef(
            content_digest=handle.content_digest,
            relative_path=relative_path,
            kind=actual_kind,
        )

    def _contained_path(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path is outside Package mount: {candidate}") from exc
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError(f"Path is outside Package mount: {candidate}")
        return candidate


__all__ = ["PackageResourceMount"]
