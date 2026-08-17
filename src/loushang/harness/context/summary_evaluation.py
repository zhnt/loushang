"""Profile-driven evaluation for structured summaries and resource evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from loushang.harness.context.summary import (
    SummaryProfile,
    SummaryValidationReport,
    validate_summary,
)


@dataclass(frozen=True)
class SummaryResourceOperation:
    """Resources reported for one product-neutral summary operation."""

    operation: str
    resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        operation = self.operation.strip()
        if not operation:
            raise ValueError("summary resource operation must not be empty")
        resources: list[str] = []
        seen: set[str] = set()
        for resource in self.resources:
            if not isinstance(resource, str) or not resource.strip():
                raise TypeError(
                    "summary resource operation resources must be non-empty strings"
                )
            resource = resource.strip()
            if resource not in seen:
                resources.append(resource)
                seen.add(resource)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "resources", tuple(resources))


@dataclass(frozen=True)
class SummaryResourceOperations:
    """Ordered resource evidence grouped by product-neutral operation name."""

    operations: tuple[SummaryResourceOperation, ...] = ()

    def __post_init__(self) -> None:
        operation_names = tuple(item.operation for item in self.operations)
        if len(operation_names) != len(set(operation_names)):
            raise ValueError("summary resource operations must not repeat an operation")
        object.__setattr__(self, "operations", tuple(self.operations))

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Sequence[str]],
    ) -> SummaryResourceOperations:
        if not isinstance(value, Mapping):
            raise TypeError("summary resource operations must be a mapping")
        operations: list[SummaryResourceOperation] = []
        for operation, resources in value.items():
            if not isinstance(operation, str):
                raise TypeError("summary resource operation names must be strings")
            if not isinstance(resources, Sequence) or isinstance(resources, str):
                raise TypeError(
                    "summary resource operation resources must be a sequence of strings"
                )
            operations.append(
                SummaryResourceOperation(
                    operation=operation, resources=tuple(resources)
                )
            )
        return cls(operations=tuple(operations))

    def resources_for(self, operation: str) -> tuple[str, ...]:
        for item in self.operations:
            if item.operation == operation:
                return item.resources
        return ()

    def missing_from(
        self,
        actual: SummaryResourceOperations,
    ) -> SummaryResourceOperations:
        missing: list[SummaryResourceOperation] = []
        for expected in self.operations:
            actual_resources = set(actual.resources_for(expected.operation))
            missing_resources = tuple(
                resource
                for resource in expected.resources
                if resource not in actual_resources
            )
            if missing_resources:
                missing.append(
                    SummaryResourceOperation(
                        operation=expected.operation,
                        resources=missing_resources,
                    )
                )
        return SummaryResourceOperations(operations=tuple(missing))

    @property
    def empty(self) -> bool:
        return not self.operations

    def to_dict(self) -> dict[str, list[str]]:
        return {item.operation: list(item.resources) for item in self.operations}


@dataclass(frozen=True)
class SummaryEvaluationCase:
    """One profile-driven summary evaluation case."""

    name: str
    summary: str | None
    profile_id: str | None = None
    required_phrases: tuple[str, ...] = ()
    expected_resource_operations: SummaryResourceOperations = field(
        default_factory=SummaryResourceOperations
    )

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("summary evaluation case requires a non-empty name")
        if self.summary is not None and not isinstance(self.summary, str):
            raise TypeError("summary evaluation case summary must be a string or null")
        if self.profile_id is not None and not self.profile_id.strip():
            raise ValueError("summary evaluation case profile_id must not be empty")
        if any(not isinstance(phrase, str) for phrase in self.required_phrases):
            raise TypeError("required_phrases must contain strings")
        if not isinstance(self.expected_resource_operations, SummaryResourceOperations):
            raise TypeError(
                "expected_resource_operations must be SummaryResourceOperations"
            )


@dataclass(frozen=True)
class SummaryEvaluationResult:
    """Evaluation facts for one summary and the selected profile."""

    case_name: str
    profile_id: str
    validation: SummaryValidationReport
    resource_operations: SummaryResourceOperations
    missing_phrases: tuple[str, ...] = ()
    missing_resource_operations: SummaryResourceOperations = field(
        default_factory=SummaryResourceOperations
    )

    @property
    def ok(self) -> bool:
        return (
            self.validation.ok
            and not self.missing_phrases
            and self.missing_resource_operations.empty
        )


@dataclass(frozen=True)
class SummaryEvaluationSuiteResult:
    results: tuple[SummaryEvaluationResult, ...]

    @property
    def total_count(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.results if result.ok)

    @property
    def failed_case_names(self) -> tuple[str, ...]:
        return tuple(result.case_name for result in self.results if not result.ok)

    @property
    def ok(self) -> bool:
        return not self.failed_case_names

    def to_dict(self) -> dict[str, object]:
        return {
            "total_count": self.total_count,
            "passed_count": self.passed_count,
            "failed_case_names": list(self.failed_case_names),
        }


def extract_summary_resource_operations(
    summary: str | None,
    profile: SummaryProfile,
) -> SummaryResourceOperations:
    """Extract profile-declared resource evidence blocks from a summary."""

    if not summary or not profile.resource_operation_tags:
        return SummaryResourceOperations()

    tag_to_operation = {
        resource_tag.tag: resource_tag.operation
        for resource_tag in profile.resource_operation_tags
    }
    alternatives = "|".join(re.escape(tag) for tag in tag_to_operation)
    block_re = re.compile(
        rf"<(?P<tag>{alternatives})>\s*(?P<body>.*?)\s*</(?P=tag)>",
        re.DOTALL,
    )
    resources: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for match in block_re.finditer(summary):
        operation = tag_to_operation[match.group("tag")]
        entries = resources.setdefault(operation, [])
        operation_seen = seen.setdefault(operation, set())
        for line in match.group("body").splitlines():
            resource = line.strip()
            if resource and resource not in operation_seen:
                entries.append(resource)
                operation_seen.add(resource)

    operation_order = dict.fromkeys(
        resource_tag.operation for resource_tag in profile.resource_operation_tags
    )
    return SummaryResourceOperations(
        operations=tuple(
            SummaryResourceOperation(
                operation=operation, resources=tuple(resources[operation])
            )
            for operation in operation_order
            if resources.get(operation)
        )
    )


def evaluate_summary_case(
    case: SummaryEvaluationCase,
    *,
    profile: SummaryProfile,
) -> SummaryEvaluationResult:
    """Evaluate one summary against a caller-selected profile."""

    if case.profile_id is not None and case.profile_id != profile.profile_id:
        raise ValueError(
            f"summary evaluation case {case.name!r} requires profile "
            f"{case.profile_id!r}, not {profile.profile_id!r}"
        )
    summary = case.summary or ""
    resource_operations = extract_summary_resource_operations(summary, profile)
    return SummaryEvaluationResult(
        case_name=case.name,
        profile_id=profile.profile_id,
        validation=validate_summary(summary, profile),
        resource_operations=resource_operations,
        missing_phrases=_missing_phrases(summary, case.required_phrases),
        missing_resource_operations=case.expected_resource_operations.missing_from(
            resource_operations
        ),
    )


def evaluate_summary_cases(
    cases: Sequence[SummaryEvaluationCase],
    *,
    profile: SummaryProfile,
) -> SummaryEvaluationSuiteResult:
    return SummaryEvaluationSuiteResult(
        results=tuple(evaluate_summary_case(case, profile=profile) for case in cases)
    )


def load_summary_evaluation_cases(
    path: str | Path,
) -> tuple[SummaryEvaluationCase, ...]:
    """Load product-selected summary cases from a JSON fixture."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    fixture_profile_id: str | None = None
    if isinstance(payload, Mapping):
        raw_cases = payload.get("cases")
        fixture_profile_id = _optional_profile_id(payload.get("profile_id"))
    else:
        raw_cases = payload
    if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, str):
        raise TypeError("summary evaluation fixture must contain a sequence of cases")
    return tuple(
        _case_from_mapping(raw_case, default_profile_id=fixture_profile_id)
        for raw_case in raw_cases
    )


def evaluate_summary_fixture(
    path: str | Path,
    *,
    profiles: Mapping[str, SummaryProfile],
) -> SummaryEvaluationSuiteResult:
    """Evaluate a fixture, resolving a profile independently for every case."""

    cases = load_summary_evaluation_cases(path)
    if not cases:
        raise ValueError("summary evaluation fixture must contain at least one case")
    results: list[SummaryEvaluationResult] = []
    for case in cases:
        if case.profile_id is None:
            raise ValueError(
                f"summary evaluation case {case.name!r} requires a profile_id"
            )
        try:
            profile = profiles[case.profile_id]
        except KeyError as exc:
            raise ValueError(
                f"summary evaluation case {case.name!r} references unknown profile "
                f"{case.profile_id!r}"
            ) from exc
        results.append(evaluate_summary_case(case, profile=profile))
    return SummaryEvaluationSuiteResult(results=tuple(results))


def _case_from_mapping(
    value: object,
    *,
    default_profile_id: str | None,
) -> SummaryEvaluationCase:
    if not isinstance(value, Mapping):
        raise TypeError("summary evaluation cases must be JSON objects")
    name = value.get("name")
    if not isinstance(name, str) or not name:
        raise TypeError("summary evaluation case requires a non-empty name")
    summary = value.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise TypeError("summary evaluation case summary must be a string or null")
    profile_id = _optional_profile_id(value.get("profile_id", default_profile_id))
    return SummaryEvaluationCase(
        name=name,
        summary=summary,
        profile_id=profile_id,
        required_phrases=_string_tuple(
            value.get("required_phrases", ()), "required_phrases"
        ),
        expected_resource_operations=_resource_operations_from_mapping(
            value.get("expected_resource_operations", {})
        ),
    )


def _resource_operations_from_mapping(value: object) -> SummaryResourceOperations:
    if not isinstance(value, Mapping):
        raise TypeError("expected_resource_operations must be a mapping")
    parsed: dict[str, tuple[str, ...]] = {}
    for operation, resources in value.items():
        if not isinstance(operation, str) or not operation.strip():
            raise TypeError(
                "expected_resource_operations keys must be non-empty strings"
            )
        parsed[operation] = _string_tuple(
            resources, f"expected_resource_operations[{operation!r}]"
        )
    return SummaryResourceOperations.from_mapping(parsed)


def _missing_phrases(
    summary: str,
    required_phrases: tuple[str, ...],
) -> tuple[str, ...]:
    lower = summary.lower()
    return tuple(phrase for phrase in required_phrases if phrase.lower() not in lower)


def _optional_profile_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TypeError("summary evaluation profile_id must be a non-empty string")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise TypeError(f"{field_name} must be a sequence of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{field_name} must contain strings")
        result.append(item)
    return tuple(result)


__all__ = [
    "SummaryEvaluationCase",
    "SummaryEvaluationResult",
    "SummaryEvaluationSuiteResult",
    "SummaryResourceOperation",
    "SummaryResourceOperations",
    "evaluate_summary_case",
    "evaluate_summary_cases",
    "evaluate_summary_fixture",
    "extract_summary_resource_operations",
    "load_summary_evaluation_cases",
]
