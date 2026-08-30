from __future__ import annotations

import json

import pytest

from loushang.harness.artifacts import SessionBlobRef, UserExportRef


def _blob_ref(**overrides: object) -> SessionBlobRef:
    values: dict[str, object] = {
        "session_id": "session-1",
        "blob_id": "a" * 64,
        "logical_name": "output/stdout.txt",
        "kind": "command-output",
        "media_type": "text/plain",
        "disclosure": "private",
        "size_bytes": 3,
        "sha256": "a" * 64,
        "created_at": 1.0,
        "source": "run-artifact:source",
    }
    values.update(overrides)
    return SessionBlobRef(**values)  # type: ignore[arg-type]


def test_session_blob_reference_round_trips_without_physical_path() -> None:
    reference = _blob_ref()

    encoded = reference.manifest_entry()
    decoded = SessionBlobRef.from_manifest_entry(encoded)

    assert decoded == reference
    serialized = json.dumps(encoded)
    assert "/tmp" not in serialized
    assert "path" not in serialized.lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", "../escape"),
        ("blob_id", "/absolute"),
        ("blob_id", "b" * 64),
        ("logical_name", "../output.txt"),
        ("logical_name", "C:\\output.txt"),
        ("sha256", "not-a-digest"),
        ("size_bytes", -1),
        ("created_at", float("nan")),
    ],
)
def test_session_blob_reference_rejects_nonportable_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _blob_ref(**{field: value})


def test_session_blob_reference_decoder_rejects_unknown_fields() -> None:
    value = _blob_ref().manifest_entry()
    value["physicalPath"] = "/tmp/leak"

    with pytest.raises(ValueError, match="keys are invalid"):
        SessionBlobRef.from_manifest_entry(value)


def test_user_export_receipt_contains_no_destination_path() -> None:
    reference = UserExportRef(
        export_id="export-1",
        logical_name="report.txt",
        kind="report",
        media_type="text/plain",
        disclosure="shareable",
        size_bytes=3,
        sha256="a" * 64,
        created_at=1.0,
        source_artifact_id="source-1",
    )

    encoded = reference.manifest_entry()

    assert "path" not in json.dumps(encoded).lower()
    assert encoded["logicalName"] == "report.txt"
