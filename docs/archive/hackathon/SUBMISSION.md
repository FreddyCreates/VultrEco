# CAPSULA — Vultr Agent Rush 2026 | Alpha submission

**CAPSULA · Autonomous Agent Computer Cloud**  
**By Medina Labs**  
**Tagline:** Intelligence has a place to work.  
**Repository:** https://github.com/FreddyCreates/VultrEco  
**Release:** v0.8.0-alpha.1

## The product

CAPSULA is a scalable autonomous-computing platform on Vultr. Each agent gets
a durable identity, persistent workspace, bounded mission and access to
controlled computers. Agents write and execute code, operate isolated browsers,
coordinate subagents, work with files and data, and produce verifiable
cryptographic execution evidence. Project teams can create workflows spanning
engineering, sales, support, recruitment, research, procurement, operations,
finance and other industries—not a single-purpose demo.

Vultr Cloud Compute is the central compute layer for the controller and
separately isolated worker/agent VMs. The Vultr API exposes live instance
inventory and budget-capped fleet creation, and Vultr Serverless Inference is
the designated model lane for challenge execution. CAPSULA's PostgreSQL
control plane coordinates concurrent jobs with SKIP LOCKED, durable leases,
idempotency, retries, dead letters, and fencing epochs.

## Challenge 1 — Blast Radius Zero

**Pattern A:** User goal → model-generated Python → approval/policy →
job-specific disposable container on worker VM → constrained CPU/memory,
network denied, no task credentials → real stdout/stderr → signed result →
model explanation/retry where authorized.

**Pattern B:** User goal → model plan → isolated Playwright container →
screenshots and bounded browser evidence → authorized vision review →
human approval for sensitive final actions.

To prove containment on Vultr, demonstrate a task trying to write outside its
workspace, access network, read forbidden secrets, or exceed resource bounds;
record the actual VM/container denial and cleanup. Existing CI results do not
replace that live demonstration.

## Challenge 2 — Future of Work

CAPSULA's governed workflows combine code, browsers, documents, search, data,
persistent memory, artifacts, independently delegated agents and approvals.
Example end-to-end trajectories: engineer fixes repo and opens a reviewed PR;
analyst turns raw CSV into checks and charts; support agent researches a ticket
and drafts resolution; recruiter coordinates screening and scheduling;
operations agent checks vendor options and follows up. Real external service
connections must be configured before describing these as completed actions.

## Live integration evidence

- **Vultr Cloud API:** HTTP 200 account and instance inventory, verified through
  GitHub Actions using the repository secret.
- **Vultr VM:** one provider-reported active `capsula-control` host in DFW.
  This is not confirmation the Work OS is running on the VM.
- **PostgreSQL control plane:** real GitHub Actions database service; distributed
  queue and fencing tests; 40 jobs with four concurrent DB clients completed
  without duplicates. Not a multi-VM execution result.
- **Inference:** adapter code exists; separate Serverless Inference credential
  was absent in the last documented preflight. No live response yet.
- **Live app / worker isolation / video / LabLab final submission:** pending.

## Evidence and architecture

- Ed25519-signed receipts and Merkle event commitments, encrypted AES-256-GCM
  memory and artifacts, versioned manifests, operator-approved recursive RAH.
- Persistent Dot/KVM computers and job-specific disposable Docker execution
  environments are distinct trust boundaries.
- PostgreSQL queue is shared control-plane state, not hypervisor attestation.
- OIDC-scoped tenant APIs exist; legacy admin routes are disabled in enterprise
  mode rather than misrepresented as tenant-safe.

## Submission assets and URLs

GitHub: https://github.com/FreddyCreates/VultrEco  
Public Vultr application: **not yet verified**  
Recorded product/containment demo: **not yet available**  
Presentation: **not yet available**  
Final LabLab submission: **not submitted**

Do not publish fabricated demo results or substitute provider inventory for
live working application proof. Use [RELEASE_GATE.md](RELEASE_GATE.md) to close
the remaining deployment gates.

## v0.8 execution evidence for both tracks

CAPSULA now accepts user-selected project files and a bounded code task,
creates a disposable worker capsule, verifies cleanup and returns authenticated
output files. Enterprises can submit the same task through an OIDC-scoped
PostgreSQL queue. This is a reusable execution engine for engineering, data,
research, customer operations, document transformation and more—not a finance
vertical. Real Stripe Checkout invoice collection is an additional, separately
governed finance capability.

CI validates worker boundaries and payment anti-replay contracts. A live
Vultr multi-VM containment film and real merchant payment are not claimed.
