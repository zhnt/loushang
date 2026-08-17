from __future__ import annotations

import subprocess
import sys


def test_testing_playback_entrypoints_stay_product_neutral_on_fresh_import() -> None:
    script = """
import importlib
import sys

for module_name in (
    "loushang.harnesstui.testing.ports",
    "loushang.harnesstui.testing.input_playback",
    "loushang.harnesstui.testing.performance",
    "loushang.harnesstui.testing.screen_loop_playback",
):
    importlib.import_module(module_name)

forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
    "loushang.harness",
)
forbidden = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
