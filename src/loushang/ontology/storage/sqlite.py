"""SQLite v3 adapters for semantic facts and source-aware projections."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast
from uuid import UUID

from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.ontology.facts.commit import (
    CommittedFactBatch,
    prepare_fact_commit,
    prepare_guarded_fact_commit,
    require_sequence,
    select_facts_as_of,
    validate_fact_journal,
)
from loushang.ontology.facts.model import (
    FactBatch,
    FactRecord,
    FactValidationError,
)
from loushang.ontology.facts.ports import FactCommit, FactSelection, StoredFact
from loushang.ontology.projection import (
    FactOrigin,
    MaterializationCut,
    ProjectedLink,
    ProjectedObject,
    ProjectedProperty,
    ProjectionSnapshot,
    ProjectionState,
    ProjectionUnavailableError,
    SchemaDefaultOrigin,
    SourceOrigin,
)
from loushang.ontology.schema import (
    CompiledOntologySchema,
    OntologyCompiler,
    SchemaCompilationError,
    SchemaIdentity,
    ValueType,
)
from loushang.ontology.source import SourceCoverage, SourceInputCut

SQLITE_STORAGE_FORMAT = "loushang.ontology.sqlite"
SQLITE_STORAGE_FORMAT_VERSION = 3
SQLITE_STORAGE_LAYOUT = "source-aware-projection"

_REQUIRED_TABLES = frozenset(
    {
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
)
_LEGACY_TABLES = frozenset(
    {
        "authority_objects",
        "mutation_journal",
        "projection_unique_values",
    }
)
_REQUIRED_METADATA_KEYS = frozenset(
    {
        "storage_format",
        "storage_format_version",
        "storage_layout",
        "fact_watermark",
    }
)

_ORIGIN_FACT = "fact"
_ORIGIN_SOURCE = "source"
_ORIGIN_SCHEMA_DEFAULT = "schema_default"


def _encode_origin(
    origin: FactOrigin | SourceOrigin | SchemaDefaultOrigin,
) -> tuple[str, str]:
    if isinstance(origin, FactOrigin):
        kind = _ORIGIN_FACT
        document: dict[str, JSONValue] = {"fact_id": str(origin.fact_id)}
    elif isinstance(origin, SourceOrigin):
        kind = _ORIGIN_SOURCE
        document = {
            "binding_id": origin.binding_id,
            "mapping_version": origin.mapping_version,
            "source_revision": origin.source_revision,
            "source_record_ref": origin.source_record_ref,
            "field_ref": origin.field_ref,
        }
    elif isinstance(origin, SchemaDefaultOrigin):
        kind = _ORIGIN_SCHEMA_DEFAULT
        document = {"schema_identity": origin.schema_identity.to_dict()}
    else:  # pragma: no cover - public projection values prevent this state
        raise TypeError("unsupported projection origin")
    return kind, dump_json_value(document, name="projection origin", sort_keys=True)


def _decode_origin(
    kind: object,
    payload: object,
) -> FactOrigin | SourceOrigin | SchemaDefaultOrigin:
    if not isinstance(kind, str) or not isinstance(payload, str):
        raise FactValidationError("stored projection origin is invalid")
    document = require_json_mapping(json.loads(payload), name="projection origin")
    if kind == _ORIGIN_FACT:
        _require_origin_keys(document, {"fact_id"})
        return FactOrigin(UUID(_origin_text(document, "fact_id")))
    if kind == _ORIGIN_SOURCE:
        _require_origin_keys(
            document,
            {
                "binding_id",
                "mapping_version",
                "source_revision",
                "source_record_ref",
                "field_ref",
            },
        )
        return SourceOrigin(
            binding_id=_origin_text(document, "binding_id"),
            mapping_version=_origin_text(document, "mapping_version"),
            source_revision=_origin_text(document, "source_revision"),
            source_record_ref=_origin_text(document, "source_record_ref"),
            field_ref=_origin_text(document, "field_ref"),
        )
    if kind == _ORIGIN_SCHEMA_DEFAULT:
        _require_origin_keys(document, {"schema_identity"})
        return SchemaDefaultOrigin(
            SchemaIdentity.from_dict(document["schema_identity"])
        )
    raise FactValidationError(f"stored projection origin kind '{kind}' is invalid")


def _require_origin_keys(
    document: dict[str, JSONValue],
    expected: set[str],
) -> None:
    if set(document) != expected:
        raise FactValidationError("stored projection origin fields are invalid")


def _origin_text(document: dict[str, JSONValue], name: str) -> str:
    value = document[name]
    if not isinstance(value, str) or not value:
        raise FactValidationError(f"stored projection origin {name} is invalid")
    return value


class SQLiteStoreCompatibilityError(RuntimeError):
    """Base class for failures detected before a SQLite store can be used."""


class SQLiteStorageFormatError(SQLiteStoreCompatibilityError):
    """Raised when an existing database is not the source-aware v3 layout."""

    def __init__(
        self,
        database: Path,
        reason: str,
        *,
        found_format: str | None = None,
        found_version: str | None = None,
    ) -> None:
        self.database = database
        self.reason = reason
        self.expected_format = SQLITE_STORAGE_FORMAT
        self.expected_version = SQLITE_STORAGE_FORMAT_VERSION
        self.found_format = found_format
        self.found_version = found_version
        super().__init__(
            f"SQLite ontology storage at '{database}' is incompatible: {reason}"
        )


class SQLiteStoredSchemaMismatchError(SQLiteStoreCompatibilityError):
    """Raised when a database schema differs from an expected snapshot."""

    def __init__(
        self,
        database: Path,
        *,
        stored_schema: CompiledOntologySchema,
        expected_schema: CompiledOntologySchema,
    ) -> None:
        self.database = database
        self.stored_schema = stored_schema
        self.expected_schema = expected_schema
        super().__init__(
            f"SQLite ontology schema at '{database}' does not match the expected "
            f"snapshot for package '{expected_schema.package_id}' version "
            f"'{expected_schema.version}'"
        )


class _SQLiteAdapter:
    """Physical layout and validation shared by independent port adapters."""

    def __init__(
        self,
        database: str | Path,
        *,
        expected_schema: CompiledOntologySchema | None = None,
    ) -> None:
        self._database = Path(database)
        self._connection = sqlite3.connect(self._database)
        self._closed = False
        self._schema: CompiledOntologySchema | None = None
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            tables = self._database_tables()
            if tables:
                self._validate_existing_database(tables)
            else:
                self._initialize_database()
            self._schema = self._load_schema(expected_schema)
            self._validate_runtime_state()
        except SQLiteStoreCompatibilityError:
            self._connection.close()
            self._closed = True
            raise
        except (
            FactValidationError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            sqlite3.DatabaseError,
        ) as exc:
            self._connection.close()
            self._closed = True
            raise SQLiteStorageFormatError(
                self._database,
                f"stored ontology runtime data is invalid: {exc}",
            ) from exc

    @property
    def database(self) -> Path:
        return self._database

    @property
    def bound_schema(self) -> CompiledOntologySchema | None:
        return self._schema

    def bind_schema(self, schema: CompiledOntologySchema) -> None:
        self._require_open()
        if not isinstance(schema, CompiledOntologySchema):
            raise TypeError("bind_schema requires a CompiledOntologySchema")
        if self._schema is not None:
            if self._schema == schema:
                return
            raise SQLiteStoredSchemaMismatchError(
                self._database,
                stored_schema=self._schema,
                expected_schema=schema,
            )
        with self._connection:
            self._connection.execute(
                "INSERT INTO ontology_schema(singleton, payload) VALUES (1, ?)",
                (schema.to_json(),),
            )
        self._schema = schema

    def backup_to(
        self,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> None:
        """Create a transactionally consistent SQLite backup."""

        self._require_open()
        target_path = Path(destination)
        if self._database.resolve() == target_path.resolve():
            raise ValueError(
                "SQLite backup destination must differ from the source database"
            )
        if target_path.exists() and not overwrite:
            raise FileExistsError(
                f"SQLite backup destination already exists: {target_path}"
            )
        if target_path.exists():
            with NamedTemporaryFile(
                dir=target_path.parent,
                prefix=f".{target_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                staging_path = Path(temporary.name)
            try:
                self._write_backup(staging_path)
                staging_path.replace(target_path)
            finally:
                staging_path.unlink(missing_ok=True)
            return
        self._write_backup(target_path)

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def _write_backup(self, target_path: Path) -> None:
        target = sqlite3.connect(target_path)
        try:
            self._connection.backup(target)
        finally:
            target.close()

    def _database_tables(self) -> set[str]:
        try:
            return {
                name
                for (name,) in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
                if not name.startswith("sqlite_")
            }
        except sqlite3.DatabaseError as exc:
            raise SQLiteStorageFormatError(
                self._database,
                "database header or catalog is invalid",
            ) from exc

    def _validate_existing_database(self, tables: set[str]) -> None:
        if "ontology_metadata" not in tables:
            raise SQLiteStorageFormatError(
                self._database,
                "storage format metadata table is missing",
            )
        try:
            metadata = dict(
                self._connection.execute("SELECT key, value FROM ontology_metadata")
            )
        except sqlite3.DatabaseError as exc:
            raise SQLiteStorageFormatError(
                self._database,
                "storage format metadata cannot be read",
            ) from exc
        found_format = cast(str | None, metadata.get("storage_format"))
        found_version = cast(str | None, metadata.get("storage_format_version"))
        if found_format != SQLITE_STORAGE_FORMAT:
            raise SQLiteStorageFormatError(
                self._database,
                f"unsupported storage format '{found_format}'",
                found_format=found_format,
                found_version=found_version,
            )
        if found_version != str(SQLITE_STORAGE_FORMAT_VERSION):
            raise SQLiteStorageFormatError(
                self._database,
                f"unsupported storage format version '{found_version}'",
                found_format=found_format,
                found_version=found_version,
            )
        if metadata.get("storage_layout") != SQLITE_STORAGE_LAYOUT:
            raise SQLiteStorageFormatError(
                self._database,
                "pre-v3 layout is unsupported; recreate the development store",
                found_format=found_format,
                found_version=found_version,
            )
        missing_metadata = _REQUIRED_METADATA_KEYS - metadata.keys()
        if missing_metadata:
            raise SQLiteStorageFormatError(
                self._database,
                "storage format metadata is incomplete: "
                f"{', '.join(sorted(missing_metadata))}",
                found_format=found_format,
                found_version=found_version,
            )
        legacy = _LEGACY_TABLES & tables
        if legacy:
            raise SQLiteStorageFormatError(
                self._database,
                f"pre-Phase-2 tables are unsupported: {', '.join(sorted(legacy))}",
                found_format=found_format,
                found_version=found_version,
            )
        missing_tables = _REQUIRED_TABLES - tables
        if missing_tables:
            raise SQLiteStorageFormatError(
                self._database,
                "required storage tables are missing: "
                f"{', '.join(sorted(missing_tables))}",
                found_format=found_format,
                found_version=found_version,
            )

    def _initialize_database(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE ontology_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE ontology_schema (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    payload TEXT NOT NULL
                );
                CREATE TABLE semantic_facts (
                    sequence INTEGER PRIMARY KEY,
                    fact_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL
                );
                CREATE TABLE fact_batches (
                    batch_id TEXT PRIMARY KEY,
                    digest TEXT NOT NULL,
                    first_sequence INTEGER NOT NULL,
                    last_sequence INTEGER NOT NULL,
                    fact_count INTEGER NOT NULL
                );
                CREATE TABLE projection_metadata (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version TEXT NOT NULL,
                    source_fact_watermark INTEGER NOT NULL,
                    projected_fact_watermark INTEGER NOT NULL,
                    valid_at REAL NOT NULL,
                    recorded_at REAL NOT NULL,
                    projection_version INTEGER NOT NULL,
                    built_at REAL NOT NULL,
                    fact_ids_json TEXT NOT NULL,
                    fact_revalidation_digest TEXT
                );
                CREATE TABLE projection_source_inputs (
                    binding_id TEXT PRIMARY KEY,
                    mapping_version TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    coverage TEXT NOT NULL CHECK (
                        coverage IN ('complete', 'partial', 'unknown')
                    )
                );
                CREATE TABLE projection_objects (
                    object_id TEXT PRIMARY KEY,
                    object_type TEXT NOT NULL,
                    origin_kind TEXT NOT NULL CHECK (
                        origin_kind IN ('fact', 'source', 'schema_default')
                    ),
                    origin_json TEXT NOT NULL
                );
                CREATE INDEX projection_objects_type
                    ON projection_objects(object_type);
                CREATE TABLE projection_properties (
                    object_id TEXT NOT NULL,
                    property_name TEXT NOT NULL,
                    value_type TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    valid_from REAL NOT NULL,
                    fact_id TEXT,
                    author_ref TEXT,
                    source_ref TEXT NOT NULL,
                    origin_kind TEXT NOT NULL CHECK (
                        origin_kind IN ('fact', 'source', 'schema_default')
                    ),
                    origin_json TEXT NOT NULL,
                    PRIMARY KEY (object_id, property_name),
                    FOREIGN KEY (object_id) REFERENCES projection_objects(object_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX projection_property_lookup
                    ON projection_properties(property_name, value_json);
                CREATE TABLE projection_links (
                    source_id TEXT NOT NULL,
                    link_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    properties_json TEXT NOT NULL,
                    valid_from REAL NOT NULL,
                    fact_id TEXT,
                    source_ref TEXT NOT NULL,
                    origin_kind TEXT NOT NULL CHECK (
                        origin_kind IN ('fact', 'source', 'schema_default')
                    ),
                    origin_json TEXT NOT NULL,
                    PRIMARY KEY (source_id, link_type, target_id),
                    FOREIGN KEY (source_id) REFERENCES projection_objects(object_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES projection_objects(object_id)
                        ON DELETE RESTRICT
                );
                CREATE INDEX projection_links_target
                    ON projection_links(target_id, link_type);
                """
            )
            self._connection.executemany(
                "INSERT INTO ontology_metadata(key, value) VALUES (?, ?)",
                (
                    ("storage_format", SQLITE_STORAGE_FORMAT),
                    ("storage_format_version", str(SQLITE_STORAGE_FORMAT_VERSION)),
                    ("storage_layout", SQLITE_STORAGE_LAYOUT),
                    ("fact_watermark", "0"),
                ),
            )

    def _load_schema(
        self,
        expected_schema: CompiledOntologySchema | None,
    ) -> CompiledOntologySchema | None:
        row = self._connection.execute(
            "SELECT payload FROM ontology_schema WHERE singleton = 1"
        ).fetchone()
        if row is None:
            if self._database_contains_runtime_state():
                raise SQLiteStorageFormatError(
                    self._database,
                    "runtime state exists without a stored ontology schema",
                )
            return None
        try:
            stored_schema = OntologyCompiler().load_json(cast(str, row[0]))
        except SchemaCompilationError as exc:
            raise SQLiteStorageFormatError(
                self._database,
                "stored ontology schema is invalid",
            ) from exc
        if expected_schema is not None and stored_schema != expected_schema:
            raise SQLiteStoredSchemaMismatchError(
                self._database,
                stored_schema=stored_schema,
                expected_schema=expected_schema,
            )
        return stored_schema

    def _database_contains_runtime_state(self) -> bool:
        for table in (
            "semantic_facts",
            "fact_batches",
            "projection_metadata",
            "projection_source_inputs",
            "projection_objects",
            "projection_properties",
            "projection_links",
        ):
            if self._connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                return True
        return False

    def _validate_runtime_state(self) -> None:
        facts = self._read_fact_entries()
        batches = self._read_committed_batches()
        validate_fact_journal(facts, batches)
        metadata = dict(
            self._connection.execute("SELECT key, value FROM ontology_metadata")
        )
        try:
            fact_watermark = int(metadata["fact_watermark"])
        except ValueError as exc:
            raise FactValidationError("stored fact watermark is invalid") from exc
        if fact_watermark != len(facts):
            raise FactValidationError(
                "stored fact watermark does not match the semantic fact journal"
            )
        self._read_projection_snapshot()

    def _read_fact_entries(self, *, after_sequence: int = 0) -> tuple[StoredFact, ...]:
        rows = self._connection.execute(
            """
            SELECT sequence, fact_id, payload
            FROM semantic_facts
            WHERE sequence > ?
            ORDER BY sequence
            """,
            (after_sequence,),
        )
        entries: list[StoredFact] = []
        for sequence, fact_id, payload in rows:
            fact = FactRecord.from_json(cast(str, payload))
            if str(fact.fact_id) != fact_id:
                raise FactValidationError(
                    "stored semantic fact identity does not match its payload"
                )
            entries.append(StoredFact(sequence=cast(int, sequence), fact=fact))
        return tuple(entries)

    def _read_committed_batches(self) -> dict[str, CommittedFactBatch]:
        batches: dict[str, CommittedFactBatch] = {}
        for row in self._connection.execute(
            """
            SELECT batch_id, digest, first_sequence, last_sequence, fact_count
            FROM fact_batches
            ORDER BY first_sequence
            """
        ):
            batch_id, digest, first_sequence, last_sequence, fact_count = row
            if not isinstance(digest, str) or len(digest) != 64:
                raise FactValidationError("stored fact batch digest is invalid")
            commit = FactCommit(
                batch_id=cast(str, batch_id),
                first_sequence=cast(int, first_sequence),
                last_sequence=cast(int, last_sequence),
                fact_count=cast(int, fact_count),
            )
            batches[commit.batch_id] = CommittedFactBatch(
                digest=digest,
                commit=commit,
            )
        return batches

    def _read_projection_snapshot(self) -> ProjectionSnapshot | None:
        if self._connection.in_transaction:
            return self._read_projection_snapshot_in_transaction()
        self._connection.execute("BEGIN")
        try:
            snapshot = self._read_projection_snapshot_in_transaction()
            self._connection.commit()
            return snapshot
        except Exception:
            self._connection.rollback()
            raise

    def _read_projection_snapshot_in_transaction(self) -> ProjectionSnapshot | None:
        row = self._connection.execute(
            """
            SELECT schema_version, source_fact_watermark,
                   projected_fact_watermark, valid_at, recorded_at,
                   projection_version, built_at, fact_ids_json,
                   fact_revalidation_digest
            FROM projection_metadata
            WHERE singleton = 1
            """
        ).fetchone()
        projection_counts = tuple(
            cast(
                int,
                self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
            )
            for table in (
                "projection_source_inputs",
                "projection_objects",
                "projection_properties",
                "projection_links",
            )
        )
        if row is None:
            if any(projection_counts):
                raise FactValidationError(
                    "projection rows exist without projection metadata"
                )
            return None
        if self._schema is None:
            raise FactValidationError("projection exists without a stored schema")
        (
            schema_version,
            source_watermark,
            projected_watermark,
            valid_at,
            recorded_at,
            projection_version,
            built_at,
            fact_ids_json,
            fact_revalidation_digest,
        ) = row
        if source_watermark != projected_watermark:
            raise FactValidationError("stored projection build watermarks disagree")
        raw_fact_ids = json.loads(cast(str, fact_ids_json))
        if not isinstance(raw_fact_ids, list) or not all(
            isinstance(item, str) for item in raw_fact_ids
        ):
            raise FactValidationError("stored projection fact ids are invalid")
        properties_by_object: dict[UUID, list[ProjectedProperty]] = {}
        schema_identity = SchemaIdentity.from_schema(self._schema)
        source_inputs = tuple(
            SourceInputCut(
                binding_id=cast(str, binding_id),
                mapping_version=cast(str, mapping_version),
                source_revision=cast(str, source_revision),
                payload_digest=cast(str, payload_digest),
                coverage=SourceCoverage(cast(str, coverage)),
            )
            for (
                binding_id,
                mapping_version,
                source_revision,
                payload_digest,
                coverage,
            ) in self._connection.execute(
                """
                SELECT binding_id, mapping_version, source_revision,
                       payload_digest, coverage
                FROM projection_source_inputs
                ORDER BY binding_id
                """
            )
        )
        for property_row in self._connection.execute(
            """
            SELECT object_id, property_name, value_type, value_json,
                   valid_from, fact_id, author_ref, source_ref,
                   origin_kind, origin_json
            FROM projection_properties
            ORDER BY object_id, property_name
            """
        ):
            (
                object_id,
                property_name,
                value_type,
                value_json,
                property_valid_from,
                fact_id,
                author_ref,
                source_ref,
                origin_kind,
                origin_json,
            ) = property_row
            parsed_value = json.loads(cast(str, value_json))
            projected_fact_id = None if fact_id is None else UUID(cast(str, fact_id))
            projected = ProjectedProperty(
                name=cast(str, property_name),
                value_type=ValueType(cast(str, value_type)),
                value=parsed_value,
                valid_from=cast(float, property_valid_from),
                fact_id=projected_fact_id,
                author_ref=cast(str | None, author_ref),
                source_ref=cast(str, source_ref),
                origin=_decode_origin(origin_kind, origin_json),
            )
            properties_by_object.setdefault(UUID(cast(str, object_id)), []).append(
                projected
            )
        objects: list[ProjectedObject] = []
        for object_id, object_type, origin_kind, origin_json in self._connection.execute(
            """
            SELECT object_id, object_type, origin_kind, origin_json
            FROM projection_objects
            ORDER BY object_id
            """
        ):
            checked_object_id = UUID(cast(str, object_id))
            checked_object_type = cast(str, object_type)
            objects.append(
                ProjectedObject(
                    object_id=checked_object_id,
                    object_type=checked_object_type,
                    origin=cast(
                        FactOrigin | SourceOrigin,
                        _decode_origin(origin_kind, origin_json),
                    ),
                    properties=properties_by_object.get(checked_object_id, ()),
                )
            )
        links = [
            ProjectedLink(
                source_id=UUID(cast(str, source_id)),
                link_type=cast(str, link_type),
                target_id=UUID(cast(str, target_id)),
                properties=json.loads(cast(str, properties_json)),
                valid_from=cast(float, link_valid_from),
                fact_id=None if fact_id is None else UUID(cast(str, fact_id)),
                source_ref=cast(str, source_ref),
                origin=cast(
                    FactOrigin | SourceOrigin,
                    _decode_origin(origin_kind, origin_json),
                ),
            )
            for (
                source_id,
                link_type,
                target_id,
                properties_json,
                link_valid_from,
                fact_id,
                source_ref,
                origin_kind,
                origin_json,
            ) in self._connection.execute(
                """
                SELECT source_id, link_type, target_id, properties_json,
                       valid_from, fact_id, source_ref, origin_kind, origin_json
                FROM projection_links
                ORDER BY source_id, link_type, target_id
                """
            )
        ]
        state = ProjectionState(
            schema_identity=schema_identity,
            projection_version=cast(int, projection_version),
            materialization_cut=MaterializationCut(
                schema_identity=schema_identity,
                source_inputs=source_inputs,
                fact_watermark=cast(int, projected_watermark),
                valid_at=cast(float, valid_at),
                recorded_at=cast(float, recorded_at),
                fact_revalidation_digest=cast(
                    str | None,
                    fact_revalidation_digest,
                ),
            ),
            built_at=cast(float, built_at),
        )
        if cast(str, schema_version) != state.schema_version:
            raise FactValidationError(
                "stored projection schema version disagrees with stored schema"
            )
        return ProjectionSnapshot(
            schema=self._schema,
            state=state,
            objects=objects,
            links=links,
            fact_ids=(UUID(item) for item in cast(list[str], raw_fact_ids)),
        )

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("SQLite ontology adapter is closed")


class SQLiteFactStore(_SQLiteAdapter):
    """SQLite FactStore implemented directly over the semantic fact tables."""

    @property
    def schema(self) -> CompiledOntologySchema | None:
        return self.bound_schema

    @property
    def fact_watermark(self) -> int:
        self._require_open()
        return self._read_fact_watermark()

    def _read_fact_watermark(self) -> int:
        row = self._connection.execute(
            "SELECT value FROM ontology_metadata WHERE key = 'fact_watermark'"
        ).fetchone()
        assert row is not None
        return int(cast(str, row[0]))

    def get_fact(self, fact_id: UUID) -> StoredFact:
        self._require_open()
        row = self._connection.execute(
            "SELECT sequence, fact_id, payload FROM semantic_facts WHERE fact_id = ?",
            (str(fact_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown ontology fact {fact_id}")
        sequence, stored_id, payload = row
        fact = FactRecord.from_json(cast(str, payload))
        if str(fact.fact_id) != stored_id:
            raise SQLiteStorageFormatError(
                self._database,
                "stored semantic fact identity does not match its payload",
            )
        return StoredFact(sequence=cast(int, sequence), fact=fact)

    def read_facts(self, *, after_sequence: int = 0) -> tuple[StoredFact, ...]:
        self._require_open()
        after_sequence = require_sequence("after_sequence", after_sequence)
        return self._read_fact_entries(after_sequence=after_sequence)

    def select_facts(
        self,
        *,
        valid_at: float,
        recorded_at: float,
    ) -> FactSelection:
        self._require_open()
        self._connection.execute("BEGIN")
        try:
            selected = select_facts_as_of(
                self._read_fact_entries(),
                valid_at=valid_at,
                recorded_at=recorded_at,
            )
            selection = FactSelection(
                facts=selected,
                fact_watermark=self._read_fact_watermark(),
                valid_at=valid_at,
                recorded_at=recorded_at,
            )
            self._connection.commit()
            return selection
        except Exception:
            self._connection.rollback()
            raise

    def commit_fact_batch(self, batch: FactBatch) -> FactCommit:
        """Plan and persist a fact batch in one immediate SQLite transaction."""

        return self._commit_fact_batch(batch, expected_watermark=None)

    def commit_fact_batch_guarded(
        self,
        batch: FactBatch,
        *,
        expected_watermark: int,
    ) -> FactCommit:
        """Atomically compare one planning watermark and commit or replay."""

        return self._commit_fact_batch(
            batch,
            expected_watermark=expected_watermark,
        )

    def _commit_fact_batch(
        self,
        batch: FactBatch,
        *,
        expected_watermark: int | None,
    ) -> FactCommit:

        self._require_open()
        if self._schema is None:
            raise RuntimeError("SQLite fact commits require a bound schema")
        expected_identity = SchemaIdentity.from_schema(self._schema)
        if batch.schema_identity != expected_identity:
            raise FactValidationError(
                f"Fact batch targets {batch.schema_identity}, not bound schema "
                f"{expected_identity}"
            )
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            current_facts = self._read_fact_entries()
            committed_batches = self._read_committed_batches()
            plan = (
                prepare_fact_commit(
                    batch,
                    current_facts=current_facts,
                    committed_batches=committed_batches,
                )
                if expected_watermark is None
                else prepare_guarded_fact_commit(
                    batch,
                    expected_watermark=expected_watermark,
                    current_facts=current_facts,
                    committed_batches=committed_batches,
                )
            )
            if not plan.commit.replayed:
                self._connection.executemany(
                    """
                    INSERT INTO semantic_facts(sequence, fact_id, payload)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (entry.sequence, str(entry.fact.fact_id), entry.fact.to_json())
                        for entry in plan.entries
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO fact_batches(
                        batch_id, digest, first_sequence, last_sequence, fact_count
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        plan.batch.batch_id,
                        plan.digest,
                        plan.commit.first_sequence,
                        plan.commit.last_sequence,
                        plan.commit.fact_count,
                    ),
                )
                self._connection.execute(
                    "UPDATE ontology_metadata SET value = ? WHERE key = 'fact_watermark'",
                    (str(plan.commit.last_sequence),),
                )
            self._connection.commit()
            return plan.commit
        except Exception:
            self._connection.rollback()
            raise

    def __enter__(self) -> SQLiteFactStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class SQLiteProjectionStore(_SQLiteAdapter):
    """SQLite projection adapter with atomic whole-snapshot replacement."""

    @property
    def snapshot(self) -> ProjectionSnapshot | None:
        self._require_open()
        return self._read_projection_snapshot()

    @property
    def schema(self) -> CompiledOntologySchema:
        snapshot = self._require_snapshot()
        return snapshot.schema

    @property
    def projection_state(self) -> ProjectionState:
        return self._require_snapshot().state

    def read_snapshot(self) -> ProjectionSnapshot:
        return self._require_snapshot()

    def replace(self, snapshot: ProjectionSnapshot) -> ProjectionState:
        if not isinstance(snapshot, ProjectionSnapshot):
            raise TypeError("replace requires a ProjectionSnapshot")
        self._require_open()
        object_rows: list[tuple[str, str, str, str]] = []
        property_rows: list[
            tuple[
                str,
                str,
                str,
                str,
                float,
                str | None,
                str | None,
                str,
                str,
                str,
            ]
        ] = []
        link_rows: list[
            tuple[str, str, str, str, float, str | None, str, str, str]
        ] = []
        for obj in snapshot.objects:
            origin_kind, origin_json = _encode_origin(obj.origin)
            object_rows.append(
                (str(obj.id), obj.object_type, origin_kind, origin_json)
            )
            for prop in obj.properties:
                property_origin_kind, property_origin_json = _encode_origin(
                    prop.origin
                )
                property_rows.append(
                    (
                        str(obj.id),
                        prop.name,
                        prop.value_type.value,
                        dump_json_value(prop.raw_value, sort_keys=True),
                        prop.valid_from,
                        None if prop.fact_id is None else str(prop.fact_id),
                        prop.author_ref,
                        prop.source_ref,
                        property_origin_kind,
                        property_origin_json,
                    )
                )
        for link in snapshot.links:
            origin_kind, origin_json = _encode_origin(link.origin)
            link_rows.append(
                (
                    str(link.source_id),
                    link.link_type,
                    str(link.target_id),
                    dump_json_value(link.properties, sort_keys=True),
                    link.valid_from,
                    None if link.fact_id is None else str(link.fact_id),
                    link.source_ref,
                    origin_kind,
                    origin_json,
                )
            )
        self._connection.execute("BEGIN IMMEDIATE")
        if self._schema is None:
            self._schema = self._load_schema(snapshot.schema)
        install_schema = self._schema is None
        try:
            if self._schema is not None and self._schema != snapshot.schema:
                raise SQLiteStoredSchemaMismatchError(
                    self._database,
                    stored_schema=self._schema,
                    expected_schema=snapshot.schema,
                )
            current = self._read_projection_snapshot()
            expected_version = (
                1 if current is None else current.state.projection_version + 1
            )
            if snapshot.state.projection_version != expected_version:
                raise ValueError(
                    f"projection_version must be {expected_version} for this replacement"
                )
            if install_schema:
                self._connection.execute(
                    "INSERT INTO ontology_schema(singleton, payload) VALUES (1, ?)",
                    (snapshot.schema.to_json(),),
                )
            self._connection.execute("DELETE FROM projection_links")
            self._connection.execute("DELETE FROM projection_properties")
            self._connection.execute("DELETE FROM projection_objects")
            self._connection.execute("DELETE FROM projection_source_inputs")
            self._connection.executemany(
                """
                INSERT INTO projection_source_inputs(
                    binding_id, mapping_version, source_revision,
                    payload_digest, coverage
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        item.binding_id,
                        item.mapping_version,
                        item.source_revision,
                        item.payload_digest,
                        item.coverage.value,
                    )
                    for item in snapshot.state.materialization_cut.source_inputs
                ),
            )
            self._connection.executemany(
                """
                INSERT INTO projection_objects(
                    object_id, object_type, origin_kind, origin_json
                ) VALUES (?, ?, ?, ?)
                """,
                object_rows,
            )
            self._connection.executemany(
                """
                INSERT INTO projection_properties(
                    object_id, property_name, value_type, value_json,
                    valid_from, fact_id, author_ref, source_ref,
                    origin_kind, origin_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                property_rows,
            )
            self._connection.executemany(
                """
                INSERT INTO projection_links(
                    source_id, link_type, target_id, properties_json,
                    valid_from, fact_id, source_ref, origin_kind, origin_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                link_rows,
            )
            state = snapshot.state
            self._connection.execute(
                """
                INSERT INTO projection_metadata(
                    singleton, schema_version, source_fact_watermark,
                    projected_fact_watermark, valid_at, recorded_at,
                    projection_version, built_at, fact_ids_json,
                    fact_revalidation_digest
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    source_fact_watermark = excluded.source_fact_watermark,
                    projected_fact_watermark = excluded.projected_fact_watermark,
                    valid_at = excluded.valid_at,
                    recorded_at = excluded.recorded_at,
                    projection_version = excluded.projection_version,
                    built_at = excluded.built_at,
                    fact_ids_json = excluded.fact_ids_json,
                    fact_revalidation_digest = excluded.fact_revalidation_digest
                """,
                (
                    state.schema_version,
                    state.fact_watermark,
                    state.fact_watermark,
                    state.valid_at,
                    state.recorded_at,
                    state.projection_version,
                    state.built_at,
                    dump_json_value(
                        [str(fact_id) for fact_id in snapshot.fact_ids],
                        sort_keys=True,
                    ),
                    state.materialization_cut.fact_revalidation_digest,
                ),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        if install_schema:
            self._schema = snapshot.schema
        return snapshot.state

    def get(self, object_id: UUID) -> ProjectedObject | None:
        return self._require_snapshot().get(object_id)

    def get_by_type(self, object_type: str) -> tuple[ProjectedObject, ...]:
        return self._require_snapshot().get_by_type(object_type)

    def find_neighbors(
        self,
        object_id: UUID,
        link_type: str,
        direction: str = "outgoing",
    ) -> tuple[ProjectedObject, ...]:
        return self._require_snapshot().find_neighbors(
            object_id,
            link_type,
            direction,
        )

    def all_objects(self) -> tuple[ProjectedObject, ...]:
        return self._require_snapshot().all_objects()

    def _require_snapshot(self) -> ProjectionSnapshot:
        snapshot = self.snapshot
        if snapshot is None:
            raise ProjectionUnavailableError("no ontology projection is installed")
        return snapshot

    def __enter__(self) -> SQLiteProjectionStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


__all__ = [
    "SQLITE_STORAGE_FORMAT",
    "SQLITE_STORAGE_FORMAT_VERSION",
    "SQLITE_STORAGE_LAYOUT",
    "SQLiteFactStore",
    "SQLiteProjectionStore",
    "SQLiteStorageFormatError",
    "SQLiteStoreCompatibilityError",
    "SQLiteStoredSchemaMismatchError",
]
