from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path


def test_channel_package_does_not_import_product_or_agent_runtime_layers() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/loushang/channel").glob("*.py")
        if path.name != "__pycache__"
    )

    assert "loushang.agent" not in source
    assert "loushang.coding" not in source
    assert "loushang.method" not in source
    assert "loushang.tui" not in source
    assert "loushang.work" not in source


def test_channel_depends_on_only_explicit_harness_host_and_event_surfaces() -> None:
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in Path("src/loushang/channel").glob("*.py")
        if path.name != "__pycache__"
    }

    harness_imports = {
        name for name, source in sources.items() if "loushang.harness" in source
    }

    assert harness_imports == {"host.py", "json_codec.py", "types.py"}
    assert "loushang.harness.host.product_host" in sources["host.py"]
    assert "loushang.harness.events.projection" in sources["json_codec.py"]
    assert "loushang.harness.events.projection" in sources["types.py"]

    runtime_adapter = Path(
        "src/loushang/channel/adapters/runtime_events.py"
    ).read_text(encoding="utf-8")
    assert "loushang.harness.events" in runtime_adapter
    assert "loushang.harness.session" in runtime_adapter


def test_harness_work_and_channel_import_in_any_package_order() -> None:
    modules = (
        "loushang.harness.host.rpc",
        "loushang.harnesswork",
        "loushang.work",
        "loushang.channel",
    )

    for order in itertools.permutations(modules):
        script = "; ".join(f"import {module}" for module in order)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, (
            f"import order {order} failed:\n{completed.stderr}"
        )
