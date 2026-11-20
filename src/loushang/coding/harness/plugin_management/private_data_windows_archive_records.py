"""Private-data record and proof programs over original nominal values."""

from __future__ import annotations

from loushang.coding.package import private_data_windows_archive_snapshot as _binding


def validate_archive(self: _binding.CodingWindowsArchBackupArchiveSnapshotV1) -> None:
    if (
        not _binding._digest(self.root_path_digest)
        or not _binding._valid_identity(self.root_identity)
        or not _binding.stat.S_ISDIR(self.root_identity[2])
        or not isinstance(self.files, _binding.CodingArchPrivateDataTargetSnapshotV1)
        or self.files.root_identity is None
        or not isinstance(self.manifest, _binding.CodingArchPrivateDataMemberV1)
        or self.manifest.relative_path != "manifest.json"
        or self.manifest.kind != "file"
    ):
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_01"])


def decode_archive(
    cls: type[_binding.CodingWindowsArchBackupArchiveSnapshotV1], value: object
) -> _binding.CodingWindowsArchBackupArchiveSnapshotV1:
    if type(value) is not dict or set(value) != {
        "files",
        "manifest",
        "rootIdentity",
        "rootPathDigest",
    }:
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_02"])
    identity = value["rootIdentity"]
    if type(identity) is not list or len(identity) != 5:
        raise ValueError(_binding._PRIVATE_DATA_RECORD_VALUES["value_03"])
    return cls(
        root_path_digest=value["rootPathDigest"],
        root_identity=tuple(identity),
        files=_binding.CodingArchPrivateDataTargetSnapshotV1.from_dict(value["files"]),
        manifest=_binding.CodingArchPrivateDataMemberV1.from_dict(value["manifest"]),
    )
