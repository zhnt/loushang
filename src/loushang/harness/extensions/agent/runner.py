"""Agent extension policy binding over the shared Harness runner."""

from __future__ import annotations

from collections.abc import Sequence

from loushang.harness.extensions.agent.loader import ExtensionLoader
from loushang.harness.extensions.runner import (
    ExtensionRunner as _HarnessExtensionRunner,
)
from loushang.harness.extensions.types import ExtensionDescriptor, LoadedExtension


class ExtensionRunner(_HarnessExtensionRunner):
    """Bind the Agent loader and policy to the shared dispatch runtime."""

    def __init__(
        self,
        extensions: Sequence[LoadedExtension | ExtensionDescriptor] | None = None,
    ) -> None:
        super().__init__(extensions, loader_factory=ExtensionLoader)


__all__ = ["ExtensionRunner"]
