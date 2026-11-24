"""Live references to already-admitted Host Workspace paths."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from loushang.appserver.execution.resources import ResourceV1
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.coding.hosted_workspace import CodingHostedWorkspace
from loushang.harness.artifacts import SessionBlobRef, SessionBlobStore

HOST_REFERENCE = "host-reference"


@dataclass(frozen=True, slots=True)
class HostReference:
    path: Path
    kind: Literal["file", "directory"]
    device: int
    inode: int

    def descriptor(self) -> bytes:
        return json.dumps(
            [str(self.path), self.kind, self.device, self.inode], ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")

    @classmethod
    def load(cls, store: SessionBlobStore, blob: SessionBlobRef) -> HostReference:
        path, kind, device, inode = json.loads(store.read_bytes(blob))
        if (type(path) is not str or kind not in {"file", "directory"}
                or any(type(value) is not int or value < 0 for value in (device, inode))):
            raise ValueError("invalid Host resource")
        return cls(Path(path), kind, device, inode)

    def resource(self, blob: SessionBlobRef) -> ResourceV1:
        return ResourceV1(blob.sha256, self.kind, "host_reference", "", 0, self.path.name)

    @classmethod
    def select(cls, workspace: CodingHostedWorkspace | None, value: str) -> HostReference:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("Host resource path must be absolute")
        path = path.resolve(strict=True)
        _require_workspace_path(workspace, path)
        info = path.stat(follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            kind: Literal["file", "directory"] = "directory"
        elif stat.S_ISREG(info.st_mode):
            kind = "file"
        else:
            raise ValueError("Host resource must be a directory or regular file")
        return cls(path, kind, info.st_dev, info.st_ino)

    def resolve(self, workspace: CodingHostedWorkspace | None, relative: str = ".") -> Path:
        # Resource paths are relative POSIX strings on every AppClient.
        child = PurePosixPath(relative)
        if ("\\" in relative or "\x00" in relative or ":" in relative or child.is_absolute() or ".." in child.parts):
            raise ValueError("invalid relative resource path")
        root = self.select(workspace, os.fspath(self.path))
        if root != self or (self.kind == "file" and child.parts):
            raise AppServiceError(AppErrorCodeV1.RESOURCE_UNAVAILABLE)
        target = (root.path / child).resolve(strict=False)
        if not target.is_relative_to(root.path):
            raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
        _require_workspace_path(workspace, target)
        return target


def _require_workspace_path(workspace: CodingHostedWorkspace | None, path: Path) -> None:
    if (workspace is None
            or not any(path.is_relative_to(root) for root in workspace.current_roots())
            or any(path.is_relative_to(root) for root in workspace.private_roots)):
        raise AppServiceError(AppErrorCodeV1.PERMISSION_DENIED)
