from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from loushang.coding.lsp import (
    LspCatalog,
    LspSelector,
    LspServerDefinition,
    default_lsp_environment,
    discover_lsp_catalog,
    product_default_lsp_definitions,
)


def _write_config(path: Path, servers: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"servers": servers}), encoding="utf-8")


def test_catalog_merges_config_by_product_precedence_and_admits_available_server(
    tmp_path: Path,
) -> None:
    user_config = tmp_path / "user-lsp.json"
    project_config = tmp_path / "project-lsp.json"
    _write_config(
        user_config,
        [
            {
                "id": "python-custom",
                "command": ["custom-lsp", "--stdio"],
                "language_extensions": {"python": [".py"]},
                "environment": {"CUSTOM_LSP_HOME": "/trusted/home"},
            },
            {"id": "disabled-default", "enabled": False},
        ],
    )
    _write_config(
        project_config,
        [
            {
                "id": "python-custom",
                "command": ["custom-lsp", "--stdio"],
                "language_extensions": {"python": ["py", "pyi"]},
                "priority": 20,
                "settings": {"analysis": {"strict": True}},
            },
            {"id": "broken", "command": "not-an-array"},
        ],
    )
    probe_environments: list[dict[str, str]] = []

    def resolve(command: str, environment: Mapping[str, str]) -> str | None:
        resolved_environment = dict(environment)
        probe_environments.append(resolved_environment)
        return (
            f"{resolved_environment['PATH']}/{command}"
            if command == "custom-lsp"
            else None
        )

    snapshot = discover_lsp_catalog(
        workspace_root=tmp_path,
        baseline_environment={"PATH": "/tools"},
        global_config_path=user_config,
        project_config_path=project_config,
        executable_resolver=resolve,
        include_product_defaults=False,
    )

    assert snapshot.admitted_count == 1
    assert snapshot.definitions[0].command == ("/tools/custom-lsp", "--stdio")
    assert snapshot.definitions[0].extensions == (".py", ".pyi")
    assert snapshot.definitions[0].environment == {"CUSTOM_LSP_HOME": "/trusted/home"}
    assert probe_environments == [
        {"PATH": "/tools", "CUSTOM_LSP_HOME": "/trusted/home"}
    ]
    assert [
        (record.definition_id, record.source, record.state)
        for record in snapshot.records
    ] == [
        ("broken", "project-config", "rejected"),
        ("disabled-default", "user-config", "disabled"),
        ("python-custom", "project-config", "admitted"),
    ]
    assert snapshot.records[-1].executable == "/tools/custom-lsp"
    assert len(snapshot.generation) == 12

    _write_config(
        project_config,
        [
            {
                "id": "python-custom",
                "command": ["custom-lsp", "--stdio"],
                "language_extensions": {"python": [".py"]},
                "settings": {"analysis": {"strict": False}},
            }
        ],
    )
    changed = discover_lsp_catalog(
        workspace_root=tmp_path,
        baseline_environment={"PATH": "/tools"},
        global_config_path=user_config,
        project_config_path=project_config,
        executable_resolver=lambda command, _environment: f"/tools/{command}",
        include_product_defaults=False,
    )
    assert changed.generation != snapshot.generation


def test_project_config_cannot_alter_arguments_of_trusted_command(
    tmp_path: Path,
) -> None:
    user_config = tmp_path / "user-lsp.json"
    project_config = tmp_path / "project-lsp.json"
    _write_config(
        user_config,
        [
            {
                "id": "python-custom",
                "command": ["python", "-m", "trusted_lsp"],
                "language_extensions": {"python": [".py"]},
            }
        ],
    )
    _write_config(
        project_config,
        [
            {
                "id": "python-custom",
                "command": ["python", "-c", "run_untrusted_code()"],
                "language_extensions": {"python": [".py"]},
            }
        ],
    )

    snapshot = discover_lsp_catalog(
        workspace_root=tmp_path,
        baseline_environment={"PATH": "/tools"},
        global_config_path=user_config,
        project_config_path=project_config,
        executable_resolver=lambda command, _environment: f"/tools/{command}",
        include_product_defaults=False,
    )

    assert snapshot.admitted_count == 0
    assert snapshot.records[0].state == "rejected"
    assert "complete command" in snapshot.records[0].detail


def test_explicit_sdk_definition_is_already_admitted_without_binary_probe(
    tmp_path: Path,
) -> None:
    probes: list[str] = []
    definition = LspServerDefinition(
        id="sdk-fake",
        command=("not-installed-in-this-test", "--stdio"),
        language_extensions={"python": (".py",)},
    )

    snapshot = discover_lsp_catalog(
        workspace_root=tmp_path,
        baseline_environment={},
        explicit_definitions=(definition,),
        global_config_path=tmp_path / "missing-user.json",
        project_config_path=tmp_path / "missing-project.json",
        executable_resolver=lambda command, _environment: probes.append(command),
        include_product_defaults=False,
    )

    assert snapshot.definitions == (definition,)
    assert snapshot.records[0].state == "admitted"
    assert probes == []


def test_project_config_cannot_introduce_untrusted_executable(tmp_path: Path) -> None:
    project_config = tmp_path / "project-lsp.json"
    _write_config(
        project_config,
        [
            {
                "id": "repository-command",
                "command": ["run-anything", "--stdio"],
                "language_extensions": {"python": [".py"]},
            }
        ],
    )

    snapshot = discover_lsp_catalog(
        workspace_root=tmp_path,
        baseline_environment={"PATH": "/tools"},
        global_config_path=False,
        project_config_path=project_config,
        executable_resolver=lambda command, _environment: f"/tools/{command}",
        include_product_defaults=False,
    )

    assert snapshot.admitted_count == 0
    assert snapshot.records[0].state == "rejected"
    assert "user-level" in snapshot.records[0].detail


def test_config_rejects_timeout_too_large_to_convert(tmp_path: Path) -> None:
    user_config = tmp_path / "user-lsp.json"
    _write_config(
        user_config,
        [
            {
                "id": "overflowing-timeout",
                "command": ["custom-lsp"],
                "language_extensions": {"python": [".py"]},
                "startup_timeout_seconds": 10**400,
            }
        ],
    )

    snapshot = discover_lsp_catalog(
        workspace_root=tmp_path,
        baseline_environment={"PATH": "/tools"},
        global_config_path=user_config,
        project_config_path=False,
        include_product_defaults=False,
    )

    assert snapshot.admitted_count == 0
    assert snapshot.records[0].definition_id == "overflowing-timeout"
    assert snapshot.records[0].state == "rejected"


def test_product_defaults_report_unavailable_without_installing_or_starting(
    tmp_path: Path,
) -> None:
    probes: list[str] = []

    snapshot = discover_lsp_catalog(
        workspace_root=tmp_path,
        baseline_environment={"PATH": "/empty"},
        global_config_path=tmp_path / "missing-user.json",
        project_config_path=tmp_path / "missing-project.json",
        executable_resolver=lambda command, _environment: probes.append(command),
    )

    assert snapshot.admitted_count == 0
    assert probes == [
        "clangd",
        "gopls",
        "pyright-langserver",
        "rust-analyzer",
        "typescript-language-server",
    ]
    assert {record.state for record in snapshot.records} == {"unavailable"}


@pytest.mark.parametrize(
    (
        "definition_id",
        "expected_command",
        "expected_languages",
        "expected_root_markers",
    ),
    [
        pytest.param(
            "pyright",
            ("pyright-langserver", "--stdio"),
            {"python": (".py", ".pyi")},
            ("pyrightconfig.json", "pyproject.toml", ".git"),
            id="pyright",
        ),
        pytest.param(
            "typescript-language-server",
            ("typescript-language-server", "--stdio"),
            {
                "javascript": (".js", ".mjs", ".cjs"),
                "javascriptreact": (".jsx",),
                "typescript": (".ts", ".mts", ".cts"),
                "typescriptreact": (".tsx",),
            },
            ("tsconfig.json", "jsconfig.json", "package.json", ".git"),
            id="typescript-language-server",
        ),
        pytest.param(
            "rust-analyzer",
            ("rust-analyzer",),
            {"rust": (".rs",)},
            ("rust-project.json", "Cargo.toml", ".git"),
            id="rust-analyzer",
        ),
        pytest.param(
            "gopls",
            ("gopls", "serve"),
            {"go": (".go",)},
            ("go.work", "go.mod", ".git"),
            id="gopls",
        ),
        pytest.param(
            "clangd",
            ("clangd",),
            {
                "c": (".c", ".h"),
                "cpp": (".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"),
            },
            (".clangd", "compile_commands.json", "compile_flags.txt", ".git"),
            id="clangd",
        ),
    ],
)
def test_product_presets_map_languages_and_select_every_nearest_root_marker(
    tmp_path: Path,
    definition_id: str,
    expected_command: tuple[str, ...],
    expected_languages: dict[str, tuple[str, ...]],
    expected_root_markers: tuple[str, ...],
) -> None:
    definition = next(
        item for item in product_default_lsp_definitions() if item.id == definition_id
    )

    assert definition.command == expected_command
    assert definition.language_extensions == expected_languages
    assert definition.root_markers == expected_root_markers
    assert definition.source == "product-default"
    for language_id, extensions in expected_languages.items():
        for extension in extensions:
            assert definition.language_for_filename(f"sample{extension}") == language_id

    sample_extension = next(iter(expected_languages.values()))[0]
    for index, marker in enumerate(expected_root_markers):
        workspace_root = tmp_path / f"marker-{index}"
        package_root = workspace_root / "packages" / "nested"
        source_root = package_root / "src"
        source_root.mkdir(parents=True)
        fallback_marker = expected_root_markers[
            (index + 1) % len(expected_root_markers)
        ]
        (workspace_root / fallback_marker).touch()
        (package_root / marker).touch()
        source = source_root / f"main{sample_extension}"
        source.touch()
        selector = LspSelector(
            workspace_root=workspace_root,
            catalog=LspCatalog((definition,)),
        )

        selection = selector.select(source)

        assert selection.definition_id == definition_id
        assert selection.workspace_root == package_root
        assert selection.reason_code == "nearest_root"


def test_typescript_product_preset_is_admitted_only_when_binary_exists(
    tmp_path: Path,
) -> None:
    probes: list[str] = []

    snapshot = discover_lsp_catalog(
        workspace_root=tmp_path,
        baseline_environment={"PATH": "/tools"},
        global_config_path=False,
        project_config_path=False,
        executable_resolver=lambda command, _environment: (
            probes.append(command)
            or (
                "/tools/typescript-language-server"
                if command == "typescript-language-server"
                else None
            )
        ),
    )

    assert [item.id for item in snapshot.definitions] == ["typescript-language-server"]
    definition = snapshot.definitions[0]
    assert definition.command == (
        "/tools/typescript-language-server",
        "--stdio",
    )
    record = next(
        item
        for item in snapshot.records
        if item.definition_id == "typescript-language-server"
    )
    assert record.state == "admitted"
    assert record.source == "product-default"
    assert record.executable == "/tools/typescript-language-server"
    assert probes == [
        "clangd",
        "gopls",
        "pyright-langserver",
        "rust-analyzer",
        "typescript-language-server",
    ]


def test_default_environment_excludes_unrelated_secrets() -> None:
    environment = default_lsp_environment(
        {
            "PATH": "/bin",
            "HOME": "/home/example",
            "LANG": "C.UTF-8",
            "API_TOKEN": "secret",
            "AWS_SECRET_ACCESS_KEY": "secret",
        }
    )

    assert environment == {
        "PATH": "/bin",
        "HOME": "/home/example",
        "LANG": "C.UTF-8",
    }
