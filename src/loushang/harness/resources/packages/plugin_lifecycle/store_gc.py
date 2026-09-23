"""Exact physical Store result returned to the Package GC coordinator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreNativeIdentityV1,
    PackageStoreSettlementRecordV1,
)

PackageStoreGcDisposition = Literal["deleted", "already_absent"]


@dataclass(frozen=True, slots=True)
class PackageStoreGcResultV1:
    result_id: str
    settlement_id: str
    store_identity: str
    stable_ref_id: str
    tree_identity: PackageStoreNativeIdentityV1
    disposition: PackageStoreGcDisposition
    result_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.disposition not in {"deleted", "already_absent"}
            or self.result_version != 1
            or self.result_id
            != _result_id(
                self.settlement_id,
                self.store_identity,
                self.stable_ref_id,
                self.tree_identity,
                self.disposition,
            )
        ):
            raise ValueError("Package Store GC result identity is invalid")

    @classmethod
    def create(
        cls,
        settlement: PackageStoreSettlementRecordV1,
        *,
        disposition: PackageStoreGcDisposition,
    ) -> PackageStoreGcResultV1:
        stable_ref = settlement.receipt.stable_ref
        return cls(
            result_id=_result_id(
                settlement.settlement_id,
                settlement.store_identity,
                stable_ref.ref_id,
                settlement.tree_identity,
                disposition,
            ),
            settlement_id=settlement.settlement_id,
            store_identity=settlement.store_identity,
            stable_ref_id=stable_ref.ref_id,
            tree_identity=settlement.tree_identity,
            disposition=disposition,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "resultId": self.result_id,
            "resultVersion": self.result_version,
            "settlementId": self.settlement_id,
            "stableRefId": self.stable_ref_id,
            "storeIdentity": self.store_identity,
            "treeIdentity": self.tree_identity.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageStoreGcResultV1:
        if type(value) is not dict or set(value) != {
            "disposition",
            "resultId",
            "resultVersion",
            "settlementId",
            "stableRefId",
            "storeIdentity",
            "treeIdentity",
        }:
            raise ValueError("Package Store GC result fields are invalid")
        disposition = value["disposition"]
        if disposition not in {"deleted", "already_absent"}:
            raise ValueError("Package Store GC result disposition is invalid")
        for name in ("resultId", "settlementId", "stableRefId", "storeIdentity"):
            if type(value[name]) is not str or not value[name]:
                raise ValueError("Package Store GC result identity is invalid")
        if type(value["resultVersion"]) is not int:
            raise ValueError("Package Store GC result version is invalid")
        return cls(
            result_id=value["resultId"],
            settlement_id=value["settlementId"],
            stable_ref_id=value["stableRefId"],
            store_identity=value["storeIdentity"],
            tree_identity=PackageStoreNativeIdentityV1.from_dict(value["treeIdentity"]),
            disposition=disposition,
            result_version=value["resultVersion"],
        )


def _result_id(
    settlement_id: str,
    store_identity: str,
    stable_ref_id: str,
    tree_identity: PackageStoreNativeIdentityV1,
    disposition: PackageStoreGcDisposition,
) -> str:
    payload = json.dumps(
        [
            settlement_id,
            store_identity,
            stable_ref_id,
            tree_identity.to_dict(),
            disposition,
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(b"package-store-gc-result-v1\0" + payload).hexdigest()


__all__ = ["PackageStoreGcDisposition", "PackageStoreGcResultV1"]
