# Release history

## 0.3.0-alpha.1 — Worker federation, trust visibility, bounded finance proposals

- Separate authenticated worker service and lease-based worker registration/job records. By default its Python path requires an isolated, per-job Docker container on a separate worker VM; the unsafe subprocess path is smoke-only.
- Remote worker result digest comparison and controller-signed mission evidence.
- Loopback worker execution smoke test (real process, signed receipt); no sandbox isolation certification.
- Experimental allowlisted Chromium browser worker; production safety requirements explicitly documented.
- NEXUS task/handoff local protocol adapter and Vultr inference configuration boundary.
- Signed governance audit events and independent offline verifier.
- Encrypted, content-addressed workspace artifacts and signed custody history.
- Operator approval state machine, proposal-only spending limits, revocation, payment proposals without execution.
- UI sections for Workers, Approvals, Sealed Artifacts and Security Posture.
- Socket-free controller deployment option, per-worker manifests and CI verification workflow.
- Expanded regression coverage and package release manifest.

## 0.2.0-alpha.1 — Cryptographic evidence and encrypted memory

- Ed25519-signed mission receipts, Merkle inclusion proof, offline verification.
- AES-256-GCM encrypted mission data and workspace memory.
- Capability and integration posture registry.

## 0.1.0-alpha.1 — Initial mission control

- Web dashboard, Docker-based bounded Python tasks, persistent mission records, invoice drafts, Phantom account discovery.