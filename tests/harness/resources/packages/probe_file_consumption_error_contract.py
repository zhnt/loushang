"""Callers may preserve their original overflow error without changing defaults."""

import os
from hashlib import sha256
from io import BytesIO

import pytest

from loushang.harness.resources.packages._file_consumption import (
    FileConsumptionError,
    consume_file,
    hash_exact_size,
)


def test_default_overflow_keeps_the_original_size_error() -> None:
    with pytest.raises(FileConsumptionError) as caught:
        consume_file(BytesIO(b"too long"), max_bytes=2)
    assert caught.value.code == "size"


def test_explicit_overflow_error_has_no_added_exception_chain() -> None:
    error = ValueError("original manifest changed")
    calls = []

    def original_error():
        calls.append("overflow")
        return error

    with pytest.raises(ValueError) as caught:
        consume_file(BytesIO(b"too long"), max_bytes=2, size_error=original_error)
    assert caught.value is error
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert calls == ["overflow"]


def test_quota_keeps_priority_over_a_custom_size_error() -> None:
    calls = []
    with pytest.raises(FileConsumptionError) as caught:
        consume_file(
            BytesIO(b"too long"),
            max_bytes=2,
            quota_bytes=1,
            size_error=lambda: calls.append("unexpected") or ValueError("size"),
        )
    assert caught.value.code == "quota"
    assert calls == []


def test_valid_read_never_constructs_an_overflow_error() -> None:
    calls = []
    assert consume_file(
        BytesIO(b"valid"),
        max_bytes=5,
        chunk_size=2,
        size_error=lambda: calls.append("unexpected") or ValueError("size"),
    ) == (5, sha256(b"valid").hexdigest())
    assert calls == []


@pytest.mark.parametrize("body", [b"", b"payload"])
def test_exact_hash_leaves_trailer_to_its_caller(tmp_path, monkeypatch, body):
    path = tmp_path / "payload"
    path.write_bytes(body + b"trailer")
    original_read = os.read
    # A short successful read must not be confused with EOF.
    monkeypatch.setattr(os, "read", lambda fd, size: original_read(fd, min(size, 2)))
    with path.open("rb") as stream:
        assert hash_exact_size(stream.fileno(), len(body), truncated="short") == (
            sha256(body).hexdigest()
        )
        assert original_read(stream.fileno(), 7) == b"trailer"


def test_exact_hash_preserves_callers_truncation_error(tmp_path):
    path = tmp_path / "payload"
    path.write_bytes(b"short")
    with path.open("rb") as stream:
        with pytest.raises(ValueError, match="^original truncation$"):
            hash_exact_size(stream.fileno(), 6, truncated="original truncation")
