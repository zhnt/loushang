"""Fixed Product-side SQLite ERP adapter used only as contract evidence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loushang.ontology.identity import (
    IdentityResolver,
    SourceRecordIdentity,
    require_confirmed_identity,
)
from loushang.ontology.schema import SchemaIdentity
from loushang.ontology.source import (
    ApplicationSchemaIdentity,
    MappedSourceInput,
    MappedSourceLink,
    MappedSourceObject,
    MappedSourceProperty,
    MappedSourceSnapshot,
    SourceAdapterManifest,
    SourceBinding,
    SourceCoverage,
    SourceInputRevision,
)

ERP_BINDING_ID = "reference.erp.assets"
ERP_MAPPING_VERSION = "reference-mapping/v1"
TARGET_SCHEMA_IDENTITY = SchemaIdentity(
    "reference.erp-assets",
    "urn:loushang:reference:erp-assets",
    "1.0.0",
)

ERP_SOURCE_BINDING = SourceBinding(
    binding_id=ERP_BINDING_ID,
    mapping_version=ERP_MAPPING_VERSION,
    schema_identity=TARGET_SCHEMA_IDENTITY,
    object_existence_ids=("asset", "owner"),
    property_ids=("asset.code", "owner.name"),
    link_type_ids=("asset.owned-by",),
    coverage=SourceCoverage.COMPLETE,
)

ERP_ADAPTER_MANIFEST = SourceAdapterManifest(
    adapter_id="reference.sqlite-erp-assets",
    adapter_version="1.0.0",
    application_schema=ApplicationSchemaIdentity(
        application_id="reference.erp",
        schema_version="sqlite-schema/v1",
    ),
    target_schema=TARGET_SCHEMA_IDENTITY,
    bindings=(ERP_SOURCE_BINDING,),
)


class SQLiteErpAssetAdapter:
    """Read one ERP schema using a Product-provided explicit identity resolver."""

    manifest = ERP_ADAPTER_MANIFEST

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
            owners = tuple(
                MappedSourceObject(
                    object_id=require_confirmed_identity(
                        self._identity_resolver,
                        erp_owner_source_identity(
                            self._source_instance_id,
                            owner_key,
                        ),
                    ),
                    object_type_id="owner",
                    source_record_ref=f"owner:{owner_key}",
                    identity_field_ref="erp_owners.owner_key",
                    properties=(
                        MappedSourceProperty(
                            property_id="owner.name",
                            value=owner_name,
                            field_ref="erp_owners.owner_name",
                            valid_from=valid_from,
                        ),
                    ),
                )
                for owner_key, owner_name, valid_from in connection.execute(
                    """
                    SELECT owner_key, owner_name, valid_from
                    FROM erp_owners
                    ORDER BY owner_key
                    """
                )
            )
            asset_rows = tuple(
                connection.execute(
                    """
                    SELECT asset_key, asset_code, owner_key, valid_from
                    FROM erp_assets
                    ORDER BY asset_key
                    """
                )
            )
            owner_ids = {
                owner_key: require_confirmed_identity(
                    self._identity_resolver,
                    erp_owner_source_identity(self._source_instance_id, owner_key),
                )
                for (owner_key,) in connection.execute(
                    """
                    SELECT owner_key
                    FROM erp_owners
                    ORDER BY owner_key
                    """
                )
            }
            assets = tuple(
                MappedSourceObject(
                    object_id=require_confirmed_identity(
                        self._identity_resolver,
                        erp_asset_source_identity(
                            self._source_instance_id,
                            asset_key,
                        ),
                    ),
                    object_type_id="asset",
                    source_record_ref=f"asset:{asset_key}",
                    identity_field_ref="erp_assets.asset_key",
                    properties=(
                        MappedSourceProperty(
                            property_id="asset.code",
                            value=asset_code,
                            field_ref="erp_assets.asset_code",
                            valid_from=valid_from,
                        ),
                    ),
                )
                for asset_key, asset_code, _owner_key, valid_from in asset_rows
            )
            links = tuple(
                MappedSourceLink(
                    source_id=require_confirmed_identity(
                        self._identity_resolver,
                        erp_asset_source_identity(
                            self._source_instance_id,
                            asset_key,
                        ),
                    ),
                    link_type_id="asset.owned-by",
                    target_id=owner_ids[owner_key],
                    source_record_ref=f"asset:{asset_key}:owner",
                    field_ref="erp_assets.owner_key",
                    valid_from=valid_from,
                )
                for asset_key, _asset_code, owner_key, valid_from in asset_rows
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return MappedSourceInput(
            binding_id=ERP_BINDING_ID,
            mapping_version=ERP_MAPPING_VERSION,
            source_revision=self._revision_value(revision),
            coverage=SourceCoverage.COMPLETE,
            payload=MappedSourceSnapshot(
                objects=(*assets, *owners),
                links=links,
            ),
        )

    def observe_head(self, binding_id: str) -> SourceInputRevision:
        self._require_binding(binding_id)
        connection = sqlite3.connect(self._database)
        try:
            revision = self._read_revision(connection)
        finally:
            connection.close()
        return SourceInputRevision(
            binding_id=ERP_BINDING_ID,
            mapping_version=ERP_MAPPING_VERSION,
            source_revision=self._revision_value(revision),
        )

    @staticmethod
    def _read_revision(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT revision FROM erp_metadata WHERE singleton = 1"
        ).fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0:
            raise ValueError("ERP source revision is missing or invalid")
        return row[0]

    @staticmethod
    def _revision_value(revision: int) -> str:
        return f"erp-transaction:{revision}"

    @staticmethod
    def _require_binding(binding_id: str) -> None:
        if binding_id != ERP_BINDING_ID:
            raise KeyError(f"unsupported ERP source binding '{binding_id}'")


def erp_asset_source_identity(
    source_instance_id: str,
    asset_key: str,
) -> SourceRecordIdentity:
    """Describe one ERP asset key without deciding its canonical object ID."""

    return SourceRecordIdentity(
        source_instance_id=source_instance_id,
        binding_id=ERP_BINDING_ID,
        record_type="asset",
        source_record_key=asset_key,
    )


def erp_owner_source_identity(
    source_instance_id: str,
    owner_key: str,
) -> SourceRecordIdentity:
    """Describe one ERP owner key without deciding its canonical object ID."""

    return SourceRecordIdentity(
        source_instance_id=source_instance_id,
        binding_id=ERP_BINDING_ID,
        record_type="owner",
        source_record_key=owner_key,
    )


def initialize_sqlite_erp_source(database: str | Path) -> None:
    """Create the fixed external application schema used by this fixture."""

    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE erp_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                revision INTEGER NOT NULL CHECK (revision >= 0)
            );
            CREATE TABLE erp_owners (
                owner_key TEXT PRIMARY KEY,
                owner_name TEXT NOT NULL,
                valid_from REAL NOT NULL
            );
            CREATE TABLE erp_assets (
                asset_key TEXT PRIMARY KEY,
                asset_code TEXT NOT NULL,
                owner_key TEXT NOT NULL,
                valid_from REAL NOT NULL,
                FOREIGN KEY (owner_key) REFERENCES erp_owners(owner_key)
            );
            """
        )
        connection.execute(
            "INSERT INTO erp_metadata(singleton, revision) VALUES (1, 7)"
        )
        connection.execute(
            """
            INSERT INTO erp_owners(
                owner_key, owner_name, valid_from
            ) VALUES (?, ?, ?)
            """,
            ("O-1", "Operations", 1.0),
        )
        connection.execute(
            """
            INSERT INTO erp_assets(
                asset_key, asset_code, owner_key, valid_from
            ) VALUES (?, ?, ?, ?)
            """,
            ("A-1", "A-1", "O-1", 1.0),
        )
        connection.commit()
    finally:
        connection.close()


def advance_sqlite_erp_source(database: str | Path) -> None:
    """Advance the external source after a projection has selected its cut."""

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE erp_assets SET asset_code = 'A-1-revised' WHERE asset_key = 'A-1'"
        )
        connection.execute(
            "UPDATE erp_metadata SET revision = revision + 1 WHERE singleton = 1"
        )
        connection.commit()
    finally:
        connection.close()


__all__ = [
    "ERP_ADAPTER_MANIFEST",
    "ERP_BINDING_ID",
    "SQLiteErpAssetAdapter",
    "TARGET_SCHEMA_IDENTITY",
    "advance_sqlite_erp_source",
    "erp_asset_source_identity",
    "erp_owner_source_identity",
    "initialize_sqlite_erp_source",
]
