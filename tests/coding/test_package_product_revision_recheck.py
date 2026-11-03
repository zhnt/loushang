from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.package_product_revisions import _ProductSelectedRevisionHandle
from loushang.harness.resources.plugins.revisions import PluginRevisionError


def test_pinned_product_revision_rechecks_selection_without_recapturing_bytes() -> None:
    selected = SimpleNamespace(
        snapshot=SimpleNamespace(
            installation_key=SimpleNamespace(plugin_id="coding.base")
        )
    )

    class Runtime:
        def __init__(self) -> None:
            self.rechecks = 0
            self.stale = False

        def assert_selected_plugin_manifest_current(self, candidate: object) -> None:
            assert candidate is selected
            self.rechecks += 1
            if self.stale:
                raise ValueError("Product selection changed")

        def capture_selected_plugin_manifest_for(self, *args, **kwargs) -> None:
            raise AssertionError("Pinned bytes must not be recaptured for a recheck")

    runtime = Runtime()
    handle = object.__new__(_ProductSelectedRevisionHandle)
    handle.root = Path("/__loushang_product_snapshot__/pinned")
    handle._runtime = runtime
    handle._selected = selected
    handle._files = {"definition.py": b"pinned definition"}
    handle._closed = False

    assert handle.open_file("definition.py").read() == b"pinned definition"
    assert runtime.rechecks == 1

    runtime.stale = True
    with pytest.raises(PluginRevisionError) as changed:
        handle.open_file("definition.py")
    assert changed.value.code == "plugin_revision_changed"
    assert runtime.rechecks == 2
