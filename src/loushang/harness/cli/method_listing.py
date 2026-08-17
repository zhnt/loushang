"""Shared Method catalog listing and plan projection for product CLIs."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


class MethodListingError(RuntimeError):
    """Raised when Method discovery or projection fails."""


@dataclass(frozen=True, slots=True)
class MethodListingRequest:
    list_methods: bool = False
    list_format: str = "text"
    show_method: str | None = None
    show_format: str = "text"
    show_method_plan: str | None = None
    show_plan_format: str = "text"

    @property
    def has_operation(self) -> bool:
        return bool(self.list_methods or self.show_method or self.show_method_plan)


@dataclass(frozen=True, slots=True)
class MethodListingResult:
    output: str


def run_method_listing(
    request: MethodListingRequest,
    *,
    discover_methods: Callable[[], Sequence[object]],
    compile_plan: Callable[[object], object] | None = None,
) -> MethodListingResult:
    """Run a Method catalog operation with product-supplied discovery hooks."""

    if not request.has_operation:
        return MethodListingResult("")
    try:
        methods = list(discover_methods())
    except Exception as error:
        raise MethodListingError(str(error)) from error

    if request.list_methods:
        normalized = [_normalize_method_entry(method) for method in methods]
        if request.list_format == "json":
            return MethodListingResult(json.dumps(normalized, ensure_ascii=False) + "\n")
        return MethodListingResult(
            "".join(
                f"{method['id']}\t{method['name']}\t{method['kind']}\t"
                f"{method['element_type']}\t{method['path']}\n"
                for method in normalized
            )
        )

    if request.show_method_plan is not None:
        method = _find_method(methods, request.show_method_plan)
        if method is None:
            raise MethodListingError(f"method not found: {request.show_method_plan}")
        if compile_plan is None:
            raise MethodListingError("method plan compilation is not available.")
        try:
            plan = compile_plan(method)
        except Exception as error:
            raise MethodListingError(str(error)) from error
        payload = _normalize_method_plan(method, plan)
        if request.show_plan_format == "json":
            return MethodListingResult(json.dumps(payload, ensure_ascii=False) + "\n")
        return MethodListingResult(_format_method_plan_detail(payload))

    method = _find_method(methods, request.show_method or "")
    if method is None:
        raise MethodListingError(f"method not found: {request.show_method}")
    payload = _normalize_method_entry(method)
    payload["description"] = _safe_getattr(method, "description", "") or ""
    payload["content"] = _safe_getattr(method, "content", "") or ""
    if request.show_format == "json":
        return MethodListingResult(json.dumps(payload, ensure_ascii=False) + "\n")
    return MethodListingResult(_format_method_detail(payload))


def _find_method(methods: Sequence[object], id_or_name: str) -> object | None:
    for method in methods:
        if (
            _safe_getattr(method, "id", None) == id_or_name
            or _safe_getattr(method, "name", None) == id_or_name
        ):
            return method
    return None


def _normalize_method_entry(method: object) -> dict[str, object]:
    return {
        "id": _safe_getattr(method, "id", "") or "",
        "name": _safe_getattr(method, "name", "") or "",
        "kind": _safe_getattr(method, "kind", "") or "",
        "element_type": _safe_getattr(method, "element_type", None),
        "domain": _safe_getattr(method, "domain", None),
        "meta_role": _safe_getattr(method, "meta_role", None),
        "phase": _safe_getattr(method, "phase", None),
        "path": _safe_getattr(method, "source_path", "") or "",
        "applicability": _normalize_method_applicability(
            _safe_getattr(method, "applicability", None)
        ),
    }


def _normalize_method_applicability(applicability: object) -> dict[str, object]:
    return {
        "domains": _string_list(_safe_getattr(applicability, "domains", ())),
        "task_types": _string_list(_safe_getattr(applicability, "task_types", ())),
        "contexts": _string_list(_safe_getattr(applicability, "contexts", ())),
        "artifact_types": _string_list(
            _safe_getattr(applicability, "artifact_types", ())
        ),
        "modalities": _string_list(_safe_getattr(applicability, "modalities", ())),
        "toolchains": _string_list(_safe_getattr(applicability, "toolchains", ())),
        "lifecycle": _string_list(_safe_getattr(applicability, "lifecycle", ())),
        "capabilities": _string_list(
            _safe_getattr(applicability, "capabilities", ())
        ),
        "complexity": _optional_string(
            _safe_getattr(applicability, "complexity", None)
        ),
        "risk": _optional_string(_safe_getattr(applicability, "risk", None)),
        "tags": _normalize_method_tags(_safe_getattr(applicability, "tags", {})),
    }


def _normalize_method_plan(method: object, plan: object) -> dict[str, object]:
    raw_steps = _safe_getattr(plan, "steps", ())
    steps = (
        raw_steps
        if isinstance(raw_steps, Sequence) and not isinstance(raw_steps, str)
        else ()
    )
    return {
        "method": _normalize_method_entry(method),
        "plan": {
            "id": _safe_getattr(plan, "id", "") or "",
            "method_id": _safe_getattr(plan, "method_id", "") or "",
            "mode": _safe_getattr(plan, "mode", "") or "",
            "phase": _safe_getattr(plan, "phase", None),
            "activity": _safe_getattr(plan, "activity", None),
            "task": _safe_getattr(plan, "task", None),
            "metadata": _json_safe(_safe_getattr(plan, "metadata", {})),
            "applicability": _normalize_method_applicability(
                _safe_getattr(plan, "applicability", None)
            ),
        },
        "steps": [
            _normalize_method_plan_step(step)
            for step in steps
        ],
    }


def _normalize_method_plan_step(step: object) -> dict[str, object]:
    return {
        "id": _safe_getattr(step, "id", "") or "",
        "title": _safe_getattr(step, "title", "") or "",
        "executor": _safe_getattr(step, "executor", "") or "",
        "role_variant": _safe_getattr(step, "role_variant", None),
        "projection": _json_safe(_safe_getattr(step, "projection", {})),
        "constraint": _json_safe(_safe_getattr(step, "constraint", {})),
        "audit": _json_safe(_safe_getattr(step, "audit", {})),
        "applicability": _normalize_method_applicability(
            _safe_getattr(step, "applicability", None)
        ),
    }


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return str(value)


def _normalize_method_tags(tags: object) -> dict[str, list[str]]:
    if not isinstance(tags, Mapping):
        return {}
    return {
        key: _string_list(value)
        for key, value in sorted(tags.items())
        if isinstance(key, str) and key and _string_list(value)
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list | tuple):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _format_method_detail(method: Mapping[str, object]) -> str:
    lines = [
        f"id: {method['id']}",
        f"name: {method['name']}",
        f"kind: {method['kind']}",
    ]
    for key in ("element_type", "domain", "meta_role", "phase", "path", "description"):
        value = method.get(key)
        if value:
            lines.append(f"{key}: {value}")
    applicability_lines = _format_method_applicability_lines(
        method.get("applicability")
    )
    if applicability_lines:
        lines.append("applicability:")
        lines.extend(applicability_lines)
    lines.append("")
    lines.append(str(method.get("content", "")))
    if not lines[-1].endswith("\n"):
        lines[-1] = f"{lines[-1]}\n"
    return "\n".join(lines)


def _format_method_plan_detail(payload: Mapping[str, object]) -> str:
    method = payload.get("method")
    plan = payload.get("plan")
    steps = payload.get("steps")
    method_mapping = method if isinstance(method, Mapping) else {}
    plan_mapping = plan if isinstance(plan, Mapping) else {}
    lines = [
        f"method_id: {method_mapping.get('id', '')}",
        f"method_name: {method_mapping.get('name', '')}",
        f"plan_id: {plan_mapping.get('id', '')}",
        f"mode: {plan_mapping.get('mode', '')}",
        "steps:",
    ]
    if isinstance(steps, list):
        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, Mapping):
                continue
            lines.append(f"  {index}. {raw_step.get('id', '')} - {raw_step.get('title', '')}")
            guidance = _method_plan_step_guidance(raw_step)
            if guidance:
                lines.append(f"     guidance: {guidance}")
            constraint = _method_plan_step_mapping(raw_step, "constraint")
            if constraint:
                lines.append(f"     constraint: {json.dumps(constraint, ensure_ascii=False)}")
            audit = _method_plan_step_mapping(raw_step, "audit")
            if audit:
                lines.append(f"     audit: {json.dumps(audit, ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines)


def _method_plan_step_guidance(step: Mapping[str, object]) -> str:
    projection = step.get("projection")
    if not isinstance(projection, Mapping):
        return ""
    step_guidance = projection.get("step_guidance")
    if isinstance(step_guidance, str):
        return step_guidance.strip()
    content = projection.get("content")
    return content.strip() if isinstance(content, str) else ""


def _method_plan_step_mapping(
    step: Mapping[str, object], key: str
) -> Mapping[str, object]:
    value = step.get(key)
    return value if isinstance(value, Mapping) else {}


def _format_method_applicability_lines(applicability: object) -> list[str]:
    if not isinstance(applicability, Mapping):
        return []
    lines: list[str] = []
    for key in (
        "domains",
        "task_types",
        "contexts",
        "artifact_types",
        "modalities",
        "toolchains",
        "lifecycle",
        "capabilities",
    ):
        values = _string_list(applicability.get(key))
        if values:
            lines.append(f"  {key}: {', '.join(values)}")
    for key in ("complexity", "risk"):
        value = applicability.get(key)
        if isinstance(value, str) and value:
            lines.append(f"  {key}: {value}")
    tags = applicability.get("tags")
    if isinstance(tags, Mapping):
        for key, raw_values in sorted(tags.items()):
            values = _string_list(raw_values)
            if isinstance(key, str) and key and values:
                lines.append(f"  tags.{key}: {', '.join(values)}")
    return lines


def _safe_getattr(target: object, name: str, default: object) -> object:
    try:
        return getattr(target, name, default)
    except Exception:
        return default


__all__ = [
    "MethodListingError",
    "MethodListingRequest",
    "MethodListingResult",
    "run_method_listing",
]
