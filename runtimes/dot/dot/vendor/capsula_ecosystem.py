"""NEXUS federation contract for CAPSULA runtime/deploy capsules."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

ACTIONS = {
    "capsula.session.create",
    "capsula.file.write",
    "capsula.session.run",
    "capsula.manifest.build",
    "capsula.deploy.plan",
    "capsula.preview.prepare",
    "capsula.wasm.plan",
}

RISK = {
    "capsula.session.create": "write-bounded",
    "capsula.file.write": "write-bounded",
    "capsula.session.run": "execute",
    "capsula.manifest.build": "read",
    "capsula.deploy.plan": "plan",
    "capsula.preview.prepare": "write-bounded",
    "capsula.wasm.plan": "plan",
}


def capability_descriptor() -> dict[str, Any]:
    return {
        "schema": "nexus.capability.v1",
        "component": "capsula",
        "repository": "ItsNotAILABS/CAPSULA",
        "role": "isolated-runtime-and-deployment-capsule-plane",
        "actions": sorted(ACTIONS),
        "risk_tiers": RISK,
        "produces": ["nexus.artifact.v1", "nexus.execution-receipt.v1", "nexus.handoff.v1"],
        "consumes": ["nexus.task.v1", "nexus.policy-decision.v1", "nexus.budget.v1", "nexus.context-pack.v1"],
        "limits": {
            "direct_production_deploy": False,
            "arbitrary_host_shell": False,
            "secrets_in_manifest": False,
            "operator_approval_for_external_deploy": True,
        },
        "proof": {"state": "source", "runtime_verification_required": True},
    }


def validate_task(task: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if task.get("schema") != "nexus.task.v1":
        errors.append("invalid_schema")
    action = task.get("action")
    if action not in ACTIONS:
        errors.append("unsupported_action")
    scope = task.get("scope") or {}
    if not isinstance(scope, Mapping) or not scope.get("project_id"):
        errors.append("project_scope_required")
    budget = task.get("budget") or {}
    limits = budget.get("limits") if isinstance(budget, Mapping) else None
    if not isinstance(limits, Mapping):
        errors.append("budget_required")
    elif action in {"capsula.file.write", "capsula.session.run"}:
        if int(limits.get("max_changed_bytes", 0) or 0) <= 0:
            errors.append("max_changed_bytes_required")
        if int(limits.get("wall_seconds", 0) or 0) <= 0:
            errors.append("wall_seconds_required")
    return {"ok": not errors, "errors": errors, "risk_tier": RISK.get(str(action))}


def make_artifact(*, artifact_id: str, kind: str, content: bytes, request_id: str) -> dict[str, Any]:
    return {
        "schema": "nexus.artifact.v1",
        "artifact_id": artifact_id,
        "kind": kind,
        "sha256": hashlib.sha256(content).hexdigest(),
        "created_by": "capsula",
        "request_id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def make_handoff(*, request_id: str, to: str, reason: str, artifacts: list[str]) -> dict[str, Any]:
    return {
        "schema": "nexus.handoff.v1",
        "request_id": request_id,
        "from": "capsula",
        "to": to,
        "reason": reason,
        "artifacts": list(artifacts),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

