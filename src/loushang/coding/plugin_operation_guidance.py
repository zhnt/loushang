"""Path-free Coding repair hints derived from exact operation owner evidence."""

from __future__ import annotations

import shlex


def coding_desired_repair_command(actor_id: str, operation_id: str) -> str | None:
    if not operation_id or not operation_id.isascii() or not operation_id.isprintable():
        return None
    if actor_id == "coding:cli":
        return "loushang --repair-plugin-desired-operation " + shlex.quote(
            operation_id
        )
    if actor_id == "coding:tui" and " " not in operation_id:
        return "/plugins repair " + operation_id
    return None


def project_coding_plugin_operation_guidance(
    document: dict[str, object],
) -> dict[str, object]:
    """Keep A1/A2 repair routes bound to their originating actor and owner."""

    operation_id = document.get("operationId")
    kind = document.get("operationKind")
    actor_id = document.get("managementActorId")
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or not operation_id.isascii()
        or not operation_id.isprintable()
        or kind not in {"a1_desired", "a2_package", "unknown"}
        or (actor_id is not None and not isinstance(actor_id, str))
    ):
        raise ValueError("Coding Plugin operation guidance identity is invalid")
    repair: str | None = None
    package = document.get("package")
    if (
        kind == "a1_desired"
        and actor_id is not None
        and document.get("managementStatus") == "observed"
        and document.get("managementDisposition") is None
        and document.get("managementProgressCode")
        in {"command_accepted", "desired_state_committing"}
    ):
        repair = coding_desired_repair_command(actor_id, operation_id)
    elif (
        kind == "a2_package"
        and actor_id == "product:coding"
        and document.get("joinStatus") == "same_identity"
        and document.get("handoffEvidence") == "incomplete"
        and document.get("desiredCommitEvidence")
        in {"owner_receipt", "verified_transition"}
        and isinstance(package, dict)
        and package.get("disposition") == "committed"
    ):
        repair = "loushang-package-repair repair-handoff " + shlex.quote(
            operation_id
        )
    return {**document, "repairCommand": repair}


__all__ = [
    "coding_desired_repair_command",
    "project_coding_plugin_operation_guidance",
]
