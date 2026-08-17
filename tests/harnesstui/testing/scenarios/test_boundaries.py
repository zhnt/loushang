from __future__ import annotations

import importlib
import inspect
import subprocess
import sys

SCENARIO_MODULES = (
    "loushang.harnesstui.testing.scenarios.factory",
    "loushang.harnesstui.testing.scenarios.composer",
    "loushang.harnesstui.testing.scenarios.lifecycle",
    "loushang.harnesstui.testing.scenarios.terminal",
)


def test_shared_scenario_entrypoints_stay_product_neutral_on_fresh_import() -> None:
    modules = repr(SCENARIO_MODULES)
    script = f"""
import importlib
import sys

for module_name in {modules}:
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


def test_shared_scenario_recipes_do_not_own_coding_presentation_copy() -> None:
    forbidden_copy = (
        "›",
        "queued=",
        "Messages to be submitted",
        "Conversation interrupted",
        "Operation aborted",
        "Request cancelled",
    )

    for module_name in SCENARIO_MODULES:
        source = inspect.getsource(importlib.import_module(module_name))
        assert not any(text in source for text in forbidden_copy), module_name
