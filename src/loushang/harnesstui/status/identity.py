"""Compact identity presentation; callers retain the original identifiers."""

from collections.abc import Iterable


def short_session_ids(session_ids: Iterable[str]) -> dict[str, str]:
    """Use at least eight characters, extending colliding visible prefixes."""
    identifiers = sorted(set(session_ids))
    labels: dict[str, str] = {}
    for index, identifier in enumerate(identifiers):
        length = min(8, len(identifier))
        neighbors = (
            identifiers[max(0, index - 1) : index] + identifiers[index + 1 : index + 2]
        )
        for other in neighbors:
            shared = 0
            for left, right in zip(identifier, other):
                if left != right:
                    break
                shared += 1
            length = max(length, min(len(identifier), shared + 1))
        labels[identifier] = identifier[:length]
    return labels


def session_display_label(label: str | None, session_id: str | None) -> str:
    """Abbreviate an identity fallback, preserving an independently named label."""
    if label and label != session_id:
        return label
    if session_id:
        return short_session_ids((session_id,))[session_id]
    return label or "no-session"
