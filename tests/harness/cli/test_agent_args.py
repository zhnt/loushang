from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from loushang.harness.cli import (
    agent_cli_bootstrap_args,
    agent_image_auto_resize,
    agent_resource_loader_options,
    apply_agent_offline_mode,
    configure_agent_resource_loader,
    resolve_agent_session_dir,
)


@dataclass(frozen=True)
class _CatalogArgs:
    no_session: bool = False
    list_commands: bool = False
    list_diagnostics: bool = False
    list_skills: bool = False
    list_plugins: bool = False
    list_packages: bool = False
    list_models: str | bool = False
    enable_skills: tuple[str, ...] = ()
    disable_skills: tuple[str, ...] = ()
    add_plugin_sources: tuple[str, ...] = ()
    remove_plugin_sources: tuple[str, ...] = ()
    enable_plugins: tuple[str, ...] = ()
    disable_plugins: tuple[str, ...] = ()


class _Loader:
    def set_runtime_options(self, **options: object) -> None:
        self.options = options


def test_agent_bootstrap_uses_ephemeral_session_for_shared_catalogs() -> None:
    args = _CatalogArgs(list_commands=True)

    result = agent_cli_bootstrap_args(args)

    assert result.no_session is True
    assert args.no_session is False


def test_agent_resource_options_preserve_partial_builder_inputs() -> None:
    args = SimpleNamespace(
        extensions=("one.py",),
        no_extensions=True,
        system_prompt="system",
        append_system_prompt=("tail",),
    )
    loader = _Loader()

    options = configure_agent_resource_loader(loader, args)

    assert options == {
        "additional_extension_paths": ["one.py"],
        "additional_skill_paths": [],
        "additional_prompt_template_paths": [],
        "additional_theme_paths": [],
        "no_extensions": True,
        "no_skills": False,
        "no_prompt_templates": False,
        "no_themes": False,
        "no_context_files": False,
        "system_prompt": "system",
        "append_system_prompt": ["tail"],
    }
    assert loader.options == options
    assert agent_resource_loader_options(SimpleNamespace())[
        "additional_extension_paths"
    ] == []


def test_agent_environment_and_settings_projections_are_product_neutral(
    tmp_path,
) -> None:
    environment: dict[str, str] = {}
    args = SimpleNamespace(offline=True, session_dir=None)
    settings = SimpleNamespace(
        session_dir=None,
        images=SimpleNamespace(auto_resize=False),
    )
    manager = SimpleNamespace(get_settings=lambda: settings)

    apply_agent_offline_mode(args, environment=environment)

    assert environment == {"LOUSHANG_OFFLINE": "1"}
    assert (
        resolve_agent_session_dir(
            args,
            project_root=tmp_path,
            settings_manager=manager,
        )
        == tmp_path / ".loushang" / "sessions"
    )
    assert agent_image_auto_resize(manager) is False
