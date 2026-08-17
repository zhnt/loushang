from __future__ import annotations

from types import SimpleNamespace

from loushang.foundation.observability.identity import collect_runtime_identity


def test_collect_runtime_identity_is_not_coding_specific(tmp_path) -> None:
    module = SimpleNamespace(__file__=tmp_path / "example_product" / "__init__.py")

    identity = collect_runtime_identity(
        package_name="example-product",
        package_module=module,
        executable_name="example-product",
        related_modules={
            "integration": SimpleNamespace(__file__=tmp_path / "plugin.py")
        },
        cwd=tmp_path,
        argv0="example-product",
        env={"PATH": ""},
    )

    assert identity["package_name"] == "example-product"
    assert identity["related_module_files"] == {
        "integration": str(tmp_path / "plugin.py")
    }
    assert identity["path_candidates"] == []
