from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loushang.ontology.schema import (
    ObjectTypeDefinition,
    OntologyCompiler,
    OntologyPackageDraft,
    PropertyDefinition,
    StateAuthority,
    ValueType,
)
from loushang.ontology.storage import (
    SQLITE_STORAGE_FORMAT,
    SQLITE_STORAGE_FORMAT_VERSION,
    SQLITE_STORAGE_LAYOUT,
    SQLiteFactStore,
    SQLiteStorageFormatError,
    SQLiteStoreCompatibilityError,
    SQLiteStoredSchemaMismatchError,
)


def _schema(*, version: str = "1.0.0", extra_property: bool = False):
    properties = [
        PropertyDefinition(
            "code",
            ValueType.STRING,
            semantic_id="asset.code",
            state_authority=StateAuthority.ONTOLOGY_OWNED,
        )
    ]
    if extra_property:
        properties.append(
            PropertyDefinition(
                "description",
                ValueType.STRING,
                semantic_id="asset.description",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            )
        )
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.sqlite-compatibility",
            namespace="urn:test:sqlite-compatibility",
            version=version,
            object_types=[
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    properties=properties,
                )
            ],
        )
    )


def _tables(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not name.startswith("sqlite_")
        }


def test_new_database_uses_only_the_source_aware_v3_layout(tmp_path: Path) -> None:
    database = tmp_path / "ontology.sqlite3"
    SQLiteFactStore(database).close()

    with sqlite3.connect(database) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM ontology_metadata"))

    assert metadata == {
        "storage_format": SQLITE_STORAGE_FORMAT,
        "storage_format_version": str(SQLITE_STORAGE_FORMAT_VERSION),
        "storage_layout": SQLITE_STORAGE_LAYOUT,
        "fact_watermark": "0",
    }
    assert _tables(database) == {
        "ontology_metadata",
        "ontology_schema",
        "semantic_facts",
        "fact_batches",
        "projection_metadata",
        "projection_source_inputs",
        "projection_objects",
        "projection_properties",
        "projection_links",
    }
    assert not {
        "authority_objects",
        "mutation_journal",
        "projection_unique_values",
    } & _tables(database)


def test_non_ontology_database_is_rejected_without_initialization(
    tmp_path: Path,
) -> None:
    database = tmp_path / "other.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE application_data(id INTEGER PRIMARY KEY)")
    before = _tables(database)

    with pytest.raises(SQLiteStorageFormatError, match="storage format metadata"):
        SQLiteFactStore(database)

    assert _tables(database) == before


def test_unsupported_version_is_rejected_without_upgrade(tmp_path: Path) -> None:
    database = tmp_path / "future.sqlite3"
    SQLiteFactStore(database).close()
    future_version = SQLITE_STORAGE_FORMAT_VERSION + 1
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE ontology_metadata SET value = ? WHERE key = 'storage_format_version'",
            (str(future_version),),
        )

    with pytest.raises(SQLiteStorageFormatError) as exc_info:
        SQLiteFactStore(database)

    assert exc_info.value.expected_version == SQLITE_STORAGE_FORMAT_VERSION
    assert exc_info.value.found_version == str(future_version)


def test_pre_v3_layout_is_rejected_for_explicit_recreation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "old-v2.sqlite3"
    SQLiteFactStore(database).close()
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM ontology_metadata WHERE key = 'storage_layout'")
        connection.execute("CREATE TABLE authority_objects(object_id TEXT PRIMARY KEY)")
    before = database.read_bytes()

    with pytest.raises(
        SQLiteStorageFormatError, match="recreate the development store"
    ):
        SQLiteFactStore(database)

    assert database.read_bytes() == before


def test_v2_store_is_rejected_without_a_compatibility_reader(tmp_path: Path) -> None:
    database = tmp_path / "old-v2.sqlite3"
    SQLiteFactStore(database).close()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE ontology_metadata SET value = '2' "
            "WHERE key = 'storage_format_version'"
        )
        connection.execute(
            "UPDATE ontology_metadata SET value = 'phase2' "
            "WHERE key = 'storage_layout'"
        )
    before = database.read_bytes()

    with pytest.raises(SQLiteStorageFormatError) as exc_info:
        SQLiteFactStore(database)

    assert exc_info.value.found_version == "2"
    assert database.read_bytes() == before


def test_missing_required_table_or_metadata_is_rejected(tmp_path: Path) -> None:
    missing_table = tmp_path / "missing-table.sqlite3"
    SQLiteFactStore(missing_table).close()
    with sqlite3.connect(missing_table) as connection:
        connection.execute("DROP TABLE projection_links")
    with pytest.raises(SQLiteStorageFormatError, match="projection_links"):
        SQLiteFactStore(missing_table)

    missing_metadata = tmp_path / "missing-metadata.sqlite3"
    SQLiteFactStore(missing_metadata).close()
    with sqlite3.connect(missing_metadata) as connection:
        connection.execute("DELETE FROM ontology_metadata WHERE key = 'fact_watermark'")
    with pytest.raises(SQLiteStorageFormatError, match="fact_watermark"):
        SQLiteFactStore(missing_metadata)


def test_schema_corruption_and_content_mismatch_are_public_failures(
    tmp_path: Path,
) -> None:
    database = tmp_path / "schema.sqlite3"
    schema = _schema()
    store = SQLiteFactStore(database)
    store.bind_schema(schema)
    store.close()

    reopened = SQLiteFactStore(database, expected_schema=schema)
    reopened.close()
    with pytest.raises(SQLiteStoredSchemaMismatchError) as mismatch:
        SQLiteFactStore(database, expected_schema=_schema(extra_property=True))
    assert mismatch.value.stored_schema == schema

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE ontology_schema SET payload = '{not-json' WHERE singleton = 1"
        )
    with pytest.raises(SQLiteStorageFormatError, match="stored ontology schema"):
        SQLiteFactStore(database)


def test_bind_schema_and_backup_have_explicit_failure_contracts(tmp_path: Path) -> None:
    database = tmp_path / "ontology.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    store = SQLiteFactStore(database)
    store.bind_schema(_schema())
    with pytest.raises(SQLiteStoredSchemaMismatchError):
        store.bind_schema(_schema(extra_property=True))

    backup.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="backup destination"):
        store.backup_to(backup)
    assert backup.read_text(encoding="utf-8") == "keep"
    store.backup_to(backup, overwrite=True)
    SQLiteFactStore(backup, expected_schema=_schema()).close()
    store.close()
    store.close()

    assert issubclass(SQLiteStorageFormatError, SQLiteStoreCompatibilityError)
    assert issubclass(SQLiteStoredSchemaMismatchError, SQLiteStoreCompatibilityError)
