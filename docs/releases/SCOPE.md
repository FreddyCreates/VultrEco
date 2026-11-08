# CAPSULA alpha release scope: v0.6.0-alpha.1

## Product, not a single use case

CAPSULA is a provider-neutral autonomous work operating system. It has an operator UI,
project files, encrypted persistent memory, agents with scoped capabilities, workflows,
model planning, browser and code worker contracts, artifact provenance, governance,
finance proposals, and an opt-in persistent mission scheduler. Its playbook registry
spans engineering, analytics, research, web QA, documents, operations, support,
sales, recruiting, procurement, finance and isolated self-improvement proposals.
A playbook is a domain/capability contract, not evidence of an end-to-end business
integration. Third-party systems require actual credentialed connectors.

## Bounded autonomy

- Operator defines the mission, permitted capabilities, model, cycles, recursion,
  duration and model-planning token allowance and approves the contract.
- Scheduler claims due goals; approved models propose strict JSON step plans.
- Each proposed step is revalidated against the preapproved mission authority.
- Individual workflow approvals are issued only inside that mission's scope,
  with signed governance events correlating the parent approval and child run.
- Model steps can save memory, artifacts, run Python in a separate disposable
  worker, and inspect approved HTTPS pages using a disposable browser worker.
- Agent-generated child capsules inherit a strict subset of permissions, reserved
  token budgets, depth limits and their parent's deadline. No finance signing.
- Scheduler is a separate opt-in service. Without an approved model or active
  worker, the system returns a real failure/denial, never fake output.
- Model-reported completion is NOT trusted verification; artifact/worker evidence
  and acceptance criteria must be reviewed.

## Challenge execution paths

Pattern A: model-generated code -> reviewable plan -> separate worker daemon ->
per-job read-only/no-network Docker container -> stdout/stderr/exit -> signed
operator receipt -> optional verified retry under another approval.

Pattern B: agent plan -> allowlisted HTTPS target -> disposable Playwright
container on dedicated browser worker VM -> JPEG screenshot and page text ->
operator-pinned vision model (separate explicit capability) -> model observation.
No form submission, purchasing or browser writing is automatically allowed.
An allowlist in Python is NOT sufficient: a network-enforced HTTPS gateway is
mandatory. This browser code requires a real isolated host/network assessment.

## Portability

Vultr is a deployment/inference adapter through the same worker registration and
OpenAI-compatible model provider. Local VMs or other providers are possible; the
hackathon still requires a demonstrable Vultr VM deployment and the chosen track's
model-provider requirements. The full app does not claim vendor-side execution
until the credentials, isolated workers, URL and demo are verified.

## Explicit limitations

- Single-operator authentication, not tenant isolation / SSO / enterprise RBAC.
- No third-party hardware attestation, secure enclave proof, HSM/KMS or external
  transparency witness. Ed25519 receipts prove key-controlled integrity only.
- No fully authenticated external email, CRM, HRIS or accounting write connectors.
- No agent wallet custody, signing or actual money movement.
- Browser egress enforcement must be implemented on the actual worker network.
- Model token allowance controls CAPSULA planning requests, not external provider
  billing, and is not an exhaustive cost cap for all secondary model steps.
- Loopback worker smoke is NOT an isolation demonstration.
- Browser and Docker runtime do not run in CI here; live containment MUST be
  independently measured before declaring the Blast Radius Zero challenge passed.
