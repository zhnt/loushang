"""Transaction-local blob layout over an existing rooted IO operation."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from threading import Event

from loushang.harness.journal._rooted_io import RootedDirectory, RootedFile


class BlobTransactionIO:
    """Map only this authority's manifest/objects; retain no independent owner."""

    def __init__(self, data_root: Path, assets: RootedDirectory, session_id: str) -> None:
        self.root = data_root / "session-assets" / session_id
        self._assets, self._session_id = assets, session_id
        self._session: RootedDirectory | None = None
        self._objects: RootedDirectory | None = None
        self.created_objects: dict[Path, tuple[int, int]] = {}

    def pin_existing(self) -> None:
        with suppress(FileNotFoundError):
            self.objects()

    def track_settlement(self) -> Event:
        return self._assets.track_settlement()

    def check_binding(self) -> None:
        if self._session is not None:
            self._assets.check_child(self._session_id, self._session)
            if self._objects is not None:
                self._session.check_child("objects", self._objects)

    def directory(self, *, create: bool = False) -> RootedDirectory:
        if self._session is None:
            self._session = self._assets.child(self._session_id, create=create)
        return self._session

    def objects(self, *, create: bool = False) -> RootedDirectory:
        if self._objects is None:
            self._objects = self.directory(create=create).child("objects", create=create)
        return self._objects

    def prepare(self) -> None:
        self.objects(create=True)

    def file(self, path: Path) -> RootedFile:
        parts = path.relative_to(self.root).parts
        if parts == ("manifest.json",):
            return self.directory().file(parts[0])
        if len(parts) == 2 and parts[0] == "objects":
            return self.objects().file(parts[1])
        raise ValueError("blob IO path is outside its manifest/object authority")

    def stat(self, path: Path) -> os.stat_result:
        return self.directory().stat() if path == self.root else self.file(path).stat()

    def exists(self, path: Path) -> bool:
        try:
            self.stat(path)
        except FileNotFoundError:
            return False
        return True

    def unlink(self, path: Path, identity: tuple[int, int]) -> None:
        target = self.file(path)
        metadata = target.stat()
        if (metadata.st_dev, metadata.st_ino) != identity:
            raise OSError("blob file deletion identity changed")
        target.unlink_owned(identity)

    def remove_objects(self, files: list[tuple[str, tuple[int, int]]]) -> None:
        self.objects().remove_files(files)

    def retain_restore(self, payload: bytes, retained_ids: set[str], removed_ids: set[str], *,
                       root_preexisting: bool, limit: int) -> None:
        if self._assets.deletion_registered:
            return  # The complete deletion plan already owns recovery.
        directory = self.directory()
        objects = self._objects
        created = dict(self.created_objects)

        def recover(assets: RootedDirectory) -> None:
            root = assets.reborrow(directory)
            assets.check_child(self._session_id, root)
            if not root_preexisting:
                assets.remove_tree(self._session_id, expected=root, limit=limit, defer=True)
                return
            selected = root.reborrow(objects) if objects is not None else root.child("objects")
            root.check_child("objects", selected)
            root.file("manifest.json").atomic_write(payload)
            plan = []
            for name in removed_ids | {path.name for path in created}:
                if name in retained_ids:
                    continue
                identity = created.get(self.root / "objects" / name)
                if identity is None:
                    try:
                        status = selected.file(name).stat()
                    except FileNotFoundError:
                        continue
                    identity = status.st_dev, status.st_ino
                plan.append((name, identity))
            selected.queue_files(plan)

        self._assets.retain_cleanup(recover)

    def delete(self, *, expected_identity: tuple[int, int] | None, limit: int) -> bool:
        try:
            directory = self.directory()
        except FileNotFoundError:
            return False
        metadata = directory.stat()
        if expected_identity is not None and (metadata.st_dev, metadata.st_ino) != expected_identity:
            raise OSError("blob directory deletion identity changed")
        self._assets.remove_tree(self._session_id, expected=directory, limit=limit)
        self._session = self._objects = None
        return True
