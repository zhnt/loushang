from __future__ import annotations

from loushang.harness.extensions.agent import (
    ExtensionAPI,
    ExtensionLoader,
    ExtensionRunner,
    policy_from_manifest,
)
from loushang.harness.extensions.loader import ExtensionLoader as CoreExtensionLoader
from loushang.harness.extensions.runner import ExtensionRunner as CoreExtensionRunner
from loushang.harness.extensions.types import ExtensionPolicyDecision
from loushang.harness.resources.types import ExtensionDescriptor


def test_agent_extension_profile_composes_existing_core_runtime() -> None:
    assert issubclass(ExtensionLoader, CoreExtensionLoader)
    assert issubclass(ExtensionRunner, CoreExtensionRunner)
    assert policy_from_manifest(None) == ExtensionPolicyDecision(enabled=True)


def test_agent_extension_loader_uses_agent_session_api(tmp_path) -> None:
    extension_path = tmp_path / "research_extension.py"
    extension_path.write_text(
        "\n".join(
            (
                "def register(api):",
                "    api.on('session_start', lambda event, context: None)",
            )
        ),
        encoding="utf-8",
    )

    loaded = ExtensionLoader().load_extension(
        ExtensionDescriptor(
            name="research-extension",
            source_path=extension_path,
            entry_path=extension_path,
        )
    )

    assert loaded is not None
    assert isinstance(loaded.api, ExtensionAPI)
    assert tuple(loaded.hooks) == ("session_start",)


def test_agent_extension_api_declares_side_question_replacement_as_data(
    tmp_path,
) -> None:
    created: list[str] = []
    api = ExtensionAPI(name="research", source_path=tmp_path / "extension.py")
    api.register_side_question_provider(
        "research-answer",
        create=lambda: created.append("created") or object(),
        implementation_version=2,
        priority=7,
    )

    loaded = api.build_loaded_extension()

    assert created == []
    assert len(loaded.runtime_capability_replacements) == 1
    replacement = loaded.runtime_capability_replacements[0]
    assert replacement.slot == "interaction.side_question"
    assert replacement.name == "research-answer"
    assert replacement.implementation_version == 2
    assert replacement.priority == 7
