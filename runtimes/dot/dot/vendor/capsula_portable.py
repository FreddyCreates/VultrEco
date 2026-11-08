"""Portable VAUL <-> CAPSULA contract helpers."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
from typing import Any, Mapping

SCHEMA = "capsule.contract.v1"


class ContractError(ValueError):
    pass


def _require(obj: Mapping[str, Any], path: str, key: str) -> Any:
    if key not in obj:
        raise ContractError(f"{path}.{key} is required")
    return obj[key]


def validate_contract(bundle: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, Mapping):
        raise ContractError("capsule bundle must be an object")
    if bundle.get("schema") != SCHEMA:
        raise ContractError("unsupported capsule contract")
    capsule = _require(bundle, "bundle", "capsule")
    source = _require(bundle, "bundle", "source")
    manifest = _require(bundle, "bundle", "manifest")
    state = _require(bundle, "bundle", "sealed_state")
    permissions = _require(bundle, "bundle", "permissions")
    runtime = _require(bundle, "bundle", "runtime")
    receipts = _require(bundle, "bundle", "receipts")
    if capsule.get("mode") not in {"sealed-transfer", "fork", "read-only"}:
        raise ContractError("invalid capsule mode")
    if source.get("product") != "NOVASVAUL":
        raise ContractError("unsupported source product")
    if manifest.get("format") != "novasvaul-encrypted-records-v1":
        raise ContractError("unsupported vault format")
    if state.get("ciphertext_only") is not True:
        raise ContractError("sealed state must be ciphertext-only")
    if permissions.get("default") != "deny":
        raise ContractError("permissions must default to deny")
    if runtime.get("engine") != "NOVASVAUL":
        raise ContractError("unsupported runtime engine")
    if not isinstance(receipts, list) or not receipts:
        raise ContractError("export receipt required")
    if any(r.get("type") not in {"export", "import", "handoff"} for r in receipts):
        raise ContractError("invalid receipt type")
    return {"ok": True, "capsule_id": capsule.get("id"), "records": manifest.get("records", 0)}


def content_hash(bundle: Mapping[str, Any]) -> str:
    state = bundle["sealed_state"]
    material = {
        "manifest": state["vault_manifest"],
        "records": [{"file": r["file"], "sha256": r["sha256"], "envelope": r["envelope"]} for r in state["records"]],
    }
    import json
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_import_receipt(bundle: Mapping[str, Any], destination: str) -> dict[str, Any]:
    validate_contract(bundle)
    digest = content_hash(bundle)
    return {
        "type": "import",
        "capsule_id": bundle["capsule"]["id"],
        "operation": "capsula.import.vaul",
        "destination": destination,
        "content_hash": digest,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def accept_vaul(bundle: Mapping[str, Any], destination: str) -> dict[str, Any]:
    validate_contract(bundle)
    digest = content_hash(bundle)
    if digest != bundle["manifest"].get("content_hash"):
        raise ContractError("content hash mismatch")
    return make_import_receipt(bundle, destination)
