from __future__ import annotations


def test_frontmatter_parser_has_product_neutral_entrypoint() -> None:
    from loushang.resource.frontmatter import parse_frontmatter

    result = parse_frontmatter("---\nname: review\n---\n\nRun review.")

    assert result.frontmatter == {"name": "review"}
    assert result.body == "Run review."


def test_harness_frontmatter_entrypoint_is_canonical() -> None:
    from loushang.harness.resources.frontmatter import (
        parse_frontmatter as harness_parse_frontmatter,
    )
    from loushang.resource.frontmatter import parse_frontmatter

    assert harness_parse_frontmatter is parse_frontmatter


def test_legacy_resource_frontmatter_path_preserves_harness_owner_identity() -> None:
    from loushang.harness.resources.frontmatter import (
        FrontmatterParseError as HarnessFrontmatterParseError,
    )
    from loushang.harness.resources.frontmatter import (
        ParsedFrontmatter as HarnessParsedFrontmatter,
    )
    from loushang.harness.resources.frontmatter import (
        parse_frontmatter as harness_parse_frontmatter,
    )
    from loushang.harness.resources.frontmatter import (
        strip_frontmatter as harness_strip_frontmatter,
    )
    from loushang.resource.frontmatter import (
        FrontmatterParseError,
        ParsedFrontmatter,
        parse_frontmatter,
        strip_frontmatter,
    )

    assert FrontmatterParseError is HarnessFrontmatterParseError
    assert ParsedFrontmatter is HarnessParsedFrontmatter
    assert parse_frontmatter is harness_parse_frontmatter
    assert strip_frontmatter is harness_strip_frontmatter
    assert ParsedFrontmatter.__module__ == "loushang.harness.resources.frontmatter"
    assert FrontmatterParseError.__module__ == "loushang.harness.resources.frontmatter"
