"""Second Product-side adapter proving explicit cross-system identity fusion."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loushang.ontology.identity import (
    IdentityResolver,
    SourceRecordIdentity,
    require_confirmed_identity,
)
from loushang.ontology.source import (
    ApplicationSchemaIdentity,
    MappedSourceInput,
    MappedSourceObject,
    MappedSourceProperty,
    MappedSourceSnapshot,
    SourceAdapterManifest,
    SourceBinding,
    SourceCoverage,
    SourceInputRevision,
)
from tests.integration.ontology.fixtures.sqlite_erp_adapter import (
    TARGET_SCHEMA_IDENTITY,
)

MAINTENANCE_BINDING_ID = "reference.maintenance.assets"
MAINTENANCE_MAPPING_VERSION = "reference-maintenance-mapping/v1"

MAINTENANCE_SOURCE_BINDING = SourceBinding(
    binding_id=MAINTENANCE_BINDING_ID,
    mapping_version=MAINTENANCE_MAPPING_VERSION,
    schema_identity=TARGET_SCHEMA_IDENTITY,
    property_ids=("asset.maintenance-status",),
    coverage=SourceCoverage.COMPLETE,
)

MAINTENANCE_ADAPTER_MANIFEST = SourceAdapterManifest(
    adapter_id="reference.sqlite-maintenance-assets",
    adapter_version="1.0.0",
    application_schema=ApplicationSchemaIdentity(
        application_id="reference.maintenance",
        schema_version="sqlite-schema/v1",
    ),
    target_schema=TARGET_SCHEMA_IDENTITY,
    bindings=(MAINTENANCE_SOURCE_BINDING,),
)


class SQLiteMaintenanceAssetAdapter:
    """Map maintenance properties onto identities selected outside the Adapter."""

    manifest = MAINTENANCE_ADAPTER_MANIFEST

    def __init__(
        self,
        database: str | Path,
        *,
        source_instance_id: str,
        identity_resolver: IdentityResolver,
    ) -> None:
        if not isinstance(source_instance_id, str) or not source_instance_id.strip():
            raise ValueError("source_instance_id must be a non-empty string")
        self._database = Path(database)
        self._source_instance_id = source_instance_id
        self._identity_resolver = identity_resolver

    def read_snapshot(self, binding_id: str) -> MappedSourceInput:
        self._require_binding(binding_id)
        connection = sqlite3.connect(self._database)
        connection.execute("BEGIN")
        try:
            revision = self._read_revision(connection)
            assets = tuple(
                MappedSourceObject(
                    object_id=require_confirmed_identity(
                        self._identity_resolver,
                        maintenance_asset_source_identity(
                            self._source_instance_id,
                            equipment_code,
                        ),
                    ),
                    object_type_id="asset",
                    source_record_ref=f"equipment:{equipment_code}",
                    identity_field_ref="maintenance_assets.equipment_code",
                    properties=(
                        MappedSourceProperty(
                            property_id="asset.maintenance-status",
                            value=maintenance_status,
                            field_ref="maintenance_assets.maintenance_status",
                            valid_from=valid_from,
                        ),
                    ),
                )
                for equipment_code, maintenance_status, valid_from in (
                    connection.execute(
                        """
                        SELECT equipment_code, maintenance_status, valid_from
                        FROM maintenance_assets
                        ORDER BY equipment_code
                        """
                    )
                )
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return MappedSourceInput(
            binding_id=MAINTENANCE_BINDING_ID,
            mapping_version=MAINTENANCE_MAPPING_VERSION,
            source_revision=self._revision_value(revision),
            coverage=SourceCoverage.COMPLETE,
            payload=MappedSourceSnapshot(objects=assets),
        )

    def observe_head(self, binding_id: str) -> SourceInputRevision:
        self._require_binding(binding_id)
        connection = sqlite3.connect(self._database)
        try:
            revision = self._read_revision(connection)
        finally:
            connection.close()
        return SourceInputRevision(
            binding_id=MAINTENANCE_BINDING_ID,
            mapping_version=MAINTENANCE_MAPPING_VERSION,
            source_revision=self._revision_value(revision),
        )

    @staticmethod
    def _read_revision(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT revision FROM maintenance_metadata WHERE singleton = 1"
        ).fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0:
            raise ValueError("maintenance source revision is missing or invalid")
        return row[0]

    @staticmethod
    def _revision_value(revision: int) -> str:
        return f"maintenance-transaction:{revision}"

    @staticmethod
    def _require_binding(binding_id: str) -> None:
        if binding_id != MAINTENANCE_BINDING_ID:
            raise KeyError(f"unsupported maintenance source binding '{binding_id}'")


def maintenance_asset_source_identity(
    source_instance_id: str,
    equipment_code: str,
) -> SourceRecordIdentity:
    """Describe one maintenance record without selecting a canonical object."""

    return SourceRecordIdentity(
        source_instance_id=source_instance_id,
        binding_id=MAINTENANCE_BINDING_ID,
        record_type="equipment",
        source_record_key=equipment_code,
    )


def initialize_sqlite_maintenance_source(database: str | Path) -> None:
    """Create a second incompatible source schema for the integration fixture."""

    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE maintenance_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                revision INTEGER NOT NULL CHECK (revision >= 0)
            );
            CREATE TABLE maintenance_assets (
                equipment_code TEXT PRIMARY KEY,
                maintenance_status TEXT NOT NULL,
                valid_from REAL NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO maintenance_metadata(singleton, revision) VALUES (1, 3)"
        )
        connection.execute(
            """
            INSERT INTO maintenance_assets(
                equipment_code, maintenance_status, valid_from
            ) VALUES (?, ?, ?)
            """,
            ("EQ-009", "serviceable", 2.0),
        )
        connection.commit()
    finally:
        connection.close()


__all__ = [
    "MAINTENANCE_ADAPTER_MANIFEST",
    "MAINTENANCE_BINDING_ID",
    "SQLiteMaintenanceAssetAdapter",
    "initialize_sqlite_maintenance_source",
    "maintenance_asset_source_identity",
]
