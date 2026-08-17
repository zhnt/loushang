from __future__ import annotations

import pytest


def test_parse_frontmatter_normalizes_crlf_and_block_scalars() -> None:
    from loushang.harness.resources.frontmatter import parse_frontmatter

    result = parse_frontmatter(
        "---\r\n"
        "name: review\r\n"
        "description: |\r\n"
        "  Review pull requests\r\n"
        "  and summarize risks.\r\n"
        "disable-model-invocation: true\r\n"
        "---\r\n\r\n"
        "Run the review.\r\n"
    )

    assert result.frontmatter == {
        "name": "review",
        "description": "Review pull requests\nand summarize risks.\n",
        "disable-model-invocation": True,
    }
    assert result.body == "Run the review."


def test_parse_frontmatter_supports_simple_lists_and_maps() -> None:
    from loushang.harness.resources.frontmatter import parse_frontmatter

    result = parse_frontmatter(
        "---\n"
        "domains:\n"
        "  - coding\n"
        "  - research\n"
        "tags:\n"
        "  family: review-first\n"
        "  phase:\n"
        "    - verify\n"
        "---\n\n"
        "Run the review.\n"
    )

    assert result.frontmatter == {
        "domains": ["coding", "research"],
        "tags": {
            "family": "review-first",
            "phase": ["verify"],
        },
    }


def test_parse_frontmatter_supports_nested_maps() -> None:
    from loushang.harness.resources.frontmatter import parse_frontmatter

    result = parse_frontmatter(
        "---\n"
        "step_constraints:\n"
        "  inspect:\n"
        "    level: reasoned\n"
        "    requires_reason: true\n"
        "  verify:\n"
        "    level: evidence\n"
        "    required_evidence:\n"
        "      - tests\n"
        "      - logs\n"
        "---\n\n"
        "Run the review.\n"
    )

    assert result.frontmatter["step_constraints"] == {
        "inspect": {
            "level": "reasoned",
            "requires_reason": True,
        },
        "verify": {
            "level": "evidence",
            "required_evidence": ["tests", "logs"],
        },
    }


def test_parse_frontmatter_keeps_original_body_without_complete_frontmatter() -> None:
    from loushang.harness.resources.frontmatter import (
        parse_frontmatter,
        strip_frontmatter,
    )

    unterminated = "---\nname: review\nRun the review."

    assert parse_frontmatter("Body only").frontmatter == {}
    assert parse_frontmatter("Body only").body == "Body only"
    assert parse_frontmatter(unterminated).frontmatter == {}
    assert parse_frontmatter(unterminated).body == unterminated
    assert strip_frontmatter(unterminated) == unterminated


def test_parse_frontmatter_reports_invalid_yaml_location() -> None:
    from loushang.harness.resources.frontmatter import (
        FrontmatterParseError,
        parse_frontmatter,
    )

    with pytest.raises(FrontmatterParseError) as error:
        parse_frontmatter("---\ndescription: [broken\n---\nBody")

    assert "line 1" in str(error.value)
    assert "description" in str(error.value)
