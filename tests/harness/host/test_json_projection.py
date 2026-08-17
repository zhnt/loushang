from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.host.json_projection import (
    HostJsonProjectionError,
    project_host_value,
)


def test_host_json_projection_supports_documented_values_and_rejects_cycles() -> None:
    @dataclass(frozen=True)
    class Result:
        path: Path
        values: tuple[int, int]

    value = Result(path=Path("report.md"), values=(1, 2))

    assert project_host_value(value) == {
        "path": "report.md",
        "values": [1, 2],
    }

    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(
        HostJsonProjectionError,
        match=r"rpc_output\[0\] cannot be projected to RPC JSON: circular reference",
    ):
        project_host_value(cyclic, name="rpc_output", surface="RPC")
