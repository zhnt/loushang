from __future__ import annotations

from pathlib import Path

ARCHITECTURE_PATH = Path(
    "docs/internals/architecture/harness/unified-plugin-architecture.md"
)
README_PATH = Path("docs/internals/architecture/harness/README.md")


def test_unified_plugin_architecture_is_indexed_and_freezes_single_authorities() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "unified-plugin-architecture.md" in readme
    assert "one manifest parser" in architecture
    assert "only Capability Graph publisher" in architecture
    assert "Plugin identity is not a Capability Graph node" in architecture
    assert "installed != enabled != planned != mounted" in architecture


def test_unified_plugin_architecture_defines_the_four_phase_pipeline() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    for phase in (
        "Resolve once",
        "Declare once",
        "Bind once",
        "Project once",
    ):
        assert phase in architecture


def test_unified_plugin_architecture_keeps_product_kernel_outside_plugins() -> None:
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    assert "Coding Product Kernel" in architecture
    assert "coding.base" in architecture
    assert "must remain usable when every optional Plugin is disabled" in architecture
