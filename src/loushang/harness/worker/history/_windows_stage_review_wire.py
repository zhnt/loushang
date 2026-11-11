"""Wire traversal for the existing four Windows stage-review record formats.

Only pure JSON traversal is shared. Concrete records retain their own fields,
semantic admission, fingerprint domain, limits and public error constructors.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.worker.history._base_codec import _unchanged


class _WindowsStageReviewWireMethods:
    __slots__ = ()
    _record_kind: ClassVar[str]
    _record_error: ClassVar[type[Exception]]
    _record_error_code: ClassVar[str]
    _record_schema: ClassVar[RecordSchema]

    @classmethod
    def _record_maximum(cls) -> int:
        raise NotImplementedError

    @classmethod
    def _bind_record_schema(cls) -> None:
        cls._record_schema = RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField(
                "directory_identities",
                decoder=lambda values: tuple((p, tuple(i)) for p, i in values),
            ),
            *(
                RecordField(
                    name,
                    decoder=lambda v: None if v is None else tuple(v),
                )
                for name in ("stage_identity", "marker_identity", "executable_identity")
                if name != "marker_identity" or cls._record_kind != "partial"
            ),
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        if type(raw) is not bytes or not raw or len(raw) > cls._record_maximum():
            raise cls._record_error(cls._record_error_code)
        kind = cls._record_kind
        label = {
            "full": "Windows Worker stage review",
            "crash": "Windows Worker crash stage review",
            "partial": "Windows Worker partial-stage review",
            "reserved": "Windows Worker reserved review",
        }[kind]
        detail = label.removesuffix(" review") if kind == "crash" else label
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value) != cls._record_schema.keys | {"version"}
                or value["version"] != 1
            ):
                suffix = "shape changed" if kind == "crash" else "fields changed"
                raise ValueError(f"{label} {suffix}")
            directories = value["directoryIdentities"]
            invalid_directories = type(directories) is not list or any(
                type(item) is not list or len(item) != 2 or type(item[1]) is not list
                for item in directories
            )
            identities = ("stageIdentity", "markerIdentity", "executableIdentity")
            if kind in {"full", "crash"}:
                if invalid_directories:
                    raise ValueError(f"{detail} directories changed")
                for name in identities:
                    if type(value[name]) is not list:
                        raise ValueError(f"{detail} identity changed")
            elif kind == "reserved":
                if invalid_directories or any(
                    type(value[n]) is not list for n in identities
                ):
                    raise ValueError(
                        "Windows Worker reserved review identities changed"
                    )
            else:
                if invalid_directories or type(value["stageIdentity"]) is not list:
                    raise ValueError("Windows Worker partial-stage identities changed")
                executable = value["executableIdentity"]
                if executable is not None and type(executable) is not list:
                    raise ValueError(
                        "Windows Worker partial-stage file identity changed"
                    )
            record = cls._record_schema.decode(cast(Callable[..., Self], cls), value)
            if record.to_bytes() != raw:
                suffix = "bytes changed" if kind == "partial" else "encoding changed"
                raise ValueError(f"{detail} {suffix}")
            return record
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise cls._record_error(cls._record_error_code) from error

    _from_record_bytes = from_bytes

    def to_bytes(self) -> bytes:
        raise NotImplementedError
