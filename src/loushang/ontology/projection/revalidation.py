"""Pure Fact-selection revalidation across ontology schema versions."""

from __future__ import annotations

from dataclasses import replace

from loushang.ontology.facts import FactSelection, StoredFact
from loushang.ontology.projection.materializer import (
    ProjectionMaterializationError,
    materialize_projection,
)
from loushang.ontology.projection.revalidation_model import (
    FactSchemaRevalidationDiagnostic,
    FactSchemaRevalidationReceipt,
    FactSchemaRevalidationStatus,
    fact_selection_digest,
    schema_content_digest,
)
from loushang.ontology.schema import (
    CompiledOntologySchema,
    SchemaIdentity,
    compare_schemas,
)


def revalidate_fact_selection(
    selection: FactSelection,
    source_schema: CompiledOntologySchema,
    target_schema: CompiledOntologySchema,
) -> FactSchemaRevalidationReceipt:
    """Validate reuse without mutating either schema or the source Facts."""

    if not isinstance(selection, FactSelection):
        raise TypeError("selection must be a FactSelection")
    if not isinstance(source_schema, CompiledOntologySchema) or not isinstance(
        target_schema,
        CompiledOntologySchema,
    ):
        raise TypeError("source_schema and target_schema must be compiled schemas")
    source_identity = SchemaIdentity.from_schema(source_schema)
    target_identity = SchemaIdentity.from_schema(target_schema)
    if any(
        item.fact.schema_identity != source_identity for item in selection.facts
    ):
        raise ValueError("Fact selection does not target the source schema identity")
    if source_identity == target_identity and source_schema != target_schema:
        raise ValueError(
            "schema content changed without changing the complete schema identity"
        )
    diff = compare_schemas(source_schema, target_schema)
    diagnostics: list[FactSchemaRevalidationDiagnostic] = []
    if source_schema.namespace != target_schema.namespace:
        diagnostics.append(
            FactSchemaRevalidationDiagnostic(
                code="namespace_changed",
                path="$.namespace",
                message="Facts cannot be revalidated across schema namespaces",
            )
        )
    try:
        materialize_projection(selection, source_schema)
    except ProjectionMaterializationError as exc:
        diagnostics.extend(
            FactSchemaRevalidationDiagnostic(
                code=f"source_{item.code}",
                path=item.path,
                message=item.message,
            )
            for item in exc.diagnostics
        )
    if not diagnostics:
        rebound = FactSelection(
            facts=tuple(
                StoredFact(
                    sequence=item.sequence,
                    fact=replace(item.fact, schema_identity=target_identity),
                )
                for item in selection.facts
            ),
            fact_watermark=selection.fact_watermark,
            valid_at=selection.valid_at,
            recorded_at=selection.recorded_at,
        )
        try:
            materialize_projection(rebound, target_schema)
        except ProjectionMaterializationError as exc:
            diagnostics.extend(
                FactSchemaRevalidationDiagnostic(
                    code=item.code,
                    path=item.path,
                    message=item.message,
                )
                for item in exc.diagnostics
            )
    diagnostic_values = tuple(
        sorted(diagnostics, key=lambda item: (item.path, item.code, item.message))
    )
    status = (
        FactSchemaRevalidationStatus.BLOCKED
        if diagnostic_values
        else FactSchemaRevalidationStatus.ACCEPTED
    )
    return FactSchemaRevalidationReceipt(
        source_schema=source_identity,
        target_schema=target_identity,
        source_schema_digest=schema_content_digest(source_schema),
        target_schema_digest=schema_content_digest(target_schema),
        fact_selection_digest=fact_selection_digest(selection),
        fact_watermark=selection.fact_watermark,
        valid_at=selection.valid_at,
        recorded_at=selection.recorded_at,
        fact_ids=tuple(item.fact.fact_id for item in selection.facts),
        schema_change_codes=tuple(
            sorted({change.code for change in diff.changes})
        ),
        status=status,
        diagnostics=diagnostic_values,
    )


__all__ = ["revalidate_fact_selection"]
