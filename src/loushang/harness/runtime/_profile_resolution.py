"""Deterministic admission and resolution for Product runtime profiles."""

from __future__ import annotations

from collections.abc import Iterable

from loushang.foundation.json import JSONValue, dump_json_value
from loushang.harness.runtime._profile_types import (
    ProductRuntimePlan,
    ResolvedRuntimeCapability,
    ResolvedRuntimeProfile,
    ResolvedRuntimeSelection,
    RuntimeCapabilitySelection,
    RuntimeCapabilitySlot,
    RuntimeProfileDiagnostic,
    RuntimeProfileLayer,
    RuntimeProfileResolutionError,
)

_SOURCE_RANK = {
    "product": 0,
    "oem": 1,
    "extension": 2,
    "session": 3,
}


class RuntimeProfileResolver:
    """Resolve Product, OEM, extension, and session layers deterministically."""

    def resolve(
        self,
        plan: ProductRuntimePlan,
        *,
        layers: Iterable[RuntimeProfileLayer] = (),
    ) -> ResolvedRuntimeProfile:
        supplied_layers = tuple(layers)
        if any(not isinstance(layer, RuntimeProfileLayer) for layer in supplied_layers):
            raise TypeError(
                "runtime profile layers must contain RuntimeProfileLayer values"
            )

        diagnostics: list[RuntimeProfileDiagnostic] = []
        known_slots = {slot.key: slot for slot in plan.slots}
        candidates: dict[str, list[ResolvedRuntimeSelection]] = {
            slot.key: [] for slot in plan.slots
        }
        product_layer = RuntimeProfileLayer(
            source="product",
            layer_id=f"product:{plan.product_id}",
            selections=plan.defaults,
        )
        ordered_layers = (product_layer,) + self._ordered_external_layers(
            supplied_layers, diagnostics
        )

        for layer in ordered_layers:
            grouped: dict[str, list[RuntimeCapabilitySelection]] = {}
            for selection in layer.selections:
                grouped.setdefault(selection.slot, []).append(selection)
            for slot_key, selections in grouped.items():
                slot = known_slots.get(slot_key)
                if slot is None:
                    diagnostics.append(
                        RuntimeProfileDiagnostic(
                            code="unknown_slot",
                            message="selection targets a slot absent from the Product plan",
                            slot=slot_key,
                            source=layer.source,
                            layer_id=layer.layer_id,
                        )
                    )
                    continue
                if layer.source not in slot.allowed_sources:
                    allowed_sources_json: list[JSONValue] = [
                        source for source in sorted(slot.allowed_sources)
                    ]
                    diagnostics.append(
                        RuntimeProfileDiagnostic(
                            code="source_not_allowed",
                            message="source is not authorized to select this slot",
                            slot=slot_key,
                            source=layer.source,
                            layer_id=layer.layer_id,
                            details={"allowedSources": allowed_sources_json},
                        )
                    )
                    continue
                if slot.shape in {"single", "exclusive"} and len(selections) > 1:
                    diagnostics.append(
                        RuntimeProfileDiagnostic(
                            code="ambiguous_single_selection",
                            message="a single or exclusive slot has multiple selections in one layer",
                            slot=slot_key,
                            source=layer.source,
                            layer_id=layer.layer_id,
                        )
                    )
                    continue
                for selection in sorted(selections, key=_selection_order_key):
                    candidates[slot_key].append(
                        ResolvedRuntimeSelection(
                            selection=selection,
                            source=layer.source,
                            layer_id=layer.layer_id,
                            layer_priority=layer.priority,
                        )
                    )

        if diagnostics:
            raise RuntimeProfileResolutionError(diagnostics)

        capabilities: list[ResolvedRuntimeCapability] = []
        for slot in plan.slots:
            resolved = self._resolve_slot(slot, candidates[slot.key], diagnostics)
            capabilities.append(
                ResolvedRuntimeCapability(slot=slot, selections=resolved)
            )
        if diagnostics:
            raise RuntimeProfileResolutionError(diagnostics)
        return ResolvedRuntimeProfile(
            product_id=plan.product_id,
            capabilities=tuple(capabilities),
            schema_version=plan.schema_version,
        )

    @staticmethod
    def _ordered_external_layers(
        layers: tuple[RuntimeProfileLayer, ...],
        diagnostics: list[RuntimeProfileDiagnostic],
    ) -> tuple[RuntimeProfileLayer, ...]:
        seen: set[tuple[str, str]] = set()
        valid: list[RuntimeProfileLayer] = []
        for layer in layers:
            identity = (layer.source, layer.layer_id)
            if layer.source == "product":
                diagnostics.append(
                    RuntimeProfileDiagnostic(
                        code="product_layer_not_allowed",
                        message="Product defaults must be declared on ProductRuntimePlan",
                        source=layer.source,
                        layer_id=layer.layer_id,
                    )
                )
                continue
            if identity in seen:
                diagnostics.append(
                    RuntimeProfileDiagnostic(
                        code="duplicate_layer",
                        message="a source may contribute one layer with a given layer id",
                        source=layer.source,
                        layer_id=layer.layer_id,
                    )
                )
                continue
            seen.add(identity)
            valid.append(layer)
        return tuple(
            sorted(
                valid,
                key=lambda layer: (
                    _SOURCE_RANK[layer.source],
                    layer.priority,
                    layer.layer_id,
                ),
            )
        )

    @staticmethod
    def _resolve_slot(
        slot: RuntimeCapabilitySlot,
        candidates: list[ResolvedRuntimeSelection],
        diagnostics: list[RuntimeProfileDiagnostic],
    ) -> tuple[ResolvedRuntimeSelection, ...]:
        ordered = tuple(sorted(candidates, key=_resolved_selection_order_key))
        if slot.shape in {"single", "exclusive"}:
            result = ordered[-1:] if ordered else ()
        elif slot.shape == "ordered":
            latest: dict[tuple[str, int], ResolvedRuntimeSelection] = {}
            for candidate in ordered:
                identity = (
                    candidate.selection.implementation,
                    candidate.selection.implementation_version,
                )
                latest[identity] = candidate
            result = tuple(sorted(latest.values(), key=_resolved_selection_order_key))
        else:
            result = ordered
        if slot.required and not result:
            diagnostics.append(
                RuntimeProfileDiagnostic(
                    code="missing_required_selection",
                    message="required slot has no active selection",
                    slot=slot.key,
                )
            )
        return result


def _selection_order_key(selection: RuntimeCapabilitySelection) -> tuple[object, ...]:
    return (
        selection.priority,
        selection.implementation,
        selection.implementation_version,
        dump_json_value(selection.config, name="selection config", sort_keys=True),
    )


def _resolved_selection_order_key(
    resolved: ResolvedRuntimeSelection,
) -> tuple[object, ...]:
    return (
        _SOURCE_RANK[resolved.source],
        resolved.layer_priority,
        resolved.layer_id,
        *_selection_order_key(resolved.selection),
    )
