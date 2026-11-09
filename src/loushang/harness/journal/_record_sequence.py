"""Numbered receipt names; owners keep IO, codecs, phase validation and locks."""

from __future__ import annotations

from collections.abc import Iterable
from re import Pattern


def scan_numbered_revisions(
    names: Iterable[str],
    *,
    prefix: str,
    pattern: Pattern[str],
    max_records: int,
    unexpected_member: str,
    invalid_revision: str,
    invalid_sequence: str,
) -> tuple[int, int | None]:
    published: set[int] = set()
    staged: set[int] = set()
    for name in names:
        if not name.startswith(prefix):
            continue
        match = pattern.fullmatch(name)
        if match is None:
            raise ValueError(unexpected_member)
        revision = int(match.group(1))
        if revision < 1:
            raise ValueError(invalid_revision)
        (staged if match.group(2) else published).add(revision)
    if (
        len(published) > max_records
        or len(staged) > 1
        or published != set(range(1, len(published) + 1))
        or (staged and staged != {len(published) + 1})
    ):
        raise ValueError(invalid_sequence)
    return len(published), next(iter(staged)) if staged else None
