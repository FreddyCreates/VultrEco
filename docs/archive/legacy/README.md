# CAPSULA

**Intelligence has a place to work.**  
Medina Labs — Vultr Agent Rush — **`v0.3.0-alpha.1`**

CAPSULA is a governed execution platform with sandbox workers, durable missions, sealed memory, independently verifiable cryptographic evidence, local NEXUS-compatible task contracts, and non-custodial financial proposals. This is the new application housed in `FreddyCreates/VultrEco`, separate from the canonical `ItsNotAILABS/CAPSULA` runtime repository.

## Implemented and locally tested

- Responsive dashboard: Missions, Computers, Workers, Receipts, Approvals, Encrypted Memory, Sealed Artifacts, Wallet/Pay, Security, Settings.
- SQLite mission/workspace persistence encrypted with AES-256-GCM; separate signing key with Ed25519; protocol v2 proof bundles, Merkle inclusion proofs and offline verifiers.
- Signed governance audit stream for worker registration, approvals, payment proposals, proposal grants, and artifact custody; offline verifier with separately pinned public key.
- Worker registry: operator-allowlisted origins, 45-second worker leases, authenticated heartbeats, job dispatch and job history, exact status reporting.
- Separate Python worker service with resource-constrained subprocess execution intended to run inside a hardened isolated VM/container; Docker-backed per-job execution on a dedicated worker VM; worker service has administrative access to that VM's Docker daemon, not the control-plane daemon.
- Experimental Playwright browser worker with exact HTTPS domain allowlist; **not safe for hostile browsing without an independent VM plus network-level egress controls**.
- NEXUS ingress `nexus.task.v1` → bounded CAPSULA mission → `nexus.handoff.v1` response; no claim of an externally activated NEXUS deployment.
- Configurable Vultr inference HTTP adapter with pinned host, allowlisted models, limited token budget and no fallback. Not tested against a live Vultr account without credentials.
- Phantom wallet account discovery via browser; payment proposals and short-lived proposal-only budgets; **no spending, custody, chain broadcasting, invoice settlement, or agent signing**.
- Structured integration inventory for Loom Cluster, POCKET Agent, NOVA Runtime, LiveVault, PARRALAX, Triple-MCP and Medina Memory; remote integrations remain **unconnected**.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export CAPSULA_API_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
uvicorn app:app --host 127.0.0.1 --port 8080
```

The dashboard uses a browser-session API key. It is a single-operator alpha, not a multi-user deployment. With no Docker daemon or registered worker, execution fails closed.

## Worker deployment

Run the controller on a separate control-plane VM using `docker-compose.production.yml` (no Docker socket). Run an isolated worker via `docker-compose.worker.yml` on a separate worker VM with enforced outbound network restrictions. Set `CAPSULA_WORKER_TOKEN` and `CAPSULA_WORKER_ALLOWED_ENDPOINTS` on the controller, and a matching token on the worker. Use HTTPS for remote workers. The HTTP loopback mode is strictly local development. `smoke_worker.py` deliberately enables an unsafe direct-subprocess path for trusted literal code only; it does not test Docker isolation. Register worker with `/api/workers` and refresh its lease with `/api/workers/{id}/heartbeat` using worker authentication. Browser workers require independent VM boundary and egress proxy; see `WORKER_SECURITY.md`.

## Test and evidence

```bash
pytest -q
python smoke_worker.py
python release_validate.py
```

`smoke_worker.py` launches an actual loopback worker process, dispatches Python `print(6*7)`, and verifies the signed mission receipt. This does **not** demonstrate VM isolation.

Mission evidence: `GET /api/missions/{id}/evidence`, verify with `python verify_evidence.py evidence.json --public-key PINNED_KEY`. Signed governance audit: `GET /api/audit`, verify with `python verify_governance.py audit.json --public-key PINNED_KEY`.

## API slices

- `/api/health`, `/api/overview`, `/api/security/posture`, `/api/integrations`, `/api/federation/contracts`
- `/api/missions`, `/api/missions/{id}`, `/api/missions/{id}/evidence`
- `/api/workers`, `/api/workers/{id}/heartbeat`, `/api/jobs`
- `/api/approvals`, `/api/approvals/{id}/decide`, `/api/audit`
- `/api/workspaces`, `/api/memory`, `/api/artifacts`
- `/api/federation/nexus/task`, `/api/inference/complete`
- `/api/invoices`, `/api/finance/intents`, `/api/finance/grants`

## Required before 1.0

Full Loom Cluster scheduling and orchestration, actual POCKET Agent recursive worker integration, production browser isolation, verifiable external anchoring/attestation, external KMS/LiveVault, secure multi-user identity, live Vultr deployment, production chain signing/settlement, payment compliance, observability/load testing, and independent security review. None is claimed complete here.

See `ARCHITECTURE.md`, `WORKER_SECURITY.md`, `OPERATOR_BOUNDARY.md`, `PRODUCTION.md`, `DEPLOYMENT.md`, and `CHANGELOG.md`.

## Vultr Agent Rush 2026 submission

CAPSULA targets **Challenge 1: Blast Radius Zero**. This repository contains a control-plane web application and a separate worker API designed for Vultr Cloud Compute. Challenge 1 requires both actual sandboxed execution **on Vultr** and **Vultr Serverless Inference** for agent model calls. The inference adapter and separate worker deployment recipes are present, but a live Vultr deployment/inference call has not been verified in this release.

Submission content and required demonstration scripts are in [`hackathon/SUBMISSION.md`](hackathon/SUBMISSION.md), [`hackathon/DEMO_RUNBOOK.md`](hackathon/DEMO_RUNBOOK.md), and [`hackathon/RELEASE_GATE.md`](hackathon/RELEASE_GATE.md). To generate non-destructive containment-probe code, run `python scripts/containment_probe.py`; submit its output **only inside an isolated per-job worker**, not on the control-plane host.

The user-facing web app and controller should be deployed on a Vultr VM with HTTPS at the edge, while untrusted execution must occur inside throwaway sandbox containers on a dedicated worker VM. The controller does not receive a Docker socket. Workers must not receive private keys or user wallet signing secrets. The GitHub repo, demo URL, and evidence must be publicly accessible for the official submission. No claim of a deployed system is made until verified.