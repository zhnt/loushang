from io import StringIO

from loushang.harness.cli import run_package_listing_operation


def test_package_listing_uses_product_fallback_records() -> None:
    stdout = StringIO()
    stderr = StringIO()

    result = run_package_listing_operation(
        requested=True,
        output_format="text",
        list_records=lambda: [],
        fallback_records=lambda: [
            {
                "name": "research-defaults",
                "kind": "builtin",
                "scope": "project",
                "version": "1",
                "source": "research",
                "path": "/workspace/resources",
                "enabled": True,
                "prompts": 1,
                "skills": 1,
                "extensions": 0,
                "themes": 0,
                "diagnostics": 0,
            }
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "research-defaults" in stdout.getvalue()
    assert stderr.getvalue() == ""
