# CAPSULA — Provider-neutral architecture, v0.4

```
Operator browser  →  CAPSULA Work OS (FastAPI + static UI)
                         │
                         ├─ Projects → encrypted versioned file ledger (SQLite + AES-GCM)
                         ├─ Agents → capability registry, role/instructions/step limit
                         ├─ Planner → pinned OpenAI-compatible inference provider
                         │                  (local/self-hosted/remote)
                         ├─ Approvals → signed governance log
                         ├─ Runs → deterministic sequential step executor
                         │      ├─ Python/browser → leased isolated worker HTTPS API
                         │      ├─ Inference → pinned compatible model endpoint
                         │      ├─ Memory → authenticated sealed workspace record
                         │      └─ Artifact → content-addressed encrypted record
                         ├─ Proof → Ed25519 + Merkle + per-mission event chain
                         ├─ Finance → unsigned proposals; browser wallet discovery
                         └─ Federation → NEXUS ingress/handoff contracts
                                            │
                       optional: Loom Cluster / Pocket Agent / LiveVault / PARRALAX
                       optional: Vultr / bare metal / Kubernetes / any VM provider
```

**Control-plane invariants:** one operator key is required for all privileged APIs; no agent can alter an operator-pinned model URL or worker allowlist; an unconfigured worker is denied; model plans remain proposals; human approval is required for Python/browser effects; no payment intent signs or transfers funds; encrypted content is authenticated to its workspace/path/revision; every sensitive state transition emits a signed governance entry.

**Trust boundary:** signature provenance establishes consistency with a signing key held by the CAPSULA installation. It cannot prove the executor host was not compromised. The Docker worker must run on a physically or virtually isolated worker host, not alongside high-value data. External telemetry/attestation, multi-user identity, external KMS, policy-enforced tenant separation and production browser isolation are future hardening gates.

**Backend contracts:** model provider receives `POST /v1/chat/completions`-compatible requests; CAPSULA workers expose `POST /execute` with a shared, operator-provisioned token and return bounded results with a digest; Nexus uses explicit `nexus.task.v1` / `nexus.handoff.v1` objects. These boundaries can be replaced with locally operated services without changing the customer UI.


### CAPSULA autonomy planes (v0.5)

Operator -> scoped mission grant (signed audit) -> opt-in scheduler -> strict
model JSON proposal -> validation -> child capsule/granted steps -> worker isolation
-> signed receipt/artifact -> retained memory/evaluation. Root mission controls
capabilities, max cycles, deadlines, planning token allowance and child slots.
Python tasks use per-job read-only, network-disabled Docker on dedicated worker VM.
Browser tasks use per-job Playwright image with network-level egress gateway;
vision review is an independent explicit model capability and never used as
cryptographic attestation. Universal playbooks are capability/risk templates,
not claims of third-party business integrations.
