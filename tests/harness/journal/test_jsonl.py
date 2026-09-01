from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _Header:
    journal_id: str


@dataclass(frozen=True)
class _Record:
    record_id: str
    text: str


class _HeaderCodec:
    def encode_header(self, header: _Header):
        return {"type": "fixture", "journalId": header.journal_id}

    def decode_header(self, value):
        from loushang.harness.journal import JournalCodecError

        if value.get("type") != "fixture":
            raise JournalCodecError("missing fixture header", code="missing_header")
        return _Header(journal_id=str(value["journalId"]))


class _RecordCodec:
    def encode_record(self, record: _Record):
        return {"recordId": record.record_id, "text": record.text}

    def decode_record(self, value):
        return _Record(record_id=str(value["recordId"]), text=str(value["text"]))


def test_descriptor_relative_journal_read_stays_beneath_open_directory(
    tmp_path: Path,
) -> None:
    import os

    import pytest

    from loushang.harness.journal import read_journal_file_at

    if os.name != "posix" or os.open not in os.supports_dir_fd:
        pytest.skip("requires POSIX descriptor-relative opens")
    root = tmp_path / "root"
    root.mkdir()
    (root / "state.jsonl").write_text("trusted\n", encoding="utf-8")
    (root / "state.jsonl").chmod(0o600)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("attacker\n", encoding="utf-8")
    outside.chmod(0o600)
    (root / "linked.jsonl").symlink_to(outside)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert read_journal_file_at(descriptor, "state.jsonl") == "trusted\n"
        assert read_journal_file_at(descriptor, "missing.jsonl") == ""
        with pytest.raises(OSError):
            read_journal_file_at(descriptor, "linked.jsonl")
    finally:
        os.close(descriptor)


def test_descriptor_relative_journal_apis_reject_non_child_names() -> None:
    import pytest

    from loushang.harness.journal import journal_file_lock_at, read_journal_file_at

    for name in (
        "",
        ".",
        "..",
        "parent/child",
        "parent\\child",
        "entry:stream",
        "entry\0tail",
    ):
        with pytest.raises(ValueError, match="one direct component"):
            read_journal_file_at(-1, name)
        with pytest.raises(ValueError, match="one direct component"):
            with journal_file_lock_at(-1, name, "exclusive"):
                pass


def test_header_journal_rewrite_append_and_load_round_trip(tmp_path: Path) -> None:
    from loushang.harness.journal import (
        JournalLoadPolicy,
        append_jsonl_record,
        load_jsonl,
        write_jsonl,
    )

    path = tmp_path / "nested" / "records.jsonl"
    write_jsonl(
        path,
        [_Record("one", "alpha")],
        record_codec=_RecordCodec(),
        header=_Header("journal-1"),
        header_codec=_HeaderCodec(),
    )
    append_jsonl_record(path, _Record("two", "beta"), record_codec=_RecordCodec())

    snapshot = load_jsonl(
        path,
        record_codec=_RecordCodec(),
        header_codec=_HeaderCodec(),
        load_policy=JournalLoadPolicy(header="required"),
    )

    assert snapshot.header == _Header("journal-1")
    assert snapshot.records == (_Record("one", "alpha"), _Record("two", "beta"))
    assert not list(path.parent.glob("*.tmp"))


def test_journal_batch_append_preserves_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from loushang.harness.journal import (
        JournalLoadPolicy,
        append_jsonl_records,
        load_jsonl,
        write_jsonl,
    )
    from loushang.harness.journal import jsonl as jsonl_module

    path = tmp_path / "records.jsonl"
    write_jsonl(
        path,
        [],
        record_codec=_RecordCodec(),
        header=_Header("journal-1"),
        header_codec=_HeaderCodec(),
    )
    sync_calls = 0

    def count_sync(handle, durability) -> None:
        nonlocal sync_calls
        sync_calls += 1
        handle.flush()

    monkeypatch.setattr(jsonl_module, "_sync_handle", count_sync)

    append_jsonl_records(
        path,
        [_Record("one", "alpha"), _Record("two", "beta")],
        record_codec=_RecordCodec(),
    )

    snapshot = load_jsonl(
        path,
        record_codec=_RecordCodec(),
        header_codec=_HeaderCodec(),
        load_policy=JournalLoadPolicy(header="required"),
    )
    assert snapshot.records == (
        _Record("one", "alpha"),
        _Record("two", "beta"),
    )
    assert sync_calls == 1


def test_durable_creation_and_replace_sync_parent_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from loushang.harness.journal import append_jsonl_record, write_jsonl
    from loushang.harness.journal import jsonl as jsonl_module

    path = tmp_path / "nested" / "records.jsonl"
    synced: list[Path] = []
    monkeypatch.setattr(
        jsonl_module,
        "_sync_parent_directory",
        lambda target, _durability: synced.append(target),
    )

    append_jsonl_record(path, _Record("one", "alpha"), record_codec=_RecordCodec())
    append_jsonl_record(path, _Record("two", "beta"), record_codec=_RecordCodec())
    write_jsonl(path, [_Record("three", "gamma")], record_codec=_RecordCodec())

    assert synced == [path, path]


def test_format_profile_preserves_unicode_and_key_order(tmp_path: Path) -> None:
    from loushang.harness.journal import (
        PROCESS_LOCAL_JOURNAL,
        SORTED_UNICODE_JSONL_FORMAT,
        append_jsonl_record,
        load_jsonl,
    )

    path = tmp_path / "events.jsonl"
    record = _Record("记录", "你\u0085好\u2028世\u2029界")
    append_jsonl_record(
        path,
        record,
        record_codec=_RecordCodec(),
        format_profile=SORTED_UNICODE_JSONL_FORMAT,
        durability=PROCESS_LOCAL_JOURNAL,
    )

    assert path.read_bytes() == (
        '{"recordId": "记录", "text": "你\u0085好\u2028世\u2029界"}\n'.encode()
    )
    assert load_jsonl(
        path,
        record_codec=_RecordCodec(),
        format_profile=SORTED_UNICODE_JSONL_FORMAT,
        durability=PROCESS_LOCAL_JOURNAL,
    ).records == (record,)
    assert not path.with_name("events.jsonl.lock").exists()


def test_decoder_accepts_jsonl_cr_lf_framing() -> None:
    from loushang.harness.journal import decode_jsonl

    for newline in ("\n", "\r\n", "\r"):
        snapshot = decode_jsonl(
            newline.join(
                (
                    '{"recordId":"one","text":"alpha"}',
                    '{"recordId":"two","text":"beta"}',
                    "",
                )
            ),
            target="records.jsonl",
            record_codec=_RecordCodec(),
        )

        assert snapshot.records == (
            _Record("one", "alpha"),
            _Record("two", "beta"),
        )


def test_journal_rejects_values_outside_strict_json_algebra(tmp_path: Path) -> None:
    import pytest

    from loushang.foundation.json import JsonValueError
    from loushang.harness.journal import append_jsonl_record

    class UnsafeRecordCodec:
        def encode_record(self, record: _Record):
            return {"recordId": record.record_id, "path": Path(record.text)}

        def decode_record(self, value):
            return _Record(record_id=str(value["recordId"]), text=str(value["path"]))

    path = tmp_path / "records.jsonl"

    with pytest.raises(JsonValueError) as exc_info:
        append_jsonl_record(
            path,
            _Record("one", "notes.txt"),
            record_codec=UnsafeRecordCodec(),
        )

    assert exc_info.value.path == "journal_record.path"
    assert not path.exists()


def test_skip_invalid_records_and_partial_tail_reports_provenance(
    tmp_path: Path,
) -> None:
    from loushang.harness.journal import (
        PROCESS_LOCAL_JOURNAL,
        JournalLoadPolicy,
        load_jsonl,
    )

    path = tmp_path / "records.jsonl"
    path.write_text(
        '{"recordId":"one","text":"ok"}\nnot-json\n{"recordId":',
        encoding="utf-8",
    )

    snapshot = load_jsonl(
        path,
        record_codec=_RecordCodec(),
        durability=PROCESS_LOCAL_JOURNAL,
        load_policy=JournalLoadPolicy(
            invalid_record="skip",
            partial_tail="skip",
        ),
    )

    assert snapshot.records == (_Record("one", "ok"),)
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "invalid_journal_record",
        "partial_journal_tail",
    ]
    assert [diagnostic.line_number for diagnostic in snapshot.diagnostics] == [2, 3]
    assert all(diagnostic.source_path == path for diagnostic in snapshot.diagnostics)


def test_syntactically_complete_unterminated_record_is_not_committed(
    tmp_path: Path,
) -> None:
    from loushang.harness.journal import (
        PROCESS_LOCAL_JOURNAL,
        JournalLoadPolicy,
        load_jsonl,
    )

    path = tmp_path / "records.jsonl"
    committed = '{"recordId":"one","text":"committed\u2028still"}\n'
    tail = '{"recordId":"two","text":"not committed"}'
    path.write_text(committed + tail, encoding="utf-8")

    snapshot = load_jsonl(
        path,
        record_codec=_RecordCodec(),
        durability=PROCESS_LOCAL_JOURNAL,
        load_policy=JournalLoadPolicy(partial_tail="skip"),
    )

    assert snapshot.records == (_Record("one", "committed\u2028still"),)
    assert [item.code for item in snapshot.diagnostics] == ["partial_journal_tail"]
    assert path.read_text(encoding="utf-8") == committed + tail

    repaired = load_jsonl(
        path,
        record_codec=_RecordCodec(),
        durability=PROCESS_LOCAL_JOURNAL,
        load_policy=JournalLoadPolicy(partial_tail="repair"),
    )

    assert repaired.records == (_Record("one", "committed\u2028still"),)
    assert path.read_text(encoding="utf-8") == committed


def test_unterminated_whitespace_tail_never_removes_committed_record(
    tmp_path: Path,
) -> None:
    from loushang.harness.journal import (
        PROCESS_LOCAL_JOURNAL,
        JournalLoadPolicy,
        load_jsonl,
    )

    path = tmp_path / "records.jsonl"
    committed = '{"recordId":"one","text":"committed"}\n'
    path.write_text(committed + "   ", encoding="utf-8")

    snapshot = load_jsonl(
        path,
        record_codec=_RecordCodec(),
        durability=PROCESS_LOCAL_JOURNAL,
        load_policy=JournalLoadPolicy(partial_tail="skip"),
    )

    assert snapshot.records == (_Record("one", "committed"),)
    assert [item.line_number for item in snapshot.diagnostics] == [2]
    assert path.read_text(encoding="utf-8") == committed + "   "

    repaired = load_jsonl(
        path,
        record_codec=_RecordCodec(),
        durability=PROCESS_LOCAL_JOURNAL,
        load_policy=JournalLoadPolicy(partial_tail="repair"),
    )

    assert repaired.records == (_Record("one", "committed"),)
    assert path.read_text(encoding="utf-8") == committed


def test_repair_partial_tail_atomically_removes_only_incomplete_line(
    tmp_path: Path,
) -> None:
    from loushang.harness.journal import (
        PROCESS_LOCAL_JOURNAL,
        JournalLoadPolicy,
        JsonlJournal,
    )

    path = tmp_path / "records.jsonl"
    complete = '{"recordId":"one","text":"ok"}\n'
    path.write_text(complete + '{"recordId":', encoding="utf-8")
    journal = JsonlJournal(
        path,
        record_codec=_RecordCodec(),
        durability=PROCESS_LOCAL_JOURNAL,
        load_policy=JournalLoadPolicy(partial_tail="repair"),
    )

    snapshot = journal.load()
    journal.append(_Record("two", "after repair"))
    reloaded = journal.load()

    assert snapshot.records == (_Record("one", "ok"),)
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "partial_journal_tail"
    ]
    assert path.read_text(encoding="utf-8").startswith(complete)
    assert reloaded.records == (
        _Record("one", "ok"),
        _Record("two", "after repair"),
    )


def test_strict_load_raises_typed_file_error(tmp_path: Path) -> None:
    import pytest

    from loushang.harness.journal import (
        PROCESS_LOCAL_JOURNAL,
        JournalFileError,
        load_jsonl,
    )

    path = tmp_path / "records.jsonl"
    path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(JournalFileError) as exc_info:
        load_jsonl(
            path,
            record_codec=_RecordCodec(),
            durability=PROCESS_LOCAL_JOURNAL,
        )

    assert exc_info.value.code == "invalid_record_json"
    assert exc_info.value.line_number == 1
    assert exc_info.value.path == path


def test_strict_load_rejects_non_standard_numbers_and_invalid_unicode(
    tmp_path: Path,
) -> None:
    import pytest

    from loushang.harness.journal import (
        PROCESS_LOCAL_JOURNAL,
        JournalFileError,
        load_jsonl,
    )

    constants_path = tmp_path / "constants.jsonl"
    constants_path.write_text(
        '{"recordId":"one","text":NaN}\n',
        encoding="utf-8",
    )
    surrogate_path = tmp_path / "surrogate.jsonl"
    surrogate_path.write_bytes(b'{"recordId":"one","text":"\\ud800"}\n')

    with pytest.raises(JournalFileError) as constant_error:
        load_jsonl(
            constants_path,
            record_codec=_RecordCodec(),
            durability=PROCESS_LOCAL_JOURNAL,
        )
    with pytest.raises(JournalFileError) as surrogate_error:
        load_jsonl(
            surrogate_path,
            record_codec=_RecordCodec(),
            durability=PROCESS_LOCAL_JOURNAL,
        )

    assert constant_error.value.code == "invalid_record_json"
    assert surrogate_error.value.code == "invalid_record_value"


def test_legacy_jsonl_line_parser_is_explicit_and_syntax_only() -> None:
    from loushang.harness.journal import (
        LegacyJsonConstant,
        parse_legacy_jsonl_line,
    )

    parsed = parse_legacy_jsonl_line(
        '{"nan":NaN,"positive":Infinity,"negative":-Infinity,"text":"\\ud800"}\r\n'
    )

    assert parsed is not None
    assert parsed.ending == "\r\n"
    assert parsed.value == {
        "nan": LegacyJsonConstant("NaN"),
        "positive": LegacyJsonConstant("Infinity"),
        "negative": LegacyJsonConstant("-Infinity"),
        "text": "\ud800",
    }
    assert parse_legacy_jsonl_line("{not-json}\n") is None


def test_header_errors_remain_distinguishable(tmp_path: Path) -> None:
    import pytest

    from loushang.harness.journal import JournalFileError, JournalLoadPolicy, load_jsonl

    path = tmp_path / "records.jsonl"
    path.write_text('{"type":"record"}\n', encoding="utf-8")

    with pytest.raises(JournalFileError) as exc_info:
        load_jsonl(
            path,
            record_codec=_RecordCodec(),
            header_codec=_HeaderCodec(),
            load_policy=JournalLoadPolicy(header="required"),
        )

    assert exc_info.value.code == "missing_header"


def test_nonblocking_file_lock_reports_contention_without_waiting(tmp_path) -> None:
    import pytest

    from loushang.harness.journal import (
        JournalLockUnavailable,
        journal_file_lock,
    )

    path = tmp_path / "state.jsonl"

    with journal_file_lock(path, "exclusive"):
        with pytest.raises(JournalLockUnavailable):
            with journal_file_lock(path, "exclusive", blocking=False):
                pytest.fail("contended non-blocking lock must not be acquired")


def test_existing_journal_lock_rejects_final_symlink(tmp_path: Path) -> None:
    import pytest

    from loushang.harness.journal import journal_file_lock

    path = tmp_path / "state.jsonl"
    external = tmp_path / "external.lock"
    external.write_bytes(b"sentinel")
    external.chmod(0o600)
    path.with_name("state.jsonl.lock").symlink_to(external)

    with pytest.raises(OSError):
        with journal_file_lock(path, "exclusive", create=False):
            pytest.fail("a symlinked lock must never be acquired")

    assert external.read_bytes() == b"sentinel"


def test_existing_journal_lock_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    import os

    import pytest

    from loushang.harness.journal import journal_file_lock

    if os.name != "posix" or not hasattr(os, "mkfifo"):
        pytest.skip("FIFO lock regression is POSIX-specific")
    path = tmp_path / "state.jsonl"
    os.mkfifo(path.with_name("state.jsonl.lock"), mode=0o600)

    with pytest.raises(OSError):
        with journal_file_lock(path, "exclusive", create=False):
            pytest.fail("a FIFO lock must never be acquired")
