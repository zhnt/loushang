"""Drive the exact built-in Wheel recipe through the selected native operation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from loushang.coding.package import builtin_wheel as _binding


class ExactWheelSourceOperation(Protocol):
    def __call__(
        self, source_root: Path, *, filename: str, body: bytes, label: str
    ) -> tuple[Path, str, int]: ...


def access_base_wheel(
    source_root: Path, *, operation: ExactWheelSourceOperation
) -> _binding.CodingBaseProductWheelArtifactV1:
    path, digest, byte_count = operation(
        source_root,
        filename=_binding.CODING_BASE_PRODUCT_WHEEL_FILENAME,
        body=_binding.build_coding_base_product_wheel(),
        label="base",
    )
    return _binding.CodingBaseProductWheelArtifactV1(path, digest, byte_count)


def access_capability_wheels(
    source_root: Path, *, operation: ExactWheelSourceOperation
) -> tuple[_binding.CodingCapabilityProductWheelArtifactV1, ...]:
    artifacts = []
    for plugin_id, spec in _binding._CAPABILITY_SPECS.items():
        path, digest, byte_count = operation(
            source_root,
            filename=spec.filename,
            body=_binding.build_coding_capability_product_wheel(plugin_id),
            label="Capability",
        )
        artifacts.append(
            _binding.CodingCapabilityProductWheelArtifactV1(
                plugin_id=plugin_id,
                path=path,
                artifact_digest=digest,
                byte_count=byte_count,
            )
        )
    return tuple(artifacts)
