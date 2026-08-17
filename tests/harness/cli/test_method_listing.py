from __future__ import annotations

import pytest

from loushang.harness.cli import (
    MethodListingError,
    MethodListingRequest,
    run_method_listing,
)


def _method():
    return type(
        "Method",
        (),
        {
            "id": "review",
            "name": "Review",
            "kind": "workflow",
            "element_type": "method",
            "source_path": "methods/review.md",
            "content": "Review the change.",
            "description": "Review changes",
            "applicability": None,
        },
    )()


def test_method_listing_projects_catalog_without_domain_binding() -> None:
    result = run_method_listing(
        MethodListingRequest(list_methods=True, list_format="json"),
        discover_methods=lambda: [_method()],
    )
    assert '"id": "review"' in result.output
    assert "methods/review.md" in result.output


def test_method_listing_uses_injected_plan_compiler() -> None:
    result = run_method_listing(
        MethodListingRequest(show_method_plan="review", show_plan_format="json"),
        discover_methods=lambda: [_method()],
        compile_plan=lambda method: type(
            "Plan",
            (),
            {
                "id": "review.plan",
                "method_id": method.id,
                "mode": "sequential",
                "steps": (),
                "applicability": None,
                "metadata": {},
            },
        )(),
    )
    assert '"plan":' in result.output
    assert "review.plan" in result.output


def test_method_listing_reports_missing_method() -> None:
    with pytest.raises(MethodListingError, match="method not found"):
        run_method_listing(
            MethodListingRequest(show_method="missing"),
            discover_methods=lambda: [_method()],
        )
