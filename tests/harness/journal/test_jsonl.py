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


def test_format_profile_preserves_unicode_and_key_order(tmp_path: Path) -> None:
    from loushang.harness.journal import (
        PROCESS_LOCAL_JOURNAL,
        SORTED_UNICODE_JSONL_FORMAT,
        append_jsonl_record,
    )

    path = tmp_path / "events.jsonl"
    append_jsonl_record(
        path,
        _Record("记录", "你好"),
        record_codec=_RecordCodec(),
        format_profile=SORTED_UNICODE_JSONL_FORMAT,
        durability=PROCESS_LOCAL_JOURNAL,
    )

    assert path.read_bytes() == ('{"recordId": "记录", "text": "你好"}\n'.encode())
    assert not path.with_name("events.jsonl.lock").exists()


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
