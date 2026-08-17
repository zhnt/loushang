from __future__ import annotations

from pathlib import Path

from loushang.coding.lsp.diagnostics import (
    MAX_DIAGNOSTIC_MESSAGE_CHARACTERS,
    DiagnosticInbox,
)
from loushang.coding.lsp.documents import DocumentSnapshot
from loushang.coding.lsp.model import CodePosition, CodeRange


def _snapshot(
    path: Path, *, version: int = 1, content: str = "value = 1\n"
) -> DocumentSnapshot:
    return DocumentSnapshot(
        path=path,
        uri=path.as_uri(),
        language_id="python",
        version=version,
        content=content,
        content_hash=f"hash-{version}",
    )


def _raw_diagnostic(
    message: str,
    *,
    severity: int = 1,
    start: int = 0,
    end: int = 1,
) -> dict[str, object]:
    return {
        "range": {
            "start": {"line": 0, "character": start},
            "end": {"line": 0, "character": end},
        },
        "severity": severity,
        "message": message,
        "code": 42,
        "source": "fake",
        "tags": [1, 2, 99],
    }


def test_diagnostic_inbox_normalizes_replaces_and_clears_current_set(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.py"
    document = _snapshot(source, version=3, content="a😀b\n")
    documents = {(7, document.uri): document}
    inbox = DiagnosticInbox(
        workspace_root=tmp_path,
        document_lookup=lambda runtime_id, uri: documents.get((runtime_id, uri)),
        clock=lambda: 12.5,
    )

    accepted = inbox.replace_publication(
        runtime_id=7,
        server_id="fake-python",
        uri=document.uri,
        version=3,
        diagnostics=[
            _raw_diagnostic("hint", severity=4, start=0, end=1),
            _raw_diagnostic("emoji", severity=1, start=1, end=3),
            _raw_diagnostic("emoji", severity=1, start=1, end=3),
            {"message": "missing range"},
        ],
    )

    assert accepted is True
    assert inbox.counts(7) == (1, 2)
    diagnostics = inbox.current(runtime_id=7)
    assert [item.message for item in diagnostics] == ["emoji", "hint"]
    assert diagnostics[0].server_id == "fake-python"
    assert diagnostics[0].path == "main.py"
    assert diagnostics[0].version == 3
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].range == CodeRange(
        start=CodePosition(line=1, character=2),
        end=CodePosition(line=1, character=3),
    )
    assert diagnostics[0].code == "42"
    assert diagnostics[0].source == "fake"
    assert diagnostics[0].tags == ("unnecessary", "deprecated")
    assert diagnostics[0].received_at == 12.5
    assert diagnostics[0].stale is False
    assert inbox.snapshot().omitted_diagnostic_count == 1

    assert inbox.replace_publication(
        runtime_id=7,
        server_id="fake-python",
        uri=document.uri,
        version=None,
        diagnostics=[],
    )
    assert inbox.current(runtime_id=7) == ()
    assert inbox.counts(7) == (0, 0)


def test_diagnostic_inbox_rejects_wrong_version_unknown_and_malformed_sets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "main.py"
    document = _snapshot(source, version=4)
    documents = {(2, document.uri): document}
    inbox = DiagnosticInbox(
        workspace_root=tmp_path,
        document_lookup=lambda runtime_id, uri: documents.get((runtime_id, uri)),
    )
    assert inbox.replace_publication(
        runtime_id=2,
        server_id="fake-python",
        uri=document.uri,
        version=4,
        diagnostics=[_raw_diagnostic("current")],
    )

    assert not inbox.replace_publication(
        runtime_id=2,
        server_id="fake-python",
        uri=document.uri,
        version=3,
        diagnostics=[],
    )
    assert not inbox.replace_publication(
        runtime_id=2,
        server_id="fake-python",
        uri=document.uri,
        version=5,
        diagnostics=[],
    )
    assert not inbox.replace_publication(
        runtime_id=2,
        server_id="fake-python",
        uri=(tmp_path / "unknown.py").as_uri(),
        version=4,
        diagnostics=[],
    )
    assert not inbox.replace_publication(
        runtime_id=2,
        server_id="fake-python",
        uri=document.uri,
        version="4",
        diagnostics=[],
    )

    assert [item.message for item in inbox.current(runtime_id=2)] == ["current"]
    snapshot = inbox.snapshot()
    assert snapshot.publication_count == 5
    assert snapshot.stale_publication_count == 1
    assert snapshot.future_publication_count == 1
    assert snapshot.unknown_document_publication_count == 1
    assert snapshot.malformed_publication_count == 1


def test_diagnostic_inbox_enforces_limits_and_releases_runtime(tmp_path: Path) -> None:
    paths = [tmp_path / f"file_{index}.py" for index in range(3)]
    documents = {(9, path.as_uri()): _snapshot(path) for path in paths}
    inbox = DiagnosticInbox(
        workspace_root=tmp_path,
        document_lookup=lambda runtime_id, uri: documents.get((runtime_id, uri)),
        max_documents=2,
        max_diagnostics_per_document=1,
        max_total_diagnostics=2,
        max_total_characters=16_000,
        max_raw_diagnostics_per_publication=2,
    )

    for path in paths:
        assert inbox.replace_publication(
            runtime_id=9,
            server_id="fake-python",
            uri=path.as_uri(),
            version=1,
            diagnostics=[
                _raw_diagnostic("warning", severity=2),
                _raw_diagnostic("error", severity=1),
                _raw_diagnostic("not scanned", severity=3),
            ],
        )

    assert inbox.counts(9) == (2, 2)
    assert [item.path for item in inbox.current(runtime_id=9)] == [
        "file_1.py",
        "file_2.py",
    ]
    assert all(item.message == "error" for item in inbox.current(runtime_id=9))
    snapshot = inbox.snapshot()
    assert snapshot.evicted_document_count == 1
    assert snapshot.omitted_diagnostic_count == 7

    inbox.release_runtime(9)
    assert inbox.counts(9) == (0, 0)


def test_diagnostic_inbox_bounds_large_values(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    document = _snapshot(source)
    inbox = DiagnosticInbox(
        workspace_root=tmp_path,
        document_lookup=lambda runtime_id, uri: (
            document if (runtime_id, uri) == (1, document.uri) else None
        ),
    )

    assert inbox.replace_publication(
        runtime_id=1,
        server_id="fake-python",
        uri=document.uri,
        version=None,
        diagnostics=[_raw_diagnostic("x" * (MAX_DIAGNOSTIC_MESSAGE_CHARACTERS + 50))],
    )

    diagnostic = inbox.current(runtime_id=1)[0]
    assert diagnostic.version is None
    assert len(diagnostic.message) == MAX_DIAGNOSTIC_MESSAGE_CHARACTERS
    assert inbox.snapshot().truncated_value_count == 1
