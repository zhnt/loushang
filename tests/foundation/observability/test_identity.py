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
    assert identity["launch_mode"] in {"console-script", "virtualenv-console-script"}


def test_collect_runtime_identity_distinguishes_workspace_and_source_git(
    monkeypatch, tmp_path
) -> None:
    import loushang.foundation.observability.identity as identity_module

    workspace = tmp_path / "workspace"
    source = tmp_path / "source" / "src" / "example_product"
    workspace.mkdir()
    source.mkdir(parents=True)
    module = SimpleNamespace(__file__=source / "__init__.py")

    def fake_git_identity(path):
        if path == workspace:
            return {
                "project_root": "/workspace",
                "git_branch": "feature",
                "git_commit": "workspace-commit",
                "git_dirty": True,
            }
        assert path == source
        return {
            "project_root": "/source",
            "git_branch": "main",
            "git_commit": "source-commit",
            "git_dirty": False,
        }

    monkeypatch.setattr(identity_module, "git_identity", fake_git_identity)

    identity = collect_runtime_identity(
        package_name="example-product",
        package_module=module,
        executable_name="example-product",
        cwd=workspace,
        argv0="example-product",
        env={"PATH": ""},
    )

    assert identity["project_root"] == "/workspace"
    assert identity["git_commit"] == "workspace-commit"
    assert identity["git_dirty"] is True
    assert identity["source_project_root"] == "/source"
    assert identity["source_git_branch"] == "main"
    assert identity["source_git_commit"] == "source-commit"
    assert identity["source_git_dirty"] is False


def test_collect_runtime_identity_marks_direct_entrypoint_active_outside_path(
    tmp_path,
) -> None:
    active = tmp_path / "active" / "example-product"
    shadowed = tmp_path / "path" / "example-product"
    active.parent.mkdir()
    shadowed.parent.mkdir()
    for candidate in (active, shadowed):
        candidate.write_text("#!/bin/sh\n", encoding="utf-8")
        candidate.chmod(0o755)

    identity = collect_runtime_identity(
        package_name="example-product",
        package_module=SimpleNamespace(
            __file__=tmp_path / "src" / "example_product" / "__init__.py"
        ),
        executable_name="example-product",
        cwd=tmp_path,
        argv0=str(active),
        env={"PATH": str(shadowed.parent)},
    )

    assert identity["entrypoint"] == str(active)
    assert identity["path_candidates"] == [
        {"path": str(active), "status": "active", "active": True},
        {"path": str(shadowed), "status": "shadowed", "active": False},
    ]


def test_collect_runtime_identity_keeps_path_candidates_inactive_for_python_module(
    tmp_path,
) -> None:
    module_entrypoint = tmp_path / "src" / "example_product" / "__main__.py"
    module_entrypoint.parent.mkdir(parents=True)
    module_entrypoint.write_text("", encoding="utf-8")
    path_candidate = tmp_path / "bin" / "example-product"
    path_candidate.parent.mkdir()
    path_candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    path_candidate.chmod(0o755)

    identity = collect_runtime_identity(
        package_name="example-product",
        package_module=SimpleNamespace(
            __file__=module_entrypoint.with_name("__init__.py")
        ),
        executable_name="example-product",
        cwd=tmp_path,
        argv0=str(module_entrypoint),
        env={"PATH": str(path_candidate.parent)},
    )

    assert identity["launch_mode"] == "python-module"
    assert identity["path_candidates"] == [
        {"path": str(path_candidate), "status": "shadowed", "active": False}
    ]


def test_collect_runtime_identity_discovers_pathext_candidates(tmp_path) -> None:
    active = tmp_path / "active" / "example-product.EXE"
    shadowed = tmp_path / "path" / "example-product.CMD"
    active.parent.mkdir()
    shadowed.parent.mkdir()
    for candidate in (active, shadowed):
        candidate.write_text("launcher", encoding="utf-8")
        candidate.chmod(0o755)

    identity = collect_runtime_identity(
        package_name="example-product",
        package_module=SimpleNamespace(
            __file__=tmp_path / "src" / "example_product" / "__init__.py"
        ),
        executable_name="example-product",
        cwd=tmp_path,
        argv0=str(active),
        env={"PATH": str(shadowed.parent), "PATHEXT": ".EXE;.CMD"},
    )

    assert identity["path_candidates"] == [
        {"path": str(active), "status": "active", "active": True},
        {"path": str(shadowed), "status": "shadowed", "active": False},
    ]
