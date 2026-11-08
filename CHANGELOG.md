# CAPSULA Changelog

## 0.5.0-alpha.1 — 2026-11-08

**Autonomous capsules and broad work-platform release.**

- Added persistent opt-in autonomy service: mission contracts with operator authorization, cycles, deadlines, model planning allowance, pause/resume/cancel, and auditable delegation.
- Added two levels of scoped child capsules with reserved token allowance, inherited deadlines and capability subset enforcement; unauthorized scope expansion fails closed.
- Added 12th responsive interface section for authoring, inspecting and controlling autonomous mission trees.
- Added separate scheduler service and Docker Compose override; infrastructure remains provider-neutral.
- Added strict model-generated Python code proposals with human review, execution through separate worker path, and bounded verified-failure retry contracts.
- Added disposable browser-task runner returning page text and bounded screenshot; vision verification requires an explicitly configured visual model.
- Hardened browser runtime: no Playwright execution in persistent worker service; dedicated disposable container and operator-enforced outbound egress requirement.
- Added adversarial tests for delegated authority, budgets, invalid model plans, unavailable backends, browser containment configuration and vision media signature validation.

## 0.4.0-alpha.1 — 2026-11-08

**Standalone Work OS — no mandatory cloud provider.**

- Rebuilt the application front end as 11 task-focused responsive screens with actual wired API actions; all routes are self-contained static assets.
- Added encrypted, versioned project files with revision precondition checks and traversal-safe project paths.
- Added agent registry with capability lists, max step limits, active/disabled state and workspace isolation by logical scope.
- Added goal-to-plan inference compiler, strict plan parsing, authority validation and mandatory approval before effectful execution.
- Added durable workflows with step results, approval linkage, deterministic terminal states, stop-on-failure and encrypted result storage.
- Added permitted memory/artifact steps and explicit model-output-to-memory/artifact transfer using `{{last.output}}` for write-only steps.
- Generalized the model API to operator-pinned OpenAI-compatible endpoints (self-hosted loopback, private network or HTTPS), not Vultr-only.
- Hardened control-plane execution: direct Docker invocation disabled by default; worker required unless explicitly enabled on an isolated operator host.
- Added dedicated V4 integration/adversarial tests; retained prior v0.3 proof/governance/worker tests.
- Updated container image, Compose, release gate and CI source checks.

## 0.3.0-alpha.1 — 2026-11-04

- Leased worker registry, Python and experimental browser workers, signed governance audit and artifact custody.
- NEXUS contract adapter, proposal-only financial authorizations and non-custodial wallet discovery.

## 0.2.0-alpha.1 — 2026-11-04

- Ed25519 signer, signed Merkle event receipts, encrypted memory and offline verifiers.

## 0.1.0-alpha.1 — 2026-11-04

- Initial mission-control UI, Python sandbox prototype and SQLite mission store.
