from pathlib import Path

from loushang.method import (
    MethodDomainProfile,
    MethodDomainRequest,
    MethodDomainRuntime,
    MethodPolicy,
    resolve_method_policy,
)


def test_method_domain_runtime_supports_non_coding_product(tmp_path: Path) -> None:
    method_dir = tmp_path / "methods" / "task" / "source-review"
    method_dir.mkdir(parents=True)
    (method_dir / "SKILL.md").write_text(
        "---\n"
        "name: source-review\n"
        "description: Review research sources.\n"
        "type: task\n"
        "---\n\n"
        "Check source quality and conflicting evidence.",
        encoding="utf-8",
    )
    runtime = MethodDomainRuntime(
        profile=MethodDomainProfile(domain="research"),
    )

    turn = runtime.prepare_turn(
        MethodDomainRequest(
            user_input="Review these sources",
            cwd=tmp_path,
            method="source-review",
        )
    )

    assert turn.method_id == "method:task:source-review"
    assert turn.prepared_prompt.endswith("User request:\n\nReview these sources")
    assert "Check source quality" in turn.prepared_prompt


def test_method_policy_resolution_composes_cli_and_product_settings() -> None:
    settings = type(
        "Settings",
        (),
        {
            "get_method_settings": lambda _self: type(
                "MethodSettings",
                (),
                {"mode": "explicit", "selected_method": "research"},
            )()
        },
    )()

    assert resolve_method_policy(
        explicit_method=None,
        disabled=False,
        settings_manager=settings,
    ) == MethodPolicy.explicit("research")
    assert resolve_method_policy(
        explicit_method="review",
        disabled=False,
        settings_manager=settings,
    ) == MethodPolicy.explicit("review")
    assert resolve_method_policy(
        explicit_method="review",
        disabled=True,
        settings_manager=settings,
    ) == MethodPolicy.off()
